"use client";

import { useRef, useEffect, useState, type KeyboardEvent } from "react";
import { Spinner } from "@/components/ui/Spinner";
import { SlashCommandMenu } from "./SlashCommandMenu";
import type { CommandMode, SlashCommand } from "@/types/chat";
import { SLASH_COMMANDS } from "@/types/chat";

interface Props {
  onSend: (text: string, mode: CommandMode) => void;
  disabled: boolean;
  value: string;
  onChange: (v: string) => void;
  activeMode: CommandMode;
  onModeChange: (mode: CommandMode) => void;
}

const MODE_CONFIG: Record<CommandMode, { badge: string; color: string; placeholder: string }> = {
  question: {
    badge: "📚 /question",
    color: "text-indigo-400",
    placeholder: "Ask a fitness question…",
  },
  analysis: {
    badge: "📊 /analysis",
    color: "text-emerald-400",
    placeholder: "What do you want to know about your training?",
  },
};

export function ChatInput({ onSend, disabled, value, onChange, activeMode, onModeChange }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [showMenu, setShowMenu] = useState(false);
  const [menuQuery, setMenuQuery] = useState("");

  // Auto-resize
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  // Detect slash-command typing
  useEffect(() => {
    if (value.startsWith("/") && !value.includes(" ")) {
      setShowMenu(true);
      setMenuQuery(value.slice(1));
    } else {
      setShowMenu(false);
    }
  }, [value]);

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Escape") {
      setShowMenu(false);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function handleCommandSelect(cmd: SlashCommand) {
    onModeChange(cmd.mode);
    onChange("");
    setShowMenu(false);
    ref.current?.focus();
  }

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    // Strip leading slash command prefix if user typed it inline
    const matched = SLASH_COMMANDS.find((c) => text.startsWith(c.name + " "));
    if (matched) {
      onModeChange(matched.mode);
      onSend(text.slice(matched.name.length).trim(), matched.mode);
    } else {
      onSend(text, activeMode);
    }
    onChange("");
  }

  const cfg = MODE_CONFIG[activeMode];

  return (
    <div className="relative">
      {showMenu && (
        <SlashCommandMenu query={menuQuery} onSelect={handleCommandSelect} />
      )}

      <div className="flex flex-col rounded-2xl border border-white/15 bg-white/[0.06] focus-within:border-indigo-500/60 transition-colors overflow-hidden">
        {/* Mode badge */}
        <div className="flex items-center gap-2 px-4 pt-2.5 pb-0">
          <button
            onClick={() => setShowMenu((v) => !v)}
            className={`flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ${cfg.color} bg-white/8 hover:bg-white/12 transition-colors`}
            title="Type / to change command"
          >
            {cfg.badge}
            <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" className="opacity-60">
              <path d="M1 3l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
            </svg>
          </button>
        </div>

        {/* Input row */}
        <div className="flex items-end gap-2 px-4 py-2.5">
          <textarea
            ref={ref}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKey}
            disabled={disabled}
            placeholder={cfg.placeholder}
            className="flex-1 resize-none bg-transparent text-sm text-gray-100 placeholder:text-gray-500 outline-none leading-relaxed disabled:opacity-50"
          />
          <button
            onClick={submit}
            disabled={disabled || !value.trim()}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white transition-all hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Send"
          >
            {disabled ? (
              <Spinner size={14} />
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
