"use client";

import type { DemoUser } from "@/types/chat";

interface UserSelectorProps {
  users: DemoUser[];
  activeKey: string;
  onSelect: (user: DemoUser) => void;
  loading: boolean;
}

const USER_META: Record<string, { color: string; bg: string; emoji: string }> = {
  alex: { color: "text-indigo-300", bg: "bg-indigo-600", emoji: "💪" },
  binh: { color: "text-emerald-300", bg: "bg-emerald-600", emoji: "🏃" },
};

export function UserSelector({ users, activeKey, onSelect, loading }: UserSelectorProps) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-gray-600 mr-1">User:</span>
      {users.map((user) => {
        const meta = USER_META[user.key] ?? { color: "text-gray-300", bg: "bg-gray-600", emoji: "👤" };
        const isActive = user.key === activeKey;
        return (
          <button
            key={user.key}
            onClick={() => !loading && onSelect(user)}
            disabled={loading}
            title={`Switch to ${user.name}`}
            className={`
              flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium
              transition-all duration-150 disabled:cursor-not-allowed
              ${isActive
                ? `${meta.bg} text-white shadow-md ring-2 ring-white/20`
                : "bg-white/8 text-gray-400 hover:bg-white/12 hover:text-gray-200"
              }
            `}
          >
            <span className="text-sm leading-none">{meta.emoji}</span>
            {user.name}
          </button>
        );
      })}
    </div>
  );
}
