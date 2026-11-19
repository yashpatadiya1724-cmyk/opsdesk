"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Plane, ChevronRight } from "lucide-react";
import { TicketSummary } from "@/lib/types";
import { SplitFlap } from "@/components/ui";
import { cn, parseUtc } from "@/lib/utils";

export interface DepartureBoardStripProps {
  tickets: TicketSummary[];
  onSelectTicket?: (ticketId: string) => void;
  className?: string;
}

export function DepartureBoardStrip({
  tickets,
  onSelectTicket,
  className,
}: DepartureBoardStripProps) {
  const router = useRouter();
  const [now, setNow] = useState<number>(Date.now());
  const [flipKeys, setFlipKeys] = useState<Record<string, number>>({});

  // 1-second live countdown ticker
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const handleRowMouseEnter = (ticketId: string) => {
    setFlipKeys((prev) => ({
      ...prev,
      [ticketId]: (prev[ticketId] || 0) + 1,
    }));
  };

  // Compute 5 most urgent check-ins from loaded tickets
  const urgentTickets = useMemo(() => {
    if (!tickets || tickets.length === 0) return [];

    // Filter tickets that are not closed/resolved
    const active = tickets.filter(
      (t) => t.status !== "Closed" && t.status !== "Resolved"
    );

    // Sort by check_in_date ascending (earliest check-in first)
    return [...active]
      .sort((a, b) => {
        const timeA = parseUtc(a.check_in_date)?.getTime() ?? 0;
        const timeB = parseUtc(b.check_in_date)?.getTime() ?? 0;
        return timeA - timeB;
      })
      .slice(0, 5);
  }, [tickets]);

  if (urgentTickets.length === 0) {
    return null;
  }

  // Format countdown string: "03:42:10" or "1d 04:12:05"
  const formatCountdown = (checkInIso: string) => {
    const checkInTime = parseUtc(checkInIso)?.getTime() ?? 0;
    const diffMs = checkInTime - now;

    if (diffMs <= 0) {
      return "00:00:00";
    }

    const totalSecs = Math.floor(diffMs / 1000);
    const hours = Math.floor(totalSecs / 3600);
    const mins = Math.floor((totalSecs % 3600) / 60);
    const secs = totalSecs % 60;

    const pad = (n: number) => n.toString().padStart(2, "0");

    if (hours >= 24) {
      const days = Math.floor(hours / 24);
      const remHours = hours % 24;
      return `${days}d ${pad(remHours)}:${pad(mins)}:${pad(secs)}`;
    }

    return `${pad(hours)}:${pad(mins)}:${pad(secs)}`;
  };

  const handleClick = (ticketId: string) => {
    if (onSelectTicket) {
      onSelectTicket(ticketId);
    } else {
      router.push(`/ticket/${ticketId}`);
    }
  };

  return (
    <div
      className={cn(
        "bg-[#07151D] border border-[#16384C] rounded-[24px] p-4 text-[#A8C7DC] shadow-md font-mono-numbers flex flex-col gap-3 select-none",
        className
      )}
      aria-label="Dispatch Departure Board"
    >
      {/* Board Header */}
      <div className="flex items-center justify-between border-b border-[#16384C] pb-2 text-[11px] uppercase tracking-wider text-[#63879F]">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-departure-amber animate-pulse shrink-0" />
          <span className="font-semibold text-departure-amber tracking-wide flex items-center gap-1.5">
            <Plane className="w-3.5 h-3.5 rotate-45 text-departure-amber" />
            DISPATCH DEPARTURE BOARD
          </span>
          <span className="hidden sm:inline-block text-[#3B647E]">|</span>
          <span className="hidden sm:inline-block text-[10px] text-[#63879F]">
            TOP 5 URGENT CHECK-INS
          </span>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-[#4E7792]">
          <span>OPS MISSION CONTROL</span>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping shrink-0" />
        </div>
      </div>

      {/* Rows */}
      <div className="flex flex-col gap-1.5 divide-y divide-[#102B3C]/60">
        {urgentTickets.map((t) => {
          const countdownStr = formatCountdown(t.check_in_date);
          const flipKey = flipKeys[t.id] || 0;

          // SLA Light styling
          const isBreached = t.sla.status === "BREACHED";
          const isAtRisk = t.sla.status === "AT_RISK";
          const isNormal = t.sla.status === "NORMAL";

          let lightColor = "bg-slate-400";
          let glowColor = "group-hover:shadow-[0_0_10px_rgba(148,163,184,0.9)]";
          if (isBreached) {
            lightColor = "bg-rose-500 animate-pulse";
            glowColor = "group-hover:shadow-[0_0_14px_rgba(244,63,94,1)]";
          } else if (isAtRisk) {
            lightColor = "bg-amber-400";
            glowColor = "group-hover:shadow-[0_0_14px_rgba(251,191,36,1)]";
          } else if (isNormal) {
            lightColor = "bg-emerald-400";
            glowColor = "group-hover:shadow-[0_0_14px_rgba(52,211,153,1)]";
          }

          return (
            <div
              key={t.id}
              onClick={() => handleClick(t.id)}
              onMouseEnter={() => handleRowMouseEnter(t.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleClick(t.id);
                }
              }}
              tabIndex={0}
              role="button"
              aria-label={`Open case ${t.id} - Check in in ${countdownStr}`}
              className="pt-2 first:pt-0 flex items-center justify-between text-[12px] gap-2 flex-wrap sm:flex-nowrap group hover:bg-[#0C2433] p-1.5 rounded-lg transition-colors cursor-pointer focus:outline-none focus:bg-[#0C2433]"
            >
              {/* Left: SLA Light + ID + Agency + Title */}
              <div className="flex items-center gap-2.5 min-w-0">
                {/* Status light that brightens on hover */}
                <div
                  className={cn(
                    "w-2.5 h-2.5 rounded-full shrink-0 transition-all duration-150 shadow-xs",
                    lightColor,
                    glowColor,
                    "group-hover:scale-125 group-hover:brightness-150"
                  )}
                  title={`SLA: ${t.sla.status}`}
                />

                {/* ID in mono */}
                <span className="font-bold text-white tracking-wider shrink-0 group-hover:text-departure-amber transition-colors">
                  {t.id}
                </span>

                {/* Agency Pill */}
                <span className="px-1.5 py-0.5 rounded bg-[#0B212E] text-[#86A8BF] border border-[#16384C] text-[11px] font-medium shrink-0">
                  {t.agency_id}
                </span>

                {/* Title */}
                <span className="text-[#86A8BF] group-hover:text-[#D1E5F2] text-[11px] truncate max-w-[200px] sm:max-w-[320px]">
                  {t.title}
                </span>
              </div>

              {/* Right: Check-in countdown in amber split-flap style */}
              <div className="flex items-center gap-3 shrink-0 ml-auto">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] uppercase text-[#63879F] tracking-wider hidden sm:inline">
                    CHECK-IN:
                  </span>
                  <div className="flex items-center gap-0.5 bg-[#051118] px-2 py-1 rounded border border-[#143245]">
                    {countdownStr.split("").map((ch, idx) => {
                      if (ch === ":" || ch === " " || ch === "d") {
                        return (
                          <span
                            key={`${idx}-${flipKey}`}
                            className="text-departure-amber font-bold text-[12px] px-0.5"
                          >
                            {ch}
                          </span>
                        );
                      }
                      return (
                        <SplitFlap
                          key={`${idx}-${flipKey}`}
                          char={ch}
                          size="sm"
                          amber={true}
                          className="h-5 w-3.5 text-[10px]"
                        />
                      );
                    })}
                  </div>
                </div>

                {/* SLA Status Pill */}
                <span
                  className={cn(
                    "px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border",
                    isBreached
                      ? "bg-rose-950/60 text-rose-300 border-rose-800"
                      : isAtRisk
                      ? "bg-amber-950/60 text-amber-300 border-amber-800"
                      : "bg-[#0B212E] text-departure-amber border-[#1D445C]"
                  )}
                >
                  {t.sla.status}
                </span>

                <ChevronRight className="w-3.5 h-3.5 text-[#3B647E] group-hover:text-departure-amber group-hover:translate-x-0.5 transition-all" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
