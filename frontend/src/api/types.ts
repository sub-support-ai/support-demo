export type UserRole = "user" | "agent" | "admin";

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
}

export interface Conversation {
  id: number;
  user_id: number;
  status: string;
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
  status: string;
  department: string;
  ticket_source: string;
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

export interface EscalateResponse {
  ticket: Ticket;
  conversation_id: number;
}

export interface ApiErrorPayload {
  detail?: string | Array<{ loc?: Array<string | number>; msg?: string; type?: string }>;
}
