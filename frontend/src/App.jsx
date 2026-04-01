import React, { useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import UploadPage from "./pages/UploadPage";
import VerifyPage from "./pages/VerifyPage";

export default function App() {
  const [loggedInUser, setLoggedInUser] = useState("");

  return (
    <Routes>
      <Route
        path="/"
        element={<LoginPage setLoggedInUser={setLoggedInUser} />}
      />
      <Route
        path="/upload"
        element={<UploadPage loggedInUser={loggedInUser} />}
      />
      <Route
        path="/verify/:sessionId"
        element={<VerifyPage loggedInUser={loggedInUser} />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}