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
    containerBorder: string;
    sendBg: string;
    tabActiveClass: string;
  }
> = {
  question: {
    badge: "📚 /question",
    placeholder: "Ask a fitness question…",
    containerBorder: "border-white/15 focus-within:border-indigo-500/60",
    sendBg: "bg-indigo-600 hover:bg-indigo-500",
    tabActiveClass: "border-b-2 border-indigo-400 text-indigo-300 bg-indigo-500/10",
  },
  analysis: {
    badge: "📊 /analysis",
    placeholder: "What do you want to know about your training?",
    containerBorder: "border-emerald-500/25 focus-within:border-emerald-500/55",
    sendBg: "bg-emerald-600 hover:bg-emerald-500",
    tabActiveClass: "border-b-2 border-emerald-400 text-emerald-300 bg-emerald-500/10",
  },
  agent: {
    badge: "🤖 @AgentAssist",
    placeholder: 'Ask about your athletes… e.g. "Is Alex ready to increase weight?"',
    containerBorder: "border-purple-500/35 focus-within:border-purple-500/65",
    sendBg: "bg-purple-600 hover:bg-purple-500",
    tabActiveClass: "border-b-2 border-purple-400 text-purple-300 bg-purple-500/10",
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

  // Slash command detection (power-user shortcut, works for all roles)
  useEffect(() => {
    if (value.startsWith("/") && !value.includes(" ")) {
      setShowSlashMenu(true);
      setSlashQuery(value.slice(1));
      setShowAtMenu(false);
    } else {
      setShowSlashMenu(false);
    }
  }, [value]);

  // @AgentAssist detection — auto-switch coach to agent tab
  useEffect(() => {
    if (!isCoach) { setShowAtMenu(false); return; }
    const q = getAtQuery(value);
    if (q !== null && !value.includes("@AgentAssist")) {
      setShowAtMenu(true);
      setAtQuery(q);
      setShowSlashMenu(false);
    } else {
      setShowAtMenu(false);
      // Auto-switch to agent tab when @AgentAssist is present
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

    // Coach in agent mode — strip @AgentAssist mention if present
    if (activeMode === "agent" || (isCoach && raw.includes("@AgentAssist"))) {
      onSend(stripAgentMention(raw), "agent");
      onChange("");
      return;
    }

    // Slash command typed inline (power-user shortcut)
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

      <div
        className={`flex flex-col rounded-2xl border transition-colors overflow-hidden bg-white/[0.06] ${cfg.containerBorder}`}
      >
        {/* ── Coach: tab bar ─────────────────────────────────────────────── */}
        {isCoach ? (
          <div className="flex border-b border-white/8">
            {COACH_TABS.map((tab) => (
              <button
                key={tab.mode}
                onClick={() => selectTab(tab.mode)}
                disabled={disabled}
                className={`flex flex-1 items-center justify-center gap-1.5 px-2 py-2.5 text-xs font-medium transition-all border-b-2 ${
                  activeMode === tab.mode
                    ? cfg.tabActiveClass
                    : "border-transparent text-gray-500 hover:text-gray-300 hover:bg-white/5"
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
              className="flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium text-indigo-400 bg-white/8 hover:bg-white/12 transition-colors"
              title="Type / to change command"
            >
              {cfg.badge}
              <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" className="opacity-60">
                <path d="M1 3l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        )}

        {/* ── Agent hint ─────────────────────────────────────────────────── */}
        {isCoach && activeMode === "agent" && (
          <p className="px-4 pt-2 text-[11px] text-purple-400/60 leading-snug">
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
            className="flex-1 resize-none bg-transparent text-sm text-gray-100 placeholder:text-gray-500 outline-none leading-relaxed disabled:opacity-50"
          />
          <button
            onClick={submit}
            disabled={disabled || !value.trim()}
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-white transition-all ${cfg.sendBg} disabled:cursor-not-allowed disabled:opacity-40`}
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
