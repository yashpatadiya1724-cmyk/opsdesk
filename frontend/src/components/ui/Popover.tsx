"use client";

import React, { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";

export interface PopoverProps {
  trigger: React.ReactNode;
  children: React.ReactNode;
  position?: "bottom-left" | "bottom-right" | "top-left" | "top-right";
  className?: string;
}

interface TriggerProps {
  ref?: React.Ref<HTMLElement>;
  onClick?: React.MouseEventHandler;
  "aria-haspopup"?: string;
  "aria-expanded"?: boolean;
}

export function Popover({
  trigger,
  children,
  position = "bottom-right",
  className,
}: PopoverProps) {
  const [isOpen, setIsOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const positionStyles = {
    "bottom-right": "top-full right-0 mt-2",
    "bottom-left": "top-full left-0 mt-2",
    "top-right": "bottom-full right-0 mb-2",
    "top-left": "bottom-full left-0 mb-2",
  };

  const handleToggle = () => {
    setIsOpen((prev) => !prev);
  };

  const renderedTrigger = React.isValidElement<TriggerProps>(trigger) ? (
    React.cloneElement(trigger, {
      ref: (node: HTMLElement | null) => {
        triggerRef.current = node;
        const origRef = (trigger as React.RefAttributes<HTMLElement>).ref;
        if (typeof origRef === "function") {
          origRef(node);
        } else if (origRef && typeof origRef === "object" && "current" in origRef) {
          (origRef as React.MutableRefObject<HTMLElement | null>).current = node;
        }
      },
      onClick: (e: React.MouseEvent) => {
        trigger.props.onClick?.(e);
        handleToggle();
      },
      "aria-haspopup": "dialog",
      "aria-expanded": isOpen,
    })
  ) : (
    <button
      ref={triggerRef as React.RefObject<HTMLButtonElement | null>}
      type="button"
      onClick={handleToggle}
      aria-haspopup="dialog"
      aria-expanded={isOpen}
      className="inline-block cursor-pointer bg-transparent border-0 p-0 text-inherit"
    >
      {trigger}
    </button>
  );

  return (
    <div className="relative inline-block">
      {renderedTrigger}
      {isOpen && (
        <div
          ref={popoverRef}
          role="dialog"
          aria-modal="false"
          className={cn(
            "absolute z-50 bg-surface border border-border rounded-card shadow-lg p-3 min-w-[200px] animate-in fade-in zoom-in-95 duration-120",
            positionStyles[position],
            className
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}
