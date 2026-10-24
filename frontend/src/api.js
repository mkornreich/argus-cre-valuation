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
export const consolidatePortfolio = (ids, scenarios, fund_debt) =>
  request("/api/portfolio", {
    method: "POST",
    body: JSON.stringify({ ids, scenarios, fund_debt }),
  });

export const importRentroll = (csv) =>
  request("/api/import/rentroll", { method: "POST", body: JSON.stringify({ csv }) });

export const listPortfolios = () => request("/api/portfolios");
export const savePortfolio = (name, ids, fund_debt) =>
  request("/api/portfolios", {
    method: "POST",
    body: JSON.stringify({ name, ids, fund_debt }),
  });
export const loadPortfolio = (id) => request(`/api/portfolios/${id}`);
export const deletePortfolioById = (id) =>
  request(`/api/portfolios/${id}`, { method: "DELETE" });

// Fetch the .xlsx report pack and trigger a browser download.
export async function downloadReport(scenario) {
  const res = await fetch("/api/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(scenario),
  });
  if (!res.ok) throw new Error("Report generation failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${(scenario.property?.name || "argus-report").replace(/\s+/g, "_")}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
