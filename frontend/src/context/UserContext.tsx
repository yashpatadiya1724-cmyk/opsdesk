"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { DemoUser, DEMO_USERS } from "@/lib/types";

interface UserContextType {
  currentUser: DemoUser;
  setCurrentUser: (user: DemoUser) => void;
  isStaff: boolean;
  isLead: boolean;
  isEscalationManager: boolean;
  isRequester: boolean;
  token?: string | null;
  setToken?: (token: string | null) => void;
  logout?: () => void;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [currentUser, setCurrentUser] = useState<DemoUser>(DEMO_USERS[0]);
  const [token, setTokenState] = useState<string | null>(null);

  useEffect(() => {
    const saved = localStorage.getItem("opsdesk_user_id");
    if (saved) {
      const found = DEMO_USERS.find((u) => u.id === saved);
      if (found) setCurrentUser(found);
    }
    const savedToken = localStorage.getItem("opsdesk_token");
    if (savedToken) {
      setTokenState(savedToken);
    }

    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === "opsdesk_token") {
        setTokenState(e.newValue);
        if (!e.newValue && typeof window !== "undefined") {
          const authMode = process.env.NEXT_PUBLIC_AUTH_MODE || "jwt";
          if (authMode === "jwt" && window.location && window.location.pathname !== "/login") {
            window.location.href = "/login";
          }
        }
      }
      if (e.key === "opsdesk_user_id" && e.newValue) {
        const found = DEMO_USERS.find((u) => u.id === e.newValue);
        if (found) setCurrentUser(found);
      }
    };

    window.addEventListener("storage", handleStorageChange);
    return () => window.removeEventListener("storage", handleStorageChange);
  }, []);

  const handleSetUser = (user: DemoUser) => {
    setCurrentUser(user);
    localStorage.setItem("opsdesk_user_id", user.id);
  };

  const handleSetToken = (newToken: string | null) => {
    setTokenState(newToken);
    if (newToken) {
      localStorage.setItem("opsdesk_token", newToken);
    } else {
      localStorage.removeItem("opsdesk_token");
    }
  };

  const handleLogout = () => {
    handleSetToken(null);
  };

  const isStaff = currentUser.role !== "Requester";
  const isLead = currentUser.role === "Lead";
  const isEscalationManager = currentUser.role === "EscalationManager";
  const isRequester = currentUser.role === "Requester";

  return (
    <UserContext.Provider
      value={{
        currentUser,
        setCurrentUser: handleSetUser,
        isStaff,
        isLead,
        isEscalationManager,
        isRequester,
        token,
        setToken: handleSetToken,
        logout: handleLogout,
      }}
    >
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const context = useContext(UserContext);
  if (!context) {
    throw new Error("useUser must be used within a UserProvider");
  }
  return context;
}
