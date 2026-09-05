// Centralized typed API client for J.A.R.V.I.S backend.
// All calls go through this module — components never construct URLs.
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

const http = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  timeout: 60000,
});

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const detail = err?.response?.data?.detail;
    const msg = typeof detail === "string" ? detail : detail?.message || err.message;
    err.jarvis = { code: detail?.code, message: msg, status: err?.response?.status };
    return Promise.reject(err);
  }
);

export const api = {
  health:            () => http.get("/health").then((r) => r.data),
  diagnostics:       () => http.get("/diagnostics").then((r) => r.data),
  insight:           () => http.get("/insight").then((r) => r.data),

  // Chat
  chat:              (message, session_id) => http.post("/chat", { message, session_id }).then((r) => r.data),
  listSessions:      () => http.get("/chat/sessions").then((r) => r.data),
  sessionMessages:   (id) => http.get(`/chat/sessions/${id}/messages`).then((r) => r.data),
  deleteSession:     (id) => http.delete(`/chat/sessions/${id}`).then((r) => r.data),

  // Notes
  listNotes:         () => http.get("/notes").then((r) => r.data),
  createNote:        (n) => http.post("/notes", n).then((r) => r.data),
  updateNote:        (id, n) => http.put(`/notes/${id}`, n).then((r) => r.data),
  deleteNote:        (id) => http.delete(`/notes/${id}`).then((r) => r.data),

  // Approvals
  listApprovals:     () => http.get("/approvals").then((r) => r.data),
  createApproval:    (a) => http.post("/approvals", a).then((r) => r.data),
  decideApproval:    (id, decision) => http.post(`/approvals/${id}`, { decision }).then((r) => r.data),

  // Checkpoints
  listCheckpoints:   () => http.get("/checkpoints").then((r) => r.data),
  createCheckpoint:  (c) => http.post("/checkpoints", c).then((r) => r.data),
  restoreCheckpoint: (id) => http.post(`/checkpoints/${id}/restore`).then((r) => r.data),

  // Admin LLM
  getLLM:            () => http.get("/admin/llm").then((r) => r.data),
  putLLM:            (cfg) => http.put("/admin/llm", cfg).then((r) => r.data),

  // Council
  getCouncil:        () => http.get("/admin/council").then((r) => r.data),
  upsertMember:      (id, m) => http.put(`/admin/council/members/${id}`, m).then((r) => r.data),
  deleteMember:      (id) => http.delete(`/admin/council/members/${id}`).then((r) => r.data),

  // UI actions bus
  pollUIActions:     (session_id) => http.get("/ui/actions", { params: session_id ? { session_id } : {} }).then((r) => r.data),
  postUIAction:      (a) => http.post("/ui/actions", a).then((r) => r.data),

  // Coding loop
  codingRun:         (message, session_id) => http.post("/coding/run", { message, session_id }).then((r) => r.data),

  // Memory
  listMemory:        (kind, q) => http.get("/memory", { params: { kind, q } }).then((r) => r.data),
  addMemory:         (m) => http.post("/memory", m).then((r) => r.data),

  // Panel natural-language commands (Jarvis writes for you)
  panelCommand:      (panel, message) => http.post("/panels/command", { panel, message }).then((r) => r.data),

  // Apps: calendar / reminders / weather / translate
  listEvents:        (month) => http.get("/events", { params: month ? { month } : {} }).then((r) => r.data),
  createEvent:       (e) => http.post("/events", e).then((r) => r.data),
  deleteEvent:       (id) => http.delete(`/events/${id}`).then((r) => r.data),
  listReminders:     () => http.get("/reminders").then((r) => r.data),
  createReminder:    (rm) => http.post("/reminders", rm).then((r) => r.data),
  patchReminder:     (id, done) => http.patch(`/reminders/${id}`, { done }).then((r) => r.data),
  deleteReminder:    (id) => http.delete(`/reminders/${id}`).then((r) => r.data),
  weather:           (city) => http.get("/weather", { params: { city } }).then((r) => r.data),
  translate:         (text, target) => http.post("/translate", { text, target }).then((r) => r.data),
};

/**
 * SSE streaming for /chat/stream. Yields token deltas via callbacks.
 * Uses fetch + ReadableStream (EventSource does not support POST).
 */
export async function streamChat({ message, session_id, onSession, onDelta, onDone, onError, signal }) {
  try {
    const res = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message, session_id }),
      signal,
    });
    if (!res.ok || !res.body) {
      const t = await res.text().catch(() => "");
      throw new Error(`stream_failed_${res.status}: ${t}`);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const chunk of parts) {
        const lines = chunk.split("\n");
        let event = "message"; let data = "";
        for (const ln of lines) {
          if (ln.startsWith("event:")) event = ln.slice(6).trim();
          else if (ln.startsWith("data:")) data += ln.slice(5).trim();
        }
        if (!data) continue;
        try {
          const parsed = JSON.parse(data);
          if (event === "session") onSession?.(parsed.session_id);
          else if (event === "done") onDone?.(parsed);
          else if (event === "error") onError?.(new Error(parsed.message || "stream error"));
          else if (parsed.delta) onDelta?.(parsed.delta);
        } catch { /* swallow malformed chunk */ }
      }
    }
    onDone?.({});
  } catch (e) {
    onError?.(e);
  }
}
