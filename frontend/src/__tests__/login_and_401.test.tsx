import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, act, fireEvent, waitFor } from "@testing-library/react";
import { fetchTickets, loginUser } from "@/lib/api";
import { UserProvider, useUser } from "@/context/UserContext";
import LoginPage from "@/app/login/page";

// Mock next/navigation
const mockPush = vi.fn();
const mockGet = vi.fn().mockReturnValue(null);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => ({ get: mockGet }),
}));

describe("Frontend Auth: 401 handling, login flow, and multi-tab sync", () => {
  const originalFetch = global.fetch;
  const originalLocation = window.location;

  beforeEach(() => {
    localStorage.clear();
    mockPush.mockClear();
    mockGet.mockClear();
    // Setup window.location mock
    Object.defineProperty(window, "location", {
      value: {
        pathname: "/tickets",
        search: "?view=triage",
        href: "http://localhost:3000/tickets?view=triage",
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    window.location = originalLocation;
    vi.restoreAllMocks();
  });

  it("on 401 response, clears opsdesk_token and redirects to /login with from query param", async () => {
    localStorage.setItem("opsdesk_token", "expired-or-revoked-token");

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Token expired or invalid" }),
    });

    await expect(fetchTickets("triage")).rejects.toThrow("Token expired or invalid");

    // Token must be wiped
    expect(localStorage.getItem("opsdesk_token")).toBeNull();
    // Redirect must be initiated
    expect(window.location.href).toBe("/login?from=%2Ftickets%3Fview%3Dtriage");
  });

  it("loginUser sends POST /api/auth/login and persists access_token in localStorage", async () => {
    let capturedBody: { email?: string; password?: string } | null = null;
    let capturedUrl = "";

    global.fetch = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      capturedUrl = url;
      capturedBody = JSON.parse(init?.body as string);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          access_token: "new-valid-jwt-token-456",
          token_type: "bearer",
          user: { id: "USR-101", name: "Ananya Sharma", role: "Agent", email: "ananya@opsdesk.internal" },
        }),
      };
    });

    const result = await loginUser("ananya@opsdesk.internal", "SecurePassword123!");

    expect(capturedUrl).toContain("/api/auth/login");
    expect(capturedBody).toEqual({ email: "ananya@opsdesk.internal", password: "SecurePassword123!" });
    expect(result.access_token).toBe("new-valid-jwt-token-456");
    expect(localStorage.getItem("opsdesk_token")).toBe("new-valid-jwt-token-456");
    expect(localStorage.getItem("opsdesk_user_id")).toBe("USR-101");
  });

  it("listens to window storage event so logging out in one tab updates token and redirects other tabs", () => {
    function TestConsumer() {
      const { token } = useUser();
      return <div data-testid="active-token">{token || "NO_TOKEN"}</div>;
    }

    localStorage.setItem("opsdesk_token", "active-session-token");

    render(
      <UserProvider>
        <TestConsumer />
      </UserProvider>
    );

    expect(screen.getByTestId("active-token").textContent).toBe("active-session-token");

    // Simulate storage event from another tab clearing opsdesk_token
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "opsdesk_token",
          oldValue: "active-session-token",
          newValue: null,
        })
      );
    });

    expect(screen.getByTestId("active-token").textContent).toBe("NO_TOKEN");
    expect(window.location.href).toBe("/login");
  });

  it("LoginPage renders form, handles submission, sets token, and redirects back", async () => {
    mockGet.mockReturnValue("/insights");

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        access_token: "jwt-token-login-page-test",
        token_type: "bearer",
        user: { id: "USR-101", name: "Ananya Sharma", role: "Agent", email: "ananya@opsdesk.internal" },
      }),
    });

    render(
      <UserProvider>
        <LoginPage />
      </UserProvider>
    );

    fireEvent.change(screen.getByLabelText(/Email Address/i), { target: { value: "ananya@opsdesk.internal" } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "password123" } });

    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/insights");
    });
    expect(localStorage.getItem("opsdesk_token")).toBe("jwt-token-login-page-test");
  });
});
