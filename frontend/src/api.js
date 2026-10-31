// All calls go to the real FastAPI backend (same origin in production, proxied in dev).
export async function getOverview() {
  const res = await fetch("/api/overview?history=120");
  if (!res.ok) throw new Error(`Backend returned ${res.status}`);
  return res.json();
}

export async function post(path, body, apiKey) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) throw new Error("Wrong API key. Check the API_KEY value on the server.");
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  }
  return res.json();
}
