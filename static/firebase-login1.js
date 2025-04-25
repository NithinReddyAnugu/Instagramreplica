// -------------------- Firebase Imports --------------------
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  onAuthStateChanged,
  signOut,
  getIdToken
} from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";

import {
  getFirestore,
  doc,
  setDoc
} from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";

// -------------------- Firebase Config --------------------
const firebaseConfig = {
  apiKey: "AIzaSyAEkAhvqVDuJzZGR8W5kWqpOdsAG-6vzeU",
  authDomain: "instagram-replica-ac218.firebaseapp.com",
  projectId: "instagram-replica-ac218",
  storageBucket: "instagram-replica-ac218.appspot.com",
  messagingSenderId: "871840298011",
  appId: "1:871840298011:web:6f904a95902be4f09374be"
};

// -------------------- Firebase Init --------------------
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

// -------------------- Helper: Set Cookie --------------------
const setTokenCookie = async (user) => {
  const idToken = await getIdToken(user, true);
  document.cookie = `token=${idToken}; path=/`;
};

// -------------------- DOM Elements --------------------
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const loginBtn = document.getElementById("login");
const signUpBtn = document.getElementById("sign-up");
const signOutBtn = document.getElementById("sign-out");

// -------------------- Sign Up --------------------
if (signUpBtn) {
  signUpBtn.addEventListener("click", async () => {
    const email = emailInput.value.trim();
    const password = passwordInput.value.trim();
    const roleInput = document.querySelector('input[name="role"]:checked');
    const role = roleInput ? roleInput.value : "user";

    try {
      const userCredential = await createUserWithEmailAndPassword(auth, email, password);
      const user = userCredential.user;

      // Create User document in Firestore
      await setDoc(doc(db, "User", user.uid), {
        id: user.uid,
        email: user.email,
        role: role,
        following: [],
        followers: [],
        created_at: new Date().toISOString()
      });

      await setTokenCookie(user);
      window.location.href = "/login"; // redirect after sign-up
    } catch (error) {
      console.error("Signup error:", error.message);
      alert("Signup failed: " + error.message);
    }
  });
}

// -------------------- Login --------------------
if (loginBtn) {
  loginBtn.addEventListener("click", async () => {
    const email = emailInput.value.trim();
    const password = passwordInput.value.trim();

    try {
      const userCredential = await signInWithEmailAndPassword(auth, email, password);
      await setTokenCookie(userCredential.user);

      window.location.href = "/"; // home page
    } catch (error) {
      console.error("Login error:", error.message);
      alert("Login failed: " + error.message);
    }
  });
}

// -------------------- Logout --------------------
if (signOutBtn) {
  signOutBtn.addEventListener("click", async () => {
    try {
      await signOut(auth);
      document.cookie = "token=; Max-Age=0; path=/";
      window.location.href = "/login";
    } catch (error) {
      console.error("Sign out error:", error.message);
    }
  });
}

// -------------------- Auth State Listener --------------------
onAuthStateChanged(auth, async (user) => {
  if (user) {
    await setTokenCookie(user);

    try {
      const idToken = await getIdToken(user, true);
      await fetch("/auth/init", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${idToken}`  // Pass the ID token in Authorization header
        },
        credentials: "same-origin"
      });
    } catch (err) {
      console.error("User init failed:", err);
    }
  }
});

