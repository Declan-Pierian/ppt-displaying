import { useState, useCallback } from "react";
import api from "../lib/api";

interface User {
  username: string;
  role: string;
}

export function useAuth() {
  const [user, setUser] = useState<User | null>(() => {
    const stored = localStorage.getItem("user");
    return stored ? JSON.parse(stored) : null;
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const login = useCallback(async (username: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.post("/auth/login", { username, password });
      const { access_token, username: uname, role } = res.data;
      localStorage.setItem("token", access_token);
      const userData = { username: uname, role };
      localStorage.setItem("user", JSON.stringify(userData));
      setUser(userData);
      return true;
    } catch (err: any) {
      setError(err.response?.data?.detail || "Login failed");
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    setUser(null);
  }, []);

  const isAuthenticated = !!user && !!localStorage.getItem("token");

  return { user, login, logout, loading, error, isAuthenticated };
}
