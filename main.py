import os
from datetime import datetime
from typing import Dict, List
from fastapi import FastAPI, Request, HTTPException, status, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from google.cloud import firestore
from google.oauth2 import id_token
from google.auth.transport import requests
from fastapi import UploadFile, File
from fastapi import Form
from fastapi import status
from datetime import datetime

# Then use:
status.HTTP_302_FOUND

# Load Firebase credentials
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "firebase-key.json"

# Setup Firestore client
db = firestore.Client()
firebase_request_adapter = requests.Request()

# Setup FastAPI app
app = FastAPI()

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific origin(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")



# ------------------- Helper -------------------

def verify_user(request: Request) -> Dict:
    token_cookie = request.cookies.get("token")
    if not token_cookie:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        claims = id_token.verify_firebase_token(token_cookie, firebase_request_adapter)
        return {
            "user_id": claims["user_id"],
            "email": claims.get("email"),
            "username": claims.get("name") or claims.get("email").split("@")[0]
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

def get_user_data(user_id: str) -> Dict:
    """Helper function to fetch user data and ensure 'followers' and 'following' are initialized."""
    user_ref = db.collection("User").document(user_id)
    user_doc = user_ref.get()
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user_doc.to_dict()
    user_data.setdefault("followers", [])
    user_data.setdefault("following", [])
    return user_data

def get_current_user(request: Request) -> Dict:
    """Returns the current user, used in Depends."""
    return verify_user(request)

# ------------------- Routes -------------------


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    try:
        user = verify_user(request)
        user_ref = db.collection("User").document(user["user_id"])
        user_doc = user_ref.get()

        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="User not found")

        user_data = user_doc.to_dict()
        following_users = user_data.get("following", [])

        posts_list = []

        # Get user's own posts
        posts_ref = db.collection("Post").where("user_id", "==", user["user_id"]).order_by("date", direction=firestore.Query.DESCENDING).limit(50)
        posts = posts_ref.stream()
        for post in posts:
            post_data = post.to_dict()
            post_data["id"] = post.id
            
            # Convert and format date
            if isinstance(post_data.get("date"), str):
                try:
                    post_data["date"] = datetime.fromisoformat(post_data["date"])
                except ValueError:
                    post_data["date"] = None  # If the date format is invalid, set it to None

            if post_data["date"]:
                post_data["formatted_date"] = post_data["date"].strftime('%B %d, %Y, %I:%M %p')  # Format date

            # Fetch 5 latest comments for this post
            comments_ref = db.collection("Post").document(post.id).collection("Comments").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(5)
            comments = comments_ref.stream()
            post_data["comments"] = [{"username": c.get("username"), "content": c.get("content")} for c in comments]
            posts_list.append(post_data)

        # Get posts from people the user follows
        for follow_id in following_users:
            posts_ref = db.collection("Post").where("user_id", "==", follow_id).order_by("date", direction=firestore.Query.DESCENDING).limit(50)
            posts = posts_ref.stream()
            for post in posts:
                post_data = post.to_dict()
                post_data["id"] = post.id

                # Convert and format date
                if isinstance(post_data.get("date"), str):
                    try:
                        post_data["date"] = datetime.fromisoformat(post_data["date"])
                    except ValueError:
                        post_data["date"] = None  # If the date format is invalid, set it to None

                if post_data["date"]:
                    post_data["formatted_date"] = post_data["date"].strftime('%B %d, %Y, %I:%M %p')  # Format date

                comments_ref = db.collection("Post").document(post.id).collection("Comments").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(5)
                comments = comments_ref.stream()
                post_data["comments"] = [{"username": c.get("username"), "content": c.get("content")} for c in comments]
                posts_list.append(post_data)

        posts_list.sort(key=lambda x: x["date"], reverse=True)

        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": user_data,
            "recent_posts": posts_list
        })

    except Exception as e:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": None,
            "recent_posts": []
        })



@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/auth/init")
async def initialize_user_data(request: Request):
    user = verify_user(request)
    user_ref = db.collection("User").document(user["user_id"])
    user_doc = user_ref.get()

    if not user_doc.exists:
        user_ref.set({
            "id": user["user_id"],
            "email": user["email"],
            "username": user["username"],
            "followers": [],
            "following": [],
            "created_at": datetime.utcnow().isoformat()
        })
        return {"status": "User profile created"}
    return {"status": "User already exists"}

@app.get("/posts/create", response_class=HTMLResponse)
async def create_post_form(request: Request):
    return templates.TemplateResponse("create_post.html", {"request": request})

@app.post("/posts/create")
async def create_post(request: Request, caption: str = Form(...), image: UploadFile = File(...)):
    user = verify_user(request)
    user_id = user["user_id"]

    # Save the image to the server (ensure PNG/JPG format)
    if image.content_type not in ["image/png", "image/jpeg"]:
        raise HTTPException(status_code=400, detail="Invalid image format. Only PNG and JPG are allowed.")

    file_path = f"static/uploads/{user_id}_{datetime.utcnow().timestamp()}.{image.filename.split('.')[-1]}"
    with open(file_path, "wb") as buffer:
        buffer.write(await image.read())

    # Create a new post in the database
    post_id = f"{user_id}_{datetime.utcnow().timestamp()}"
    post_ref = db.collection("Post").document(post_id)
    post_ref.set({
        "id": post_id,
        "user_id": user_id,
        "username": user["username"],
        "date": datetime.utcnow().isoformat(),
        "image_url": file_path,  # Save the image URL
        "caption": caption
    })

    return {"status": "Post created", "post_id": post_id}

@app.get("/me")
async def get_user_profile(request: Request):
    user = verify_user(request)
    user_data = get_user_data(user["user_id"])
    return user_data

@app.post("/follow")
async def follow_user(request: Request, target_email: str = Form(...)):
    user = verify_user(request)
    user_id = user["user_id"]

    # Find the target user by email
    users = db.collection("User").where("email", "==", target_email).get()
    if not users:
        raise HTTPException(status_code=404, detail="Target user not found")

    target_doc = users[0]
    target_user_id = target_doc.id

    # Fetch user and target user data
    user_data = get_user_data(user_id)
    target_data = get_user_data(target_user_id)

    if target_user_id not in user_data["following"]:
        user_data["following"].append(target_user_id)
        target_data["followers"].append(user_id)

        db.collection("User").document(user_id).update({"following": user_data["following"]})
        db.collection("User").document(target_user_id).update({"followers": target_data["followers"]})

    return RedirectResponse(url="/", status_code=303)

@app.post("/unfollow")
async def unfollow_user(request: Request, target_email: str = Form(...)):
    user = verify_user(request)
    user_id = user["user_id"]

    # Find the target user by email
    users = db.collection("User").where("email", "==", target_email).get()
    if not users:
        raise HTTPException(status_code=404, detail="Target user not found")

    target_doc = users[0]
    target_user_id = target_doc.id

    # Fetch user and target user data
    user_data = get_user_data(user_id)
    target_data = get_user_data(target_user_id)

    if target_user_id in user_data["following"]:
        user_data["following"].remove(target_user_id)
    if user_id in target_data["followers"]:
        target_data["followers"].remove(user_id)

    db.collection("User").document(user_id).update({"following": user_data["following"]})
    db.collection("User").document(target_user_id).update({"followers": target_data["followers"]})

    return RedirectResponse(url="/", status_code=303)




@app.get("/search")
async def search_users(request: Request, query: str, current_user: Dict = Depends(get_current_user)):
    users_by_username = db.collection("User").where("username", "==", query).stream()
    users_by_email = db.collection("User").where("email", "==", query).stream()

    results = [user.to_dict() for user in users_by_username]
    results.extend([user.to_dict() for user in users_by_email])

    # Filter out self
    filtered_results = [user for user in results if user["id"] != current_user["user_id"]]

    # Add follow status
    for user in filtered_results:
        user["is_following"] = current_user["user_id"] in user.get("followers", [])

    return templates.TemplateResponse("search_results.html", {
        "request": request,
        "search_results": filtered_results,
        "query": query
    })



@app.get("/followers")
async def followers_page(request: Request):
    user = verify_user(request)
    user_id = user["user_id"]

    # Get user's followers list
    user_data = get_user_data(user_id)
    followers_ids = user_data["followers"]

    # Fetch the followers in reverse chronological order based on the time they followed
    followers_list = []
    for follower_id in followers_ids:
        follower_ref = db.collection("User").document(follower_id)
        follower_doc = follower_ref.get()
        if follower_doc.exists:
            followers_list.append(follower_doc.to_dict())

    return templates.TemplateResponse("followers.html", {"request": request, "user": user, "followers": followers_list})

@app.get("/following")
async def following_page(request: Request):
    user = verify_user(request)
    user_id = user["user_id"]

    # Get user's following list
    user_data = get_user_data(user_id)
    following_ids = user_data["following"]

    following_list = []
    for following_id in following_ids:
        following_ref = db.collection("User").document(following_id)
        following_doc = following_ref.get()
        if following_doc.exists:
            following_list.append(following_doc.to_dict())

    return templates.TemplateResponse("following.html", {"request": request, "user": user, "following": following_list})




@app.get("/profile")
async def profile_page(request: Request):
    user = verify_user(request)
    user_id = user["user_id"]

    profile_data = get_user_data(user_id)

    posts_ref = db.collection("Post").where("user_id", "==", user_id).order_by("date", direction=firestore.Query.DESCENDING)
    posts = posts_ref.stream()
    posts_list = []

    for post in posts:
        data = post.to_dict()
        data["id"] = post.id  # Add post ID for delete functionality
        posts_list.append(data)

    followers_count = len(profile_data["followers"])
    following_count = len(profile_data["following"])

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "profile": profile_data,
        "posts": posts_list,
        "followers_count": followers_count,
        "following_count": following_count
    })


@app.post("/posts/delete/{post_id}")
async def delete_post(post_id: str, request: Request):
    user = verify_user(request)
    user_id = user["user_id"]

    post_ref = db.collection("Post").document(post_id)
    post = post_ref.get()

    if post.exists:
        post_data = post.to_dict()
        if post_data.get("user_id") == user_id:
            post_ref.delete()
            return RedirectResponse(url="/profile?status=success&msg=Post+deleted+successfully", status_code=status.HTTP_302_FOUND)
        else:
            return RedirectResponse(url="/profile?status=error&msg=Unauthorized+to+delete+this+post", status_code=status.HTTP_302_FOUND)
    else:
        return RedirectResponse(url="/profile?status=error&msg=Post+not+found", status_code=status.HTTP_302_FOUND)


@app.get("/profile/{profile_id}")
async def view_profile(request: Request, profile_id: str, current_user: Dict = Depends(get_current_user)):
    # Fetch the profile data for the specified profile_id
    profile_ref = db.collection("User").document(profile_id)
    profile_doc = profile_ref.get()

    if not profile_doc.exists:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    profile_data = profile_doc.to_dict()
    profile_data["id"] = profile_id  # Add ID for follow/unfollow logic in template

    # Fetch posts by this user, ordered by most recent
    posts_ref = db.collection("Post").where("user_id", "==", profile_id).order_by("date", direction=firestore.Query.DESCENDING)
    posts = posts_ref.stream()

    posts_list = []
    for post in posts:
        post_data = post.to_dict()
        
        # Convert 'date' to datetime object if it's a string
        if isinstance(post_data.get("date"), str):
            try:
                post_data["date"] = datetime.fromisoformat(post_data["date"])  # Assuming the date is in ISO format
            except ValueError:
                post_data["date"] = None  # If the date format is invalid, set it to None
        
        # Format the date into a human-readable string
        if post_data["date"]:
            post_data["formatted_date"] = post_data["date"].strftime('%B %d, %Y, %I:%M %p')  # e.g. "January 1, 2025, 10:30 AM"
        
        # Ensure image_url starts with '/' for browser rendering
        if post_data.get("image_url") and not post_data["image_url"].startswith("/"):
            post_data["image_url"] = "/" + post_data["image_url"]
        
        post_data["id"] = post.id
        posts_list.append(post_data)

    # Followers and following counts
    followers = profile_data.get("followers", [])
    following = profile_data.get("following", [])
    followers_count = len(followers)
    following_count = len(following)

    # Check if current user follows this profile
    is_following = current_user["user_id"] in followers

    # Pass everything to the template
    return templates.TemplateResponse("view_profile.html", {
        "request": request,
        "current_user": current_user,
        "profile": profile_data,
        "posts": posts_list,
        "is_following": is_following,
        "followers_count": followers_count,
        "following_count": following_count
    })


@app.post("/follow_user/{profile_id}")
async def follow_user(request: Request, profile_id: str, current_user: Dict = Depends(get_current_user)):
    # Get current user's data
    user_data = get_user_data(current_user["user_id"])
    
    # Get the profile user's data
    profile_data = get_user_data(profile_id)

    # Check if the profile is already followed
    if profile_id not in user_data["following"]:
        # Add the profile to the current user's following list
        user_data["following"].append(profile_id)
        
        # Add the current user to the profile's followers list
        profile_data["followers"].append(current_user["user_id"])

        # Update Firestore with the new following/follower data
        db.collection("User").document(current_user["user_id"]).update({"following": user_data["following"]})
        db.collection("User").document(profile_id).update({"followers": profile_data["followers"]})

    # Redirect back to the same profile page
    return RedirectResponse(url=f"/profile/{profile_id}", status_code=303)


@app.post("/unfollow_user/{profile_id}")
async def unfollow_user(request: Request, profile_id: str, current_user: Dict = Depends(get_current_user)):
    # Get current user's data
    user_data = get_user_data(current_user["user_id"])
    
    # Get the profile user's data
    profile_data = get_user_data(profile_id)

    # Check if the profile is being followed
    if profile_id in user_data["following"]:
        # Remove the profile from the current user's following list
        user_data["following"].remove(profile_id)
        
        # Remove the current user from the profile's followers list
        profile_data["followers"].remove(current_user["user_id"])

        # Update Firestore with the new following/follower data
        db.collection("User").document(current_user["user_id"]).update({"following": user_data["following"]})
        db.collection("User").document(profile_id).update({"followers": profile_data["followers"]})

    # Redirect back to the same profile page
    return RedirectResponse(url=f"/profile/{profile_id}", status_code=303)



@app.get("/search_results")
async def search_results(request: Request, query: str, current_user: Dict = Depends(get_current_user)):
    # Search by username or email
    users_by_username = db.collection("User").where("username", "==", query).stream()
    users_by_email = db.collection("User").where("email", "==", query).stream()

    # Combine results
    results = []
    results.extend([user.to_dict() for user in users_by_username])
    results.extend([user.to_dict() for user in users_by_email])

    # Filter out the current user from the results
    filtered_results = [user for user in results if user["id"] != current_user["user_id"]]

    # Check if the current user is following these profiles
    for user in filtered_results:
        user["is_following"] = current_user["user_id"] in user["followers"]

    return templates.TemplateResponse("search_results.html", {
        "request": request,
        "search_results": filtered_results
    })


@app.post("/comment")
async def add_comment(request: Request, post_id: str, comment: str, current_user: Dict = Depends(get_current_user)):
    # Check if comment is less than 200 characters
    if len(comment) > 200:
        raise HTTPException(status_code=400, detail="Comment is too long. Maximum 200 characters.")
    
    # Add comment to Firestore
    post_ref = db.collection("Post").document(post_id)
    post_doc = post_ref.get()
    
    if not post_doc.exists:
        raise HTTPException(status_code=404, detail="Post not found")

    comment_data = {
        "username": current_user["username"],
        "content": comment,
        "timestamp": firestore.SERVER_TIMESTAMP
    }
    
    # Add the comment under the post
    db.collection("Post").document(post_id).collection("Comments").add(comment_data)

    return {"message": "Comment added successfully"}

@app.get("/comments/{post_id}")
async def get_comments(post_id: str, limit: int = 5):
    # Fetch comments for the post, ordered by timestamp
    comments_ref = db.collection("Post").document(post_id).collection("Comments").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit)
    comments = comments_ref.stream()

    comments_list = [{"username": comment.get("username"), "content": comment.get("content")} for comment in comments]
    
    return {"comments": comments_list}


# Route to handle adding a comment
@app.post("/posts/{post_id}/comment")
async def add_comment(
    request: Request,
    post_id: str,
    content: str = Form(...),
    current_user: Dict = Depends(get_current_user)
):
    # Validate comment
    content = content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Comment cannot be empty")
    if len(content) > 200:
        raise HTTPException(status_code=400, detail="Comment is too long. Maximum 200 characters allowed.")

    # Reference post
    post_ref = db.collection("Post").document(post_id)
    post_doc = post_ref.get()

    if not post_doc.exists:
        raise HTTPException(status_code=404, detail="Post not found")

    # Comment data
    comment_data = {
        "username": current_user["username"],
        "user_id": current_user["user_id"],
        "content": content,
        "timestamp": firestore.SERVER_TIMESTAMP
    }

    # Add comment to the subcollection 'Comments'
    db.collection("Post").document(post_id).collection("Comments").add(comment_data)

    # Redirect back to home or timeline
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)



@app.post("/add_comment/{post_id}")
async def add_comment(
    post_id: str,
    comment: str = Form(...),
    profile_id: str = Form(...), 
    current_user: Dict = Depends(get_current_user)
):
    post_ref = db.collection("Post").document(post_id)
    post_doc = post_ref.get()
    if not post_doc.exists:
        raise HTTPException(status_code=404, detail="Post not found")

    new_comment = {
        "username": current_user["username"],
        "text": comment,
        "date": datetime.utcnow().isoformat()
    }

    post_ref.update({
        "comments": firestore.ArrayUnion([new_comment])
    })

    return RedirectResponse(url=f"/profile/{profile_id}", status_code=status.HTTP_303_SEE_OTHER)
