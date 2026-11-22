"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface AvatarProps {
  name?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
  id?: string | null;
}

// Deterministic palette generation for avatars
const PALETTE = [
  { bg: "bg-teal-50", text: "text-teal-700", border: "border-teal-200" },
  { bg: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-200" },
  { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200" },
  { bg: "bg-purple-50", text: "text-purple-700", border: "border-purple-200" },
  { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200" },
  { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200" },
  { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200" },
  { bg: "bg-cyan-50", text: "text-cyan-700", border: "border-cyan-200" },
];

function getDeterministicColor(str?: string | null) {
  if (!str) return PALETTE[0];
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const index = Math.abs(hash) % PALETTE.length;
  return PALETTE[index];
}

function getInitials(name?: string | null): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function Avatar({ name, size = "md", className, id }: AvatarProps) {
  const safeName = name || id || "User";
  const color = getDeterministicColor(id || name || "");
  const initials = getInitials(name);

  const sizeStyles = {
    sm: "w-6 h-6 text-[10px]",
    md: "w-8 h-8 text-caption",
    lg: "w-10 h-10 text-body font-semibold",
  };

  return (
    <div
      title={safeName}
      aria-label={safeName}
      className={cn(
        "inline-flex items-center justify-center rounded-full font-medium border select-none shrink-0 transition-subtle",
        sizeStyles[size],
        color.bg,
        color.text,
        color.border,
        className
      )}
    >
      <span>{initials}</span>
    </div>
  );
}
