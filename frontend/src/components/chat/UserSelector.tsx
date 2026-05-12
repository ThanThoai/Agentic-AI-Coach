"use client";

import type { DemoUser } from "@/types/chat";

interface UserSelectorProps {
  users: DemoUser[];
  activeKey: string;
  onSelect: (user: DemoUser) => void;
  loading: boolean;
}

const USER_META: Record<string, { activeClass: string; emoji: string; label?: string }> = {
  alex:  { activeClass: "bg-indigo-600 text-white border-indigo-600",  emoji: "💪" },
  binh:  { activeClass: "bg-emerald-600 text-white border-emerald-600", emoji: "🏃" },
  coach: { activeClass: "bg-violet-600 text-white border-violet-600",  emoji: "🎯", label: "Coach" },
};

export function UserSelector({ users, activeKey, onSelect, loading }: UserSelectorProps) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-neutral-400 mr-0.5">User:</span>
      {users.map((user) => {
        const meta = USER_META[user.key] ?? { activeClass: "bg-neutral-700 text-white border-neutral-700", emoji: "👤" };
        const isActive = user.key === activeKey;
        const isCoach = user.role === "coach";
        return (
          <button
            key={user.key}
            onClick={() => !loading && onSelect(user)}
            disabled={loading}
            title={`Switch to ${user.name}`}
            className={`
              flex items-center gap-1.5 border px-2.5 py-1 text-xs font-medium
              transition-colors disabled:cursor-not-allowed
              ${isActive
                ? meta.activeClass
                : "border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50 hover:text-neutral-800"
              }
            `}
          >
            <span className="text-sm leading-none">{meta.emoji}</span>
            {meta.label ?? user.name}
            {isCoach && (
              <span className={`text-[9px] font-bold uppercase tracking-wider ${isActive ? "text-violet-200" : "text-violet-500"}`}>
                PRO
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
