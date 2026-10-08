export const API_BASE = import.meta.env.VITE_API_BASE || "";

let csrfToken = "";
let activeTeam = "";
let heartbeatTimer = null;
let lastLatency = null;

export async function restoreParticipantSession() {
  const response = await fetch(`${API_BASE}/api/participants/session`, { credentials: "include" });
  if (!response.ok) { csrfToken = ""; activeTeam = ""; return null; }
  const session = await response.json();
  csrfToken = session.csrfToken;
  activeTeam = session.team;
  startHeartbeat(session.heartbeatIntervalSeconds);
  return session;
}

export async function signInParticipant(team) {
  const response = await fetch(`${API_BASE}/api/participants/session`, {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Team sign-in failed.");
  csrfToken = data.csrfToken;
  activeTeam = data.team;
  startHeartbeat(data.heartbeatIntervalSeconds);
  return data;
}

export async function recoverParticipant(team, recoveryCode) {
  const response = await fetch(`${API_BASE}/api/participants/recover`, {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team, recoveryCode }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Recovery failed.");
  csrfToken = data.csrfToken;
  activeTeam = data.team;
  startHeartbeat(data.heartbeatIntervalSeconds);
  return data;
}

export async function logoutParticipant() {
  try { await participantFetch("/api/participants/logout", { method: "POST" }); }
  finally {
    csrfToken = ""; activeTeam = "";
    if (heartbeatTimer) window.clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

export async function participantFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && !csrfToken) await restoreParticipantSession();
  return fetch(`${API_BASE}${path}`, {
    ...options, credentials: "include",
    headers: { ...(csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method) ? { "X-Participant-CSRF": csrfToken } : {}), ...options.headers },
  });
}

function startHeartbeat(seconds = 15) {
  if (heartbeatTimer) window.clearInterval(heartbeatTimer);
  const beat = async () => {
    if (!activeTeam || !csrfToken) return;
    const started = performance.now();
    try {
      const response = await participantFetch("/api/participants/heartbeat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idle: document.visibilityState !== "visible", latencyMs: lastLatency }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        csrfToken = ""; activeTeam = "";
        window.dispatchEvent(new CustomEvent("farmcraft:session-ended", { detail: body.detail || "Your session has ended. Please contact an organizer if needed." }));
        return;
      }
      lastLatency = Math.round(performance.now() - started);
    } catch { /* The next heartbeat handles a temporary disconnect. */ }
  };
  void beat();
  heartbeatTimer = window.setInterval(beat, Math.max(5, seconds) * 1000);
}
