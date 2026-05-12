"use client";

import type { SlashCommand } from "@/types/chat";
import { SLASH_COMMANDS } from "@/types/chat";

interface SlashCommandMenuProps {
  query: string;
  onSelect: (cmd: SlashCommand) => void;
  commands?: SlashCommand[];
}

const MODE_ICON: Record<string, string> = {
  question: "📚",
  analysis: "📊",
  agent: "🤖",
};

export function SlashCommandMenu({ query, onSelect, commands }: SlashCommandMenuProps) {
  const pool = commands ?? SLASH_COMMANDS;
  const filtered = pool.filter((c) =>
    c.name.toLowerCase().includes(query.toLowerCase()),
  );

  if (filtered.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 border border-neutral-200 bg-white shadow-lg overflow-hidden z-50">
      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-neutral-400 border-b border-neutral-100">
        Commands
      </div>
      {filtered.map((cmd) => (
        <button
          key={cmd.name}
          onClick={() => onSelect(cmd)}
          className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-neutral-50 transition-colors"
        >
          <span className="mt-0.5 text-base leading-none">{MODE_ICON[cmd.mode]}</span>
          <div className="min-w-0">
            <span className="text-sm font-medium text-indigo-600">{cmd.name}</span>
            <p className="text-xs text-neutral-500 mt-0.5">{cmd.description}</p>
          </div>
        </button>
      ))}
    </div>
  );
}
