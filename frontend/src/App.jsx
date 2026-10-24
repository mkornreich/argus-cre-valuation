import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api.js";
import AssumptionsPanel from "./components/AssumptionsPanel.jsx";
import RentRoll from "./components/RentRoll.jsx";
import ExpensesTable from "./components/ExpensesTable.jsx";
import Results from "./components/Results.jsx";

export default function App() {
  const [scenario, setScenario] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const debounce = useRef(null);

  // Load the sample deal on first render.
  useEffect(() => {
    api
      .getSample()
      .then(setScenario)
      .catch((e) => setError(e.message));
  }, []);

  // Re-run the valuation (debounced) whenever the scenario changes.
  const runAnalysis = useCallback((next) => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      setBusy(true);
      api
        .analyze(next)
        .then((r) => {
          setResult(r);
          setError(null);
        })
        .catch((e) => setError(e.message))
        .finally(() => setBusy(false));
    }, 250);
  }, []);

  useEffect(() => {
    if (scenario) runAnalysis(scenario);
  }, [scenario, runAnalysis]);

  function update(patch) {
    setScenario((prev) => ({ ...prev, ...patch }));
  }

  async function reloadSample() {
    try {
      setScenario(await api.getSample());
    } catch (e) {
      setError(e.message);
    }
  }

  if (!scenario) {
    return (
      <div className="loading">
        {error ? (
          <div className="banner error">
            Could not reach the API: {error}. Is the Flask backend running on
            port 5001?
          </div>
        ) : (
          "Loading ARGUS…"
        )}
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">ARGUS</span>
          <span className="brand-sub">CRE Valuation &amp; DCF</span>
        </div>
        <div className="topbar-right">
          {busy && <span className="status">calculating…</span>}
          <button className="btn ghost" onClick={reloadSample}>
            Reset to sample
          </button>
        </div>
      </header>

      {error && <div className="banner error">{error}</div>}

      <div className="layout">
        <aside className="sidebar">
          <AssumptionsPanel scenario={scenario} onChange={update} />
          <RentRoll
            leases={scenario.leases}
            onChange={(leases) => update({ leases })}
          />
          <ExpensesTable
            expenses={scenario.expenses}
            totalSf={scenario.property.total_sf}
            onChange={(expenses) => update({ expenses })}
          />
        </aside>

        <main className="main">
          <Results result={result} scenario={scenario} />
        </main>
      </div>

      <footer className="footer">
        A lease-by-lease discounted-cash-flow model in the spirit of ARGUS ·
        Flask + React · figures are illustrative, not investment advice.
      </footer>
    </div>
  );
}
