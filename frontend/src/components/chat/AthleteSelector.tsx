"use client";

import type { DemoUser } from "@/types/chat";

const ATHLETE_META: Record<string, { emoji: string; color: string; ring: string }> = {
  alex: { emoji: "💪", color: "text-indigo-300", ring: "ring-indigo-400" },
  binh: { emoji: "🏃", color: "text-emerald-300", ring: "ring-emerald-400" },
};

interface Props {
  athletes: DemoUser[];
  activeKey: string;
  onSelect: (athlete: DemoUser) => void;
  disabled?: boolean;
}

export function AthleteSelector({ athletes, activeKey, onSelect, disabled }: Props) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-gray-600 mr-1">
        Viewing:
      </span>
      {athletes.map((a) => {
        const meta = ATHLETE_META[a.key] ?? { emoji: "👤", color: "text-gray-300", ring: "ring-gray-400" };
        const isActive = a.key === activeKey;
        return (
          <button
            key={a.key}
            onClick={() => !disabled && onSelect(a)}
            disabled={disabled}
            title={`View ${a.name}'s data`}
            className={`
              flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium
              transition-all duration-150 disabled:cursor-not-allowed
              ${isActive
                ? `bg-white/12 ${meta.color} ring-1 ${meta.ring}`
                : "bg-transparent text-gray-500 hover:text-gray-300 hover:bg-white/8"
              }
            `}
          >
            <span className="text-sm leading-none">{meta.emoji}</span>
            {a.name}
          </button>
        );
      })}
    </div>
  );
}
