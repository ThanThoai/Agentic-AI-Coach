"use client";

interface AtMention {
  id: string;
  label: string;
  description: string;
  emoji: string;
}

const MENTIONS: AtMention[] = [
  {
    id: "AgentAssist",
    label: "@AgentAssist",
    description: "Ask the coach AI agent — uses both your athlete's data and the knowledge base",
    emoji: "🤖",
  },
];

interface Props {
  query: string;
  onSelect: (mention: AtMention) => void;
}

export function AtMentionMenu({ query, onSelect }: Props) {
  const filtered = MENTIONS.filter((m) =>
    m.id.toLowerCase().startsWith(query.toLowerCase()),
  );

  if (filtered.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 rounded-xl border border-purple-500/20 bg-gray-900 shadow-2xl overflow-hidden z-50">
      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-purple-600 border-b border-white/8">
        Mention
      </div>
      {filtered.map((m) => (
        <button
          key={m.id}
          onClick={() => onSelect(m)}
          className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-purple-500/10 transition-colors group"
        >
          <span className="mt-0.5 text-base leading-none">{m.emoji}</span>
          <div className="min-w-0">
            <span className="text-sm font-medium text-purple-400 group-hover:text-purple-300">
              {m.label}
            </span>
            <p className="text-xs text-gray-500 mt-0.5">{m.description}</p>
          </div>
        </button>
      ))}
    </div>
  );
}

export type { AtMention };
