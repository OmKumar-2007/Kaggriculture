export function formatApiError(detail, fallback = "Request failed.") {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail.map((entry) => {
      if (typeof entry === "string") return entry;

      if (entry && typeof entry === "object") {
        const location = Array.isArray(entry.loc)
          ? entry.loc.join(".")
          : "";
        const message = typeof entry.msg === "string"
          ? entry.msg
          : "";

        return [location, message].filter(Boolean).join(": ");
      }

      return "";
    }).filter(Boolean);

    if (messages.length) return messages.join("; ");
  }

  if (detail && typeof detail === "object" &&
      typeof detail.message === "string" && detail.message.trim()) {
    return detail.message;
  }

  return fallback;
}

export function safeLatencyMs(value) {
  if (typeof value !== "number" ||
      !Number.isFinite(value) || value < 0) {
    return null;
  }

  return Math.min(10000, Math.round(value));
}

export function isSessionTermination(status) {
  return status === 401 || status === 423;
}
