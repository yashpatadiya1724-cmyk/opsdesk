"use client";

import React, { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { loginUser } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import { DEMO_USERS, DemoUser } from "@/lib/types";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const from = searchParams.get("from") || "/";
  const { setToken, setCurrentUser } = useUser();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const data = await loginUser(email, password);
      if (setToken) {
        setToken(data.access_token);
      }
      if (data.user && setCurrentUser) {
        const matched = DEMO_USERS.find((u) => u.id === data.user?.id);
        if (matched) {
          setCurrentUser(matched);
        } else {
          setCurrentUser({
            id: data.user.id,
            name: data.user.name,
            role: (data.user.role as DemoUser["role"]) || "Agent",
            agencyId: null,
            region: null,
            description: `${data.user.role} (${data.user.name})`,
          });
        }
      }
      router.push(from);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Login failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 px-4">
      <div className="max-w-md w-full bg-slate-800 rounded-xl shadow-lg border border-slate-700 p-8">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-white tracking-tight">OpsDesk Login</h1>
          <p className="text-sm text-slate-400 mt-1">Sign in with your operational credentials</p>
        </div>

        {error && (
          <div
            data-testid="login-error"
            className="mb-4 p-3 bg-red-900/50 border border-red-700 text-red-200 text-sm rounded-lg"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1" htmlFor="email">
              Email Address
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="agent@opsdesk.internal"
              className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              placeholder="••••••••"
              className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-medium rounded-lg transition-colors shadow-sm"
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-900" />}>
      <LoginForm />
    </Suspense>
  );
}
