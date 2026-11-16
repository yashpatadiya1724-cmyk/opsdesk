export type Role = "Requester" | "Agent" | "Lead" | "EscalationManager";

export interface DemoUser {
  id: string;
  name: string;
  role: Role;
  agencyId: string | null;
  region: string | null;
  description: string;
}

export const DEMO_USERS: DemoUser[] = [
  { id: "USR-101", name: "Aisha Khan", role: "Agent", agencyId: null, region: "MEA", description: "Operations Agent (MEA Desk)" },
  { id: "USR-102", name: "Rahul Verma", role: "Agent", agencyId: null, region: "APAC", description: "Operations Agent (APAC Desk)" },
  { id: "USR-103", name: "Vikram Joshi", role: "EscalationManager", agencyId: null, region: "Global", description: "Escalation Manager (Global)" },
  { id: "USR-104", name: "Elena Rostova", role: "Lead", agencyId: null, region: "Global", description: "Operations Team Lead (Global)" },
  { id: "USR-201", name: "Grand Travel Agency", role: "Requester", agencyId: "AGY-001", region: null, description: "B2B Agency Requester (AGY-001)" },
  { id: "USR-202", name: "Apex Journeys", role: "Requester", agencyId: "AGY-002", region: null, description: "B2B Agency Requester (AGY-002)" },
];

export interface SLAStatus {
  status: "NORMAL" | "AT_RISK" | "BREACHED" | "STOPPED";
  color: "Green" | "Amber" | "Red" | "Gray";
  badge: string;
  hours_remaining: number | null;
}

export interface TicketSummary {
  id: string;
  tboh_id: string;
  agency_id: string;
  title: string;
  intent: string | null;
  priority: "Low" | "Medium" | "High" | "Urgent";
  status: "New" | "Open" | "Pending" | "Escalated" | "Resolved" | "Closed";
  check_in_date: string;
  lcd_date: string | null;
  assigned_to: string | null;
  routing_reason: string | null;
  sla: SLAStatus;
  queue_score: number | null;
  created_at: string;
}

export interface TicketMessage {
  id: string;
  message_type: "PublicReply" | "InternalNote";
  content: string;
  sender_user_id: string;
  sender_name: string;
  created_at: string;
}

export interface SideConversationMessage {
  id: string;
  sender_email: string;
  body: string;
  created_at: string;
}

export interface SideConversation {
  id: string;
  supplier_name: string;
  subject: string;
  recipients: string[];
  created_by: string;
  created_at: string;
  messages: SideConversationMessage[];
}

export interface TicketDetail extends TicketSummary {
  description: string;
  suggested_bug_link: string | null;
  linked_ticket_ids: string[];
  messages: TicketMessage[];
  side_conversations: SideConversation[];
  updated_at: string;
}

export interface ThemeInsight {
  theme: string;
  count: number;
  percentage: number;
  sample_ticket_ids: string[];
}

export interface InsightsResponse {
  time_window_days: number;
  total_tagged_records: number;
  themes: ThemeInsight[];
}

export interface TicketsListResponse {
  total: number;
  limit: number;
  offset: number;
  tickets: TicketSummary[];
}
