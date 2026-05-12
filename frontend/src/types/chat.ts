export interface RAGSource {
  doc_title: string;
  section_title: string;
  source_file: string;
  score: number;
  excerpt: string;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cache_read_tokens?: number;
}

export interface RAGResponse {
  answer: string;
  in_scope: boolean;
  sources: RAGSource[];
  intent: string | null;
  model: string | null;
  usage: TokenUsage | null;
}

export type MessageRole = "user" | "assistant";

export interface PipelineStep {
  label: string;
  detail?: string;
  status: "pending" | "done" | "skipped";
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  ragResponse?: RAGResponse;
  pipelineSteps?: PipelineStep[];
  isLoading?: boolean;
  error?: string;
}
