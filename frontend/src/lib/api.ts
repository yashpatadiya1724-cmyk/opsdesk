import { TicketsListResponse, TicketDetail, InsightsResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

async function request<T>(path: string, options: RequestInit = {}, userId: string = "USR-101"): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers = new Headers(options.headers || {});
  headers.set("X-User-Id", userId);
  if (!headers.has("Content-Type") && options.body && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    let errorDetail = `HTTP ${res.status}`;
    try {
      const errJson = await res.json();
      errorDetail = errJson.detail || errorDetail;
    } catch {
      // ignore json parse error
    }
    throw new Error(errorDetail);
  }
  return res.json();
}

export async function fetchTickets(
  view: string = "triage",
  limit: number = 20,
  offset: number = 0,
  userId: string = "USR-101",
  intentFilter?: string
): Promise<TicketsListResponse> {
  let path = `/api/tickets?view=${encodeURIComponent(view)}&limit=${limit}&offset=${offset}`;
  if (intentFilter) {
    path += `&intent=${encodeURIComponent(intentFilter)}`;
  }
  return request<TicketsListResponse>(path, {}, userId);
}

export async function fetchTicketDetail(id: string, userId: string = "USR-101"): Promise<TicketDetail> {
  return request<TicketDetail>(`/api/tickets/${encodeURIComponent(id)}`, {}, userId);
}

export async function createTicket(
  payload: {
    title: string;
    description: string;
    tboh_id: string;
    priority: string;
    check_in_date: string;
    lcd_date?: string | null;
    intent?: string | null;
    agency_id?: string | null;
  },
  userId: string = "USR-101"
): Promise<{ id: string; tboh_id: string; status: string }> {
  return request("/api/tickets", {
    method: "POST",
    body: JSON.stringify(payload),
  }, userId);
}

export async function assignTicket(ticketId: string, agentId: string, userId: string = "USR-101") {
  return request(`/api/tickets/${ticketId}/assign`, {
    method: "POST",
    body: JSON.stringify({ agent_id: agentId }),
  }, userId);
}

export async function unassignTicket(ticketId: string, userId: string = "USR-101") {
  return request(`/api/tickets/${ticketId}/unassign`, {
    method: "POST",
  }, userId);
}

export async function updateTicketStatus(ticketId: string, status: string, userId: string = "USR-101") {
  return request(`/api/tickets/${ticketId}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  }, userId);
}

export async function escalateTicket(ticketId: string, reason: string, userId: string = "USR-101") {
  return request(`/api/tickets/${ticketId}/escalate`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  }, userId);
}

export async function transferTicket(ticketId: string, targetAgentId: string, reason: string, userId: string = "USR-101") {
  return request(`/api/tickets/${ticketId}/transfer`, {
    method: "POST",
    body: JSON.stringify({ target_agent_id: targetAgentId, reason }),
  }, userId);
}

export async function postMessage(ticketId: string, messageType: "PublicReply" | "InternalNote", content: string, userId: string = "USR-101") {
  return request(`/api/tickets/${ticketId}/messages`, {
    method: "POST",
    body: JSON.stringify({ message_type: messageType, content }),
  }, userId);
}

export async function createSideThread(
  ticketId: string,
  payload: { supplier_name: string; subject: string; recipients: string[]; initial_message: string },
  userId: string = "USR-101"
) {
  return request(`/api/tickets/${ticketId}/side-threads`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, userId);
}

export async function postSideThreadMessage(ticketId: string, sideConversationId: string, body: string, userId: string = "USR-101") {
  return request(`/api/tickets/${ticketId}/side-threads/${sideConversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ body }),
  }, userId);
}

export async function suggestIntent(title: string, description: string, userId: string = "USR-101") {
  return request<{ intent: string; confidence: number; source: string }>("/api/ai/suggest-intent", {
    method: "POST",
    body: JSON.stringify({ title, description }),
  }, userId);
}

export async function linkSuggestedBug(ticketId: string, bugLink: string, userId: string = "USR-101") {
  return request(`/api/tickets/${ticketId}/link-suggestion`, {
    method: "POST",
    body: JSON.stringify({ bug_link: bugLink }),
  }, userId);
}

export async function fetchInsightsThemes(days: number = 7, userId: string = "USR-104"): Promise<InsightsResponse> {
  return request<InsightsResponse>(`/api/insights/themes?days=${days}`, {}, userId);
}

export function getExportUrl(): string {
  return `${API_BASE}/api/export/tickets.csv`;
}
