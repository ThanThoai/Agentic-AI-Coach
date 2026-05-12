"use client";

import type { SlashCommand } from "@/types/chat";
import { SLASH_COMMANDS } from "@/types/chat";

interface SlashCommandMenuProps {
  query: string;            // text after "/" to filter
  onSelect: (cmd: SlashCommand) => void;
}

const MODE_ICON: Record<string, string> = {
  question: "📚",
  analysis: "📊",
};

export function SlashCommandMenu({ query, onSelect }: SlashCommandMenuProps) {
  const filtered = SLASH_COMMANDS.filter((c) =>
    c.name.toLowerCase().includes(query.toLowerCase()),
  );

  if (filtered.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 rounded-xl border border-white/10 bg-gray-900 shadow-2xl overflow-hidden z-50">
      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-gray-600 border-b border-white/8">
        Commands
      </div>
      {filtered.map((cmd) => (
        <button
          key={cmd.name}
          onClick={() => onSelect(cmd)}
          className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-white/6 transition-colors group"
        >
          <span className="mt-0.5 text-base leading-none">{MODE_ICON[cmd.mode]}</span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-indigo-400 group-hover:text-indigo-300">
                {cmd.name}
              </span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">{cmd.description}</p>
          </div>
        </button>
      ))}
    </div>
  );
}
