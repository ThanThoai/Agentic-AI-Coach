"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message } from "@/types/chat";
import { ThinkingPanel } from "./ThinkingPanel";
import { SourceList } from "./SourceList";
import { Spinner } from "@/components/ui/Spinner";

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2.5 text-sm text-white leading-relaxed">
          {message.content}
        </div>
      </div>
    );
  }

  const isStreaming = !!message.isLoading && !!message.content;

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] min-w-[240px]">
        {/* Pipeline thinking panel */}
        {message.pipelineSteps && (
          <ThinkingPanel
            steps={message.pipelineSteps}
            ragResponse={message.ragResponse}
            isLoading={!!message.isLoading}
          />
        )}

        {/* Answer bubble */}
        <div className="rounded-2xl rounded-tl-sm bg-white/[0.08] px-4 py-3 text-sm leading-relaxed">
          {message.isLoading && !message.content ? (
            <div className="flex items-center gap-2 text-gray-400">
              <Spinner size={14} />
              <span>Thinking…</span>
            </div>
          ) : message.error ? (
            <p className="text-red-400">{message.error}</p>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none
              prose-p:my-1.5 prose-ul:my-1.5 prose-ol:my-1.5
              prose-li:my-0.5 prose-headings:mb-2 prose-headings:mt-3
              prose-strong:text-gray-200 prose-code:text-indigo-300
              prose-code:bg-white/10 prose-code:px-1 prose-code:rounded
              prose-blockquote:border-indigo-500 prose-blockquote:text-gray-400">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
              {isStreaming && (
                <span className="ml-0.5 inline-block h-[1em] w-0.5 translate-y-[2px] animate-pulse rounded-sm bg-gray-400" />
              )}
            </div>
          )}
        </div>

        {/* Sources */}
        {message.ragResponse?.sources && message.ragResponse.sources.length > 0 && !message.isLoading && (
          <SourceList sources={message.ragResponse.sources} />
        )}
      </div>
    </div>
  );
}
