"use client";

import React, { useState, useEffect } from "react";
import { cn, parseUtc } from "@/lib/utils";

export interface CountdownProps {
  targetDate: string | Date;
  className?: string;
  prefix?: string;
}

export function Countdown({ targetDate, className, prefix }: CountdownProps) {
  const [timeLeft, setTimeLeft] = useState<string>("");

  useEffect(() => {
    const calculateTime = () => {
      const target = parseUtc(targetDate)?.getTime() ?? Date.now();
      const now = Date.now();
      const diffMs = target - now;
      const isPast = diffMs < 0;
      const absDiff = Math.abs(diffMs);

      const hours = Math.floor(absDiff / (1000 * 60 * 60));
      const mins = Math.floor((absDiff % (1000 * 60 * 60)) / (1000 * 60));

      if (isPast) {
        setTimeLeft(`overdue ${hours > 0 ? `${hours}h ` : ""}${mins}m`);
      } else if (hours > 24) {
        const days = Math.floor(hours / 24);
        setTimeLeft(`${days}d ${hours % 24}h`);
      } else if (hours > 0) {
        setTimeLeft(`${hours}h ${mins}m`);
      } else {
        const secs = Math.floor((absDiff % (1000 * 60)) / 1000);
        setTimeLeft(`${mins}m ${secs}s`);
      }
    };

    calculateTime();
    const interval = setInterval(calculateTime, 10000); // 10s tick
    return () => clearInterval(interval);
  }, [targetDate]);

  return (
    <span className={cn("font-mono-numbers tracking-tight", className)}>
      {prefix && <span className="opacity-75 mr-1">{prefix}</span>}
      {timeLeft}
    </span>
  );
}
