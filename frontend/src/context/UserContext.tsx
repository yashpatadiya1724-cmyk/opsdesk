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
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [currentUser, setCurrentUser] = useState<DemoUser>(DEMO_USERS[0]);

  useEffect(() => {
    const saved = localStorage.getItem("opsdesk_user_id");
    if (saved) {
      const found = DEMO_USERS.find((u) => u.id === saved);
      if (found) setCurrentUser(found);
    }
  }, []);

  const handleSetUser = (user: DemoUser) => {
    setCurrentUser(user);
    localStorage.setItem("opsdesk_user_id", user.id);
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
