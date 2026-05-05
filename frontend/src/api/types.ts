export type UserRole = "user" | "agent" | "admin";
export type TicketStatus =
  | "new"
  | "pending_user"
  | "confirmed"
  | "in_progress"
  | "resolved"
  | "closed"
  | "ai_processing"
  | "declined"
  | "escalated"
  | "active";
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
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Source {
  title: string;
  url?: string | null;
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
  steps_tried?: string | null;
  confirmed_by_user: boolean;
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
}

export interface TicketStatusUpdate {
  status: TicketMutableStatus;
}

export interface ResolveTicketPayload {
  agent_accepted_ai_response: boolean;
  correction_lag_seconds?: number | null;
}

export interface EscalationContext {
  requester_name: string;
  requester_email: string;
  office: string;
  affected_item: string;
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

export interface TicketStats {
  total: number;
  by_status: Record<string, number>;
  by_department: Record<string, number>;
  by_source: Record<string, number>;
}

export interface AiStats {
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
  ai: AiStats;
}
