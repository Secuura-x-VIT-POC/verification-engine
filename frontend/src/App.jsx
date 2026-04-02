import React, { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import UploadPage from "./pages/UploadPage";
import VerifyPage from "./pages/VerifyPage";
import { clearStoredAuth, loadStoredAuth, storeAuth } from "./lib/api";

function ProtectedRoute({ isAuthenticated, children }) {
  if (!isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return children;
}

export default function App() {
  const [auth, setAuth] = useState(() => loadStoredAuth());

  function handleAuth(nextAuth) {
    storeAuth(nextAuth);
    setAuth(nextAuth);
  }

  function handleLogout() {
    clearStoredAuth();
    setAuth(null);
  }

  return (
    <Routes>
      <Route
        path="/"
        element={
          auth?.token ? (
            <Navigate to="/upload" replace />
          ) : (
            <LoginPage onAuth={handleAuth} />
          )
        }
      />
      <Route
        path="/upload"
        element={
          <ProtectedRoute isAuthenticated={Boolean(auth?.token)}>
            <UploadPage auth={auth} onLogout={handleLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/verify/:sessionId"
        element={
          <ProtectedRoute isAuthenticated={Boolean(auth?.token)}>
            <VerifyPage auth={auth} onLogout={handleLogout} />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to={auth?.token ? "/upload" : "/"} replace />} />
    </Routes>
  );
}
