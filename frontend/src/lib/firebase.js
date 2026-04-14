import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const firebaseConfig =
  typeof __firebase_config !== "undefined"
    ? JSON.parse(__firebase_config)
    : {
        apiKey: "AIza...",
        authDomain: "tu-app.firebaseapp.com",
        projectId: "tu-app",
      };

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
