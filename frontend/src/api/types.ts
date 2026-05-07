export type UserRole = "user" | "agent" | "admin";

export type TicketStatus =
  | "new"
  | "pending_user"
  | "confirmed"
  | "in_progress"
  | "resolved"
  | "closed"
  | "ai_processing"
  | "declined";

export type ConversationStatus =
  | "active"
  | "ai_processing"
  | "escalated"
  | "closed";

export type TicketMutableStatus =
  | "new"
  | "pending_user"
  | "confirmed"
  | "in_progress"
  | "resolved"
  | "closed"
  | "ai_processing"
  | "declined";

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserMe {
  id: number;
  email: string;
  username: string;
  role: UserRole;
  is_active: boolean;
  agent_id?: number | null;
  agent_department?: string | null;
  request_context?: RequestContextDefaults | null;
}

export interface RequestContextDefaults {
  requester_name: string;
  requester_email: string;
  office?: string | null;
  office_source?: string | null;
  office_options: string[];
  affected_item_options: string[];
}

export interface Conversation {
  id: number;
  user_id: number;
  status: ConversationStatus | string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Source {
  title: string;
  url?: string | null;
  article_id?: number | null;
  chunk_id?: number | null;
  snippet?: string | null;
  retrieval?: "keyword" | "full_text" | "semantic" | string | null;
  score?: number | null;
  decision?: "answer" | "clarify" | "escalate" | string | null;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: "user" | "ai";
  content: string;
  sources?: Source[] | null;
  ai_confidence?: number | null;
  ai_escalate?: boolean | null;
  requires_escalation?: boolean | null;
}

export interface Ticket {
  id: number;
  user_id: number;
  agent_id?: number | null;
  conversation_id?: number | null;
  title: string;
  body: string;
  user_priority: number;
  status: TicketStatus | string;
  department: string;
  ticket_source: string;
  requester_name?: string | null;
  requester_email?: string | null;
  office?: string | null;
  affected_item?: string | null;
  request_type?: string | null;
  request_details?: string | null;
  steps_tried?: string | null;
  confirmed_by_user: boolean;
  sla_started_at?: string | null;
  sla_deadline_at?: string | null;
  sla_escalated_at?: string | null;
  sla_escalation_count?: number;
  is_sla_breached?: boolean;
  reopen_count?: number;
  ai_category?: string | null;
  ai_priority?: string | null;
  ai_confidence?: number | null;
  ai_processed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
  resolved_at?: string | null;
}

export interface TicketDraftUpdate {
  title?: string;
  body?: string;
  department?: "IT" | "HR" | "finance";
  ai_priority?: "низкий" | "средний" | "высокий";
  requester_name?: string | null;
  requester_email?: string | null;
  steps_tried?: string | null;
  office?: string | null;
  affected_item?: string | null;
  request_type?: string | null;
  request_details?: string | null;
}

export interface TicketStatusUpdate {
  status: TicketMutableStatus;
}

export interface ResolveTicketPayload {
  agent_accepted_ai_response: boolean;
  routing_was_correct?: boolean;
  correction_lag_seconds?: number | null;
}

export interface EscalationContext {
  requester_name: string;
  requester_email: string;
  office: string;
  affected_item: string;
  request_type?: string | null;
  request_details?: string | null;
}

export interface EscalateResponse {
  ticket: Ticket;
  conversation_id: number;
}

export interface ApiErrorPayload {
  detail?:
    | string
    | { message?: string; fields?: string[] }
    | Array<{ loc?: Array<string | number>; msg?: string; type?: string }>;
}

export interface TicketComment {
  id: number;
  ticket_id: number;
  author_id: number;
  author_username: string;
  author_role: string;
  content: string;
  internal: boolean;
  created_at: string;
}

export interface TicketCommentCreate {
  content: string;
  internal?: boolean;
}

export interface TicketFeedbackPayload {
  feedback: "helped" | "not_helped";
  reopen?: boolean;
}

export interface KnowledgeFeedbackPayload {
  message_id: number;
  article_id: number;
  feedback: "helped" | "not_helped" | "not_relevant";
}

export interface KnowledgeArticle {
  id: number;
  department?: "IT" | "HR" | "finance" | null;
  request_type?: string | null;
  title: string;
  body: string;
  problem?: string | null;
  symptoms?: string[] | null;
  applies_to?: Record<string, string[]> | null;
  steps?: string[] | null;
  when_to_escalate?: string | null;
  required_context?: string[] | null;
  keywords?: string | null;
  source_url?: string | null;
  owner?: string | null;
  access_scope: "public" | "internal";
  version: number;
  reviewed_at?: string | null;
  expires_at?: string | null;
  is_active: boolean;
  view_count: number;
  helped_count: number;
  not_helped_count: number;
  not_relevant_count: number;
  created_at: string;
  updated_at?: string | null;
}

export interface KnowledgeArticlePayload {
  department?: "IT" | "HR" | "finance" | null;
  request_type?: string | null;
  title: string;
  body: string;
  problem?: string | null;
  symptoms?: string[] | null;
  steps?: string[] | null;
  when_to_escalate?: string | null;
  required_context?: string[] | null;
  keywords?: string | null;
  source_url?: string | null;
  owner?: string | null;
  access_scope?: "public" | "internal";
  is_active?: boolean;
}

export interface KnowledgeEmbeddingJob {
  id: number;
  article_id?: number | null;
  requested_by_user_id?: number | null;
  status: string;
  attempts: number;
  max_attempts: number;
  updated_chunks: number;
  embedding_model?: string | null;
  error?: string | null;
  run_after?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface AIJob {
  id: number;
  conversation_id: number;
  status: string;
  attempts: number;
  max_attempts: number;
  error?: string | null;
  run_after: string;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface FailedJobsResponse {
  ai: AIJob[];
  knowledge_embeddings: KnowledgeEmbeddingJob[];
}

export type JobKind = "all" | "ai" | "knowledge_embeddings";
export type JobStatusFilter = "all" | "queued" | "running" | "done" | "failed";

export interface JobsResponse {
  ai: AIJob[];
  knowledge_embeddings: KnowledgeEmbeddingJob[];
}

export interface ResponseTemplate {
  id: number;
  department?: "IT" | "HR" | "finance" | null;
  request_type?: string | null;
  title: string;
  body: string;
  is_active: boolean;
  created_at: string;
  updated_at?: string | null;
}

export interface TicketStats {
  total: number;
  by_status: Record<string, number>;
  by_department: Record<string, number>;
  by_source: Record<string, number>;
  sla_overdue_count: number;
  sla_escalated_count: number;
  reopen_count: number;
}

export interface AIStats {
  total_processed: number;
  avg_confidence: number;
  low_confidence_count: number;
  routing_correct_count: number;
  routing_incorrect_count: number;
  routing_accuracy_pct: number;
  resolved_by_ai_count: number;
  escalated_count: number;
  user_feedback_helped: number;
  user_feedback_not_helped: number;
}

export interface StatsResponse {
  tickets: TicketStats;
  ai: AIStats;
  jobs: JobsStats;
}

export interface JobQueueStats {
  total: number;
  queued: number;
  running: number;
  done: number;
  failed: number;
}

export interface JobsStats {
  ai: JobQueueStats;
  knowledge_embeddings: JobQueueStats;
}
