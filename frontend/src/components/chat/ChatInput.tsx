"use client";

import { useRef, useEffect, useState, type KeyboardEvent } from "react";
import { Spinner } from "@/components/ui/Spinner";
import { SlashCommandMenu } from "./SlashCommandMenu";
import { AtMentionMenu } from "./AtMentionMenu";
import type { AtMention } from "./AtMentionMenu";
import type { CommandMode, SlashCommand } from "@/types/chat";
import { SLASH_COMMANDS } from "@/types/chat";

interface Props {
  onSend: (text: string, mode: CommandMode) => void;
  disabled: boolean;
  value: string;
  onChange: (v: string) => void;
  activeMode: CommandMode;
  onModeChange: (mode: CommandMode) => void;
  isCoach?: boolean;
}

// ── Per-mode styling ────────────────────────────────────────────────────────

const MODE_CONFIG: Record<
  CommandMode,
  {
    badge: string;
    placeholder: string;
    focusBorder: string;
    sendBg: string;
    tabActiveClass: string;
  }
> = {
  question: {
    badge: "📚 /question",
    placeholder: "Ask a fitness question…",
    focusBorder: "focus-within:border-indigo-400",
    sendBg: "bg-indigo-600 hover:bg-indigo-500",
    tabActiveClass: "border-b-2 border-indigo-500 text-indigo-600 bg-indigo-50",
  },
  analysis: {
    badge: "📊 /analysis",
    placeholder: "What do you want to know about your training?",
    focusBorder: "focus-within:border-emerald-400",
    sendBg: "bg-emerald-600 hover:bg-emerald-500",
    tabActiveClass: "border-b-2 border-emerald-500 text-emerald-600 bg-emerald-50",
  },
  agent: {
    badge: "🤖 @AgentAssist",
    placeholder: 'Ask about your athletes… e.g. "Is Alex ready to increase weight?"',
    focusBorder: "focus-within:border-violet-400",
    sendBg: "bg-violet-600 hover:bg-violet-500",
    tabActiveClass: "border-b-2 border-violet-500 text-violet-600 bg-violet-50",
  },
};

const COACH_TABS: { mode: CommandMode; emoji: string; label: string }[] = [
  { mode: "question", emoji: "📚", label: "Knowledge" },
  { mode: "analysis", emoji: "📊", label: "Analyze" },
  { mode: "agent",   emoji: "🤖", label: "Agent Assist" },
];

// ── Helpers ─────────────────────────────────────────────────────────────────

function getAtQuery(value: string): string | null {
  const match = value.match(/@([^\s]*)$/);
  if (!match) return null;
  if (value.includes("@AgentAssist") && !value.match(/@([^\s]+)$/)?.at(0)?.startsWith("@AgentAssist")) {
    return null;
  }
  return match[1];
}

function stripAgentMention(text: string): string {
  return text.replace(/^@AgentAssist\s*/i, "").trim();
}

// ── Component ────────────────────────────────────────────────────────────────

export function ChatInput({
  onSend,
  disabled,
  value,
  onChange,
  activeMode,
  onModeChange,
  isCoach,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [showSlashMenu, setShowSlashMenu] = useState(false);
  const [slashQuery, setSlashQuery] = useState("");
  const [showAtMenu, setShowAtMenu] = useState(false);
  const [atQuery, setAtQuery] = useState("");

  // Auto-resize textarea
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  // Slash command detection
  useEffect(() => {
    if (value.startsWith("/") && !value.includes(" ")) {
      setShowSlashMenu(true);
      setSlashQuery(value.slice(1));
      setShowAtMenu(false);
    } else {
      setShowSlashMenu(false);
    }
  }, [value]);

  // @AgentAssist detection
  useEffect(() => {
    if (!isCoach) { setShowAtMenu(false); return; }
    const q = getAtQuery(value);
    if (q !== null && !value.includes("@AgentAssist")) {
      setShowAtMenu(true);
      setAtQuery(q);
      setShowSlashMenu(false);
    } else {
      setShowAtMenu(false);
      if (value.includes("@AgentAssist") && activeMode !== "agent") {
        onModeChange("agent");
      }
    }
  }, [value, isCoach, activeMode, onModeChange]);

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Escape") {
      setShowSlashMenu(false);
      setShowAtMenu(false);
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
    setShowSlashMenu(false);
    ref.current?.focus();
  }

  function handleAtSelect(mention: AtMention) {
    const replaced = value.replace(/@[^\s]*$/, `@${mention.id} `);
    onChange(replaced);
    onModeChange("agent");
    setShowAtMenu(false);
    ref.current?.focus();
  }

  function selectTab(mode: CommandMode) {
    onModeChange(mode);
    ref.current?.focus();
  }

  function submit() {
    const raw = value.trim();
    if (!raw || disabled) return;

    if (activeMode === "agent" || (isCoach && raw.includes("@AgentAssist"))) {
      onSend(stripAgentMention(raw), "agent");
      onChange("");
      return;
    }

    const matched = SLASH_COMMANDS.find((c) => raw.startsWith(c.name + " "));
    if (matched) {
      onModeChange(matched.mode);
      onSend(raw.slice(matched.name.length).trim(), matched.mode);
    } else {
      onSend(raw, activeMode);
    }
    onChange("");
  }

  const cfg = MODE_CONFIG[activeMode];

  return (
    <div className="relative">
      {showSlashMenu && <SlashCommandMenu query={slashQuery} onSelect={handleCommandSelect} />}
      {showAtMenu && <AtMentionMenu query={atQuery} onSelect={handleAtSelect} />}

      <div className={`flex flex-col border border-neutral-200 bg-white transition-colors overflow-hidden ${cfg.focusBorder}`}>

        {/* ── Coach: tab bar ─────────────────────────────────────────────── */}
        {isCoach ? (
          <div className="flex border-b border-neutral-100">
            {COACH_TABS.map((tab) => (
              <button
                key={tab.mode}
                onClick={() => selectTab(tab.mode)}
                disabled={disabled}
                className={`flex flex-1 items-center justify-center gap-1.5 px-2 py-2.5 text-xs font-medium transition-all border-b-2 ${
                  activeMode === tab.mode
                    ? cfg.tabActiveClass
                    : "border-transparent text-neutral-500 hover:text-neutral-700 hover:bg-neutral-50"
                } disabled:pointer-events-none`}
              >
                <span>{tab.emoji}</span>
                <span>{tab.label}</span>
              </button>
            ))}
          </div>
        ) : (
          /* ── Athlete: mode badge ───────────────────────────────────────── */
          <div className="flex items-center gap-2 px-4 pt-2.5 pb-0">
            <button
              onClick={() => { setShowSlashMenu((v) => !v); setShowAtMenu(false); }}
              className="flex items-center gap-1.5 border border-neutral-200 px-2 py-0.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50 transition-colors"
              title="Type / to change command"
            >
              {cfg.badge}
              <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" className="opacity-50">
                <path d="M1 3l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        )}

        {/* ── Agent hint ─────────────────────────────────────────────────── */}
        {isCoach && activeMode === "agent" && (
          <p className="px-4 pt-2 text-[11px] text-violet-500/70 leading-snug">
            Mention athlete names in your message — e.g. "Alex", "Binh", or "both athletes"
          </p>
        )}

        {/* ── Textarea + send ────────────────────────────────────────────── */}
        <div className="flex items-end gap-2 px-4 py-3">
          <textarea
            ref={ref}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKey}
            disabled={disabled}
            placeholder={cfg.placeholder}
            className="flex-1 resize-none bg-transparent text-sm text-neutral-900 placeholder:text-neutral-400 outline-none leading-relaxed disabled:opacity-50"
          />
          <button
            onClick={submit}
            disabled={disabled || !value.trim()}
            className={`flex h-8 w-8 shrink-0 items-center justify-center text-white transition-all ${cfg.sendBg} disabled:cursor-not-allowed disabled:opacity-40`}
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
