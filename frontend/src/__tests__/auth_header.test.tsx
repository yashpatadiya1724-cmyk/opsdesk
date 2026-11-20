import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, act } from "@testing-library/react";
import { fetchTickets, fetchTicketDetail } from "@/lib/api";
import { UserProvider, useUser } from "@/context/UserContext";

describe("Frontend Auth Integration: api.ts & UserContext", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("attaches Authorization Bearer token in JWT mode (when token present in localStorage)", async () => {
    localStorage.setItem("opsdesk_token", "test-mock-jwt-token-xyz");

    let capturedHeaders: Headers | undefined;
    global.fetch = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      capturedHeaders = new Headers(init?.headers);
      return {
        ok: true,
        json: async () => ({ tickets: [], total: 0, limit: 20, offset: 0, view: "triage" }),
      };
    });

    await fetchTickets("triage", 20, 0, "USR-101");

    expect(capturedHeaders).toBeDefined();
    expect(capturedHeaders?.get("Authorization")).toBe("Bearer test-mock-jwt-token-xyz");
    expect(capturedHeaders?.get("X-User-Id")).toBe("USR-101");
  });

  it("does NOT attach Authorization header in demo mode (when opsdesk_token is absent)", async () => {
    localStorage.removeItem("opsdesk_token");

    let capturedHeaders: Headers | undefined;
    global.fetch = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      capturedHeaders = new Headers(init?.headers);
      return {
        ok: true,
        json: async () => ({ id: "TCK-001", title: "Test Ticket" }),
      };
    });

    await fetchTicketDetail("TCK-001", "USR-102");

    expect(capturedHeaders).toBeDefined();
    expect(capturedHeaders?.get("Authorization")).toBeNull();
    expect(capturedHeaders?.get("X-User-Id")).toBe("USR-102");
  });

  it("UserContext manages token persistence, state updates, and logout", () => {
    function TestConsumer() {
      const { token, setToken, logout } = useUser();
      return (
        <div>
          <span data-testid="token-value">{token || "NO_TOKEN"}</span>
          <button data-testid="set-token-btn" onClick={() => setToken?.("jwt-session-abc")}>
            Set Token
          </button>
          <button data-testid="logout-btn" onClick={() => logout?.()}>
            Logout
          </button>
        </div>
      );
    }

    render(
      <UserProvider>
        <TestConsumer />
      </UserProvider>
    );

    // Initial state: no token
    expect(screen.getByTestId("token-value").textContent).toBe("NO_TOKEN");

    // Log in / set token
    act(() => {
      screen.getByTestId("set-token-btn").click();
    });
    expect(screen.getByTestId("token-value").textContent).toBe("jwt-session-abc");
    expect(localStorage.getItem("opsdesk_token")).toBe("jwt-session-abc");

    // Logout
    act(() => {
      screen.getByTestId("logout-btn").click();
    });
    expect(screen.getByTestId("token-value").textContent).toBe("NO_TOKEN");
    expect(localStorage.getItem("opsdesk_token")).toBeNull();
  });

  it("UserContext restores existing token from localStorage on mount", () => {
    localStorage.setItem("opsdesk_token", "restored-jwt-token-789");

    function TestConsumer() {
      const { token } = useUser();
      return <span data-testid="restored-token">{token || "NO_TOKEN"}</span>;
    }

    render(
      <UserProvider>
        <TestConsumer />
      </UserProvider>
    );

    expect(screen.getByTestId("restored-token").textContent).toBe("restored-jwt-token-789");
  });
});
