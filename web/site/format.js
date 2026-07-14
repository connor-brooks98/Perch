export function formatRelativeTime(value, now = Date.now()) {
  if (!value) return "";
  const timestamp = new Date(String(value).replace(" ", "T")).getTime();
  if (!Number.isFinite(timestamp)) return "";

  const seconds = Math.max(0, (now - timestamp) / 1000);
  const minutes = seconds / 60;
  const hours = minutes / 60;
  const days = hours / 24;
  if (seconds < 90) return "just now";
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  if (hours < 24) return `${Math.round(hours)} hr ago`;
  if (days < 7) {
    const rounded = Math.round(days);
    return `${rounded} day${rounded === 1 ? "" : "s"} ago`;
  }
  return new Date(timestamp).toLocaleDateString(undefined, {month: "short", day: "numeric"});
}

export function formatConfidence(confidence) {
  return `${Math.round(Number(confidence) * 100)}%`;
}

export function formatVisitCount(count) {
  return `${count} visit${Number(count) === 1 ? "" : "s"}`;
}

export function formatDate(value, options = {month: "long", day: "numeric", year: "numeric"}) {
  if (!value) return "";
  return new Date(String(value).replace(" ", "T")).toLocaleDateString(undefined, options);
}

export function formatTime(value) {
  if (!value) return "";
  return new Date(String(value).replace(" ", "T")).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}
