const STATIC_ROUTES = new Set(["today", "history", "birds", "favorites"]);

function routeParts(hash) {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const [path, query = ""] = raw.split("?", 2);
  return {segments: path.split("/").filter(Boolean), query};
}

function decodeSegment(segment) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

function recognized(hash) {
  const {segments} = routeParts(hash);
  if (segments.length === 1 && STATIC_ROUTES.has(segments[0])) return true;
  return segments.length === 2 && (
    (segments[0] === "species" && decodeSegment(segments[1]) !== null) ||
    (segments[0] === "visits" && decodeSegment(segments[1]) !== null)
  );
}

export function parseRoute(hash = "") {
  const {segments, query} = routeParts(hash);
  const params = new URLSearchParams(query);

  if (segments.length === 1 && STATIC_ROUTES.has(segments[0])) {
    return {name: segments[0], params};
  }
  if (segments.length === 2 && segments[0] === "species" && segments[1]) {
    const key = decodeSegment(segments[1]);
    if (key !== null) {
      params.set("key", key);
      return {name: "species", params};
    }
  }
  if (segments.length === 2 && segments[0] === "visits" && segments[1]) {
    const id = decodeSegment(segments[1]);
    if (id !== null) {
      params.set("id", id);
      return {name: "visit", params};
    }
  }
  return {name: "today", params: new URLSearchParams()};
}

export function startRouter(render) {
  const handleRoute = () => {
    if (!recognized(window.location.hash)) {
      window.location.hash = "#/today";
    }
    render(parseRoute(window.location.hash));
  };

  window.addEventListener("hashchange", handleRoute);
  handleRoute();
  return () => window.removeEventListener("hashchange", handleRoute);
}
