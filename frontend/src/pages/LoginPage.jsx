import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

export default function LoginPage({ setLoggedInUser }) {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(e) {
    e.preventDefault();

    if (!username.trim() || !password.trim()) {
      alert("Please enter both username and password.");
      return;
    }

    setLoggedInUser(username);
    navigate("/upload");
  }

  return (
    <div className="page">
      <div className="card login-card">
        <h1>Secuura × VIT POC</h1>
        <p className="muted">Login to continue</p>

        <form className="form" onSubmit={handleSubmit}>
          <label htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Enter username"
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter password"
          />

          <button type="submit" className="primary-btn">
            Login
          </button>
        </form>
      </div>
    </div>
  );
}