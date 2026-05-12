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
    <div className="absolute bottom-full left-0 right-0 mb-2 border border-violet-200 bg-white shadow-lg overflow-hidden z-50">
      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-violet-500 border-b border-neutral-100">
        Mention
      </div>
      {filtered.map((m) => (
        <button
          key={m.id}
          onClick={() => onSelect(m)}
          className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-violet-50 transition-colors"
        >
          <span className="mt-0.5 text-base leading-none">{m.emoji}</span>
          <div className="min-w-0">
            <span className="text-sm font-medium text-violet-600">{m.label}</span>
            <p className="text-xs text-neutral-500 mt-0.5">{m.description}</p>
          </div>
        </button>
      ))}
    </div>
  );
}

export type { AtMention };
