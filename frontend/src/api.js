// Thin API client. In dev, Vite proxies /api -> Flask (see vite.config.js).

async function request(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.error || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const getSample = () => request("/api/sample");
export const analyze = (scenario) =>
  request("/api/analyze", { method: "POST", body: JSON.stringify(scenario) });
export const listScenarios = () => request("/api/scenarios");
export const saveScenario = (name, scenario) =>
  request("/api/scenarios", {
    method: "POST",
    body: JSON.stringify({ name, scenario }),
  });
export const loadScenario = (id) => request(`/api/scenarios/${id}`);
export const deleteScenario = (id) =>
  request(`/api/scenarios/${id}`, { method: "DELETE" });
