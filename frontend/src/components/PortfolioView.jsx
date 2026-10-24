import { useEffect, useState } from "react";
import * as api from "../api.js";
import { currency, percent, number } from "../format.js";
import MetricCard from "./MetricCard.jsx";

// Fund-level consolidation: save deals, pick which to include, and roll them up
// into portfolio value, blended cap rate and a portfolio-level IRR.
export default function PortfolioView({ scenario }) {
  const [saved, setSaved] = useState([]);
  const [selected, setSelected] = useState({});
  const [includeCurrent, setIncludeCurrent] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = () =>
    api.listScenarios().then((list) => {
      setSaved(list);
      setSelected((prev) => {
        const next = { ...prev };
        list.forEach((s) => {
          if (!(s.id in next)) next[s.id] = true;
        });
        return next;
      });
    }).catch((e) => setError(e.message));

  useEffect(() => {
    refresh();
  }, []);

  async function saveCurrent() {
    try {
      await api.saveScenario(scenario.property?.name || "Untitled Deal", scenario);
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function remove(id) {
    await api.deleteScenario(id).catch((e) => setError(e.message));
    refresh();
  }

  async function consolidate() {
    setBusy(true);
    setError(null);
    try {
      const ids = saved.filter((s) => selected[s.id]).map((s) => s.id);
      const scenarios = includeCurrent ? [scenario] : [];
      if (ids.length + scenarios.length === 0) {
        setError("Select at least one deal (or include the current one).");
        setResult(null);
      } else {
        setResult(await api.consolidatePortfolio(ids, scenarios));
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const t = result?.totals;

  return (
    <div className="portfolio">
      <div className="card">
        <div className="card-head">
          <h2 className="card-title">Fund / Portfolio</h2>
          <div className="sens-toggle">
            <button className="btn tiny" onClick={saveCurrent}>
              Save current deal
            </button>
            <button className="btn" onClick={consolidate} disabled={busy}>
              {busy ? "Consolidating…" : "Consolidate"}
            </button>
          </div>
        </div>

        {error && <div className="banner error">{error}</div>}

        <label className="toggle" style={{ marginBottom: 10 }}>
          <input
            type="checkbox"
            checked={includeCurrent}
            onChange={(e) => setIncludeCurrent(e.target.checked)}
          />
          <span>Include the current deal ({scenario.property?.name})</span>
        </label>

        {saved.length === 0 ? (
          <p className="trad-note">
            No saved deals yet. Click “Save current deal” to add this one, then
            adjust assumptions and save more to build a portfolio.
          </p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>Include</th>
                <th>Saved deal</th>
                <th aria-label="remove" />
              </tr>
            </thead>
            <tbody>
              {saved.map((s) => (
                <tr key={s.id}>
                  <td>
                    <div className="exp-flags">
                      <input
                        type="checkbox"
                        checked={!!selected[s.id]}
                        onChange={(e) =>
                          setSelected((p) => ({ ...p, [s.id]: e.target.checked }))
                        }
                      />
                    </div>
                  </td>
                  <td>{s.name}</td>
                  <td>
                    <button className="btn tiny danger" onClick={() => remove(s.id)}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {t && (
        <>
          <section className="metric-grid">
            <MetricCard label="Portfolio Value" value={currency(t.dcf_value)} hint={`${currency(t.price_per_sf)}/sf`} accent />
            <MetricCard label="Total Cost" value={currency(t.purchase_price)} hint={`${number(t.total_sf)} SF`} />
            <MetricCard label="Blended Going-in Cap" value={percent(t.blended_going_in_cap)} hint={`NOI ${currency(t.year1_noi)}`} />
            <MetricCard label="Portfolio IRR" value={percent(t.portfolio_unlevered_irr)} hint="unlevered" accent />
            <MetricCard label="Equity / Debt" value={currency(t.equity_invested)} hint={`${currency(t.loan_amount)} debt`} />
          </section>

          <section className="card">
            <h2 className="card-title">Assets</h2>
            <div className="table-scroll">
              <table className="proforma">
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Price</th>
                    <th>DCF Value</th>
                    <th>Yr-1 NOI</th>
                    <th>Going-in</th>
                    <th>Unlev IRR</th>
                    <th>Lev IRR</th>
                  </tr>
                </thead>
                <tbody>
                  {result.assets.map((a, i) => (
                    <tr key={i}>
                      <th scope="row">{a.name}</th>
                      <td>{currency(a.price)}</td>
                      <td>{currency(a.dcf_value)}</td>
                      <td>{currency(a.year1_noi)}</td>
                      <td>{percent(a.going_in_cap_rate)}</td>
                      <td>{percent(a.unlevered_irr)}</td>
                      <td>{a.levered_irr == null ? "—" : percent(a.levered_irr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h2 className="card-title">Consolidated Cash Flow</h2>
            <div className="table-scroll">
              <table className="proforma">
                <thead>
                  <tr>
                    <th>Line item</th>
                    {result.years.map((y) => (
                      <th key={y}>{y}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr className="row-bold">
                    <th scope="row">Unlevered Cash Flow</th>
                    {result.consolidated_cash_flow.map((v, i) => (
                      <td key={i}>{currency(v)}</td>
                    ))}
                  </tr>
                  <tr>
                    <th scope="row">Levered Cash Flow</th>
                    {result.consolidated_levered_cash_flow.map((v, i) => (
                      <td key={i}>{currency(v)}</td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
