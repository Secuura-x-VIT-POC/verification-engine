import React, { startTransition, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiRequest } from "../lib/api";

export default function LoginPage({ onAuth }) {
  const navigate = useNavigate();
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();

    if (!username.trim() || !password.trim()) {
      setError("Please enter both username and password.");
      return;
    }

    setError("");
    setIsSubmitting(true);

    try {
      if (mode === "register") {
        await apiRequest("/register", {
          method: "POST",
          body: {
            username: username.trim(),
            password,
          },
        });
      }

      const loginResponse = await apiRequest("/login", {
        method: "POST",
        body: {
          username: username.trim(),
          password,
        },
      });

      onAuth({
        token: loginResponse.access_token,
        username: username.trim(),
      });
      startTransition(() => navigate("/upload"));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="page auth-page">
      <div className="card login-card">
        <p className="eyebrow">Secure transient verification</p>
        <h1>Secuura x VIT POC</h1>
        <p className="muted">
          Sign in to create a review session, upload a PDF, and trigger trust scoring when the
          verification view opens.
        </p>

        <div className="mode-switch" role="tablist" aria-label="Authentication mode">
          <button
            type="button"
            className={mode === "login" ? "secondary-btn active" : "secondary-btn"}
            onClick={() => setMode("login")}
          >
            Login
          </button>
          <button
            type="button"
            className={mode === "register" ? "secondary-btn active" : "secondary-btn"}
            onClick={() => setMode("register")}
          >
            Register
          </button>
        </div>

        <form className="form" onSubmit={handleSubmit}>
          <label htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="Enter username"
            autoComplete="username"
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Enter password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />

          {error ? <p className="error-text">{error}</p> : null}

          <button type="submit" className="primary-btn" disabled={isSubmitting}>
            {isSubmitting ? "Working..." : mode === "login" ? "Login" : "Register and Login"}
          </button>
        </form>
      </div>
    </div>
  );
}
