async function request(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw Object.assign(
      new Error(body.message || "The feeder could not be reached."),
      {status: response.status, body},
    );
  }
  return body;
}

function withParams(path, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of new URLSearchParams(params)) {
    if (value !== "undefined" && value !== "null" && value !== "") {
      query.append(key, value);
    }
  }
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export const getToday = () => request("/api/today");
export const getDetections = (params) => request(withParams("/api/detections", params));
export const getDetection = (id) => request(`/api/detections/${encodeURIComponent(id)}`);
export const patchDetection = (id, patch) => request(
  `/api/detections/${encodeURIComponent(id)}`,
  {method: "PATCH", body: JSON.stringify(patch)},
);
export const getSpecies = (params) => request(withParams("/api/species", params));
export const getSpeciesDetail = (key, params) => request(
  withParams(`/api/species/${encodeURIComponent(key)}`, params),
);
export const searchTaxa = (query) => request(withParams("/api/taxa", {q: query}));
