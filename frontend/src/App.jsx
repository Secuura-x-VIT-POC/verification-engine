import React, { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { GeneralizedVerifyPage } from "./features/generalized-verification";
import LoginPage from "./pages/LoginPage";
import UploadPage from "./pages/UploadPage";
import VerifyPage from "./pages/VerifyPage";
import { clearStoredAuth, loadStoredAuth, storeAuth } from "./lib/api";
import { APP_ROUTE_PATHS } from "./routes/paths";

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
        path={APP_ROUTE_PATHS.upload}
        element={
          <ProtectedRoute isAuthenticated={Boolean(auth?.token)}>
            <UploadPage auth={auth} onLogout={handleLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path={APP_ROUTE_PATHS.legacyVerify}
        element={
          <ProtectedRoute isAuthenticated={Boolean(auth?.token)}>
            <VerifyPage auth={auth} onLogout={handleLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path={APP_ROUTE_PATHS.generalizedVerify}
        element={
          <ProtectedRoute isAuthenticated={Boolean(auth?.token)}>
            <GeneralizedVerifyPage auth={auth} onLogout={handleLogout} />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to={auth?.token ? "/upload" : "/"} replace />} />
    </Routes>
  );
}
