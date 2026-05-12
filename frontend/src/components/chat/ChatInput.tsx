"use client";

import { useRef, useEffect, type KeyboardEvent } from "react";
import { Spinner } from "@/components/ui/Spinner";

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
  value: string;
  onChange: (v: string) => void;
}

export function ChatInput({ onSend, disabled, value, onChange }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    onChange("");
  }

  return (
    <div className="flex items-end gap-2 rounded-2xl border border-white/15 bg-white/8 px-4 py-3 focus-within:border-indigo-500/60 transition-colors">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKey}
        disabled={disabled}
        placeholder="Ask a fitness question…"
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
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
          >
            <path d="M5 12h14M12 5l7 7-7 7" />
          </svg>
        )}
      </button>
    </div>
  );
}
