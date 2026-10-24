import { useState } from "react";
import { currency, percent, multiple } from "../format.js";
import MetricCard from "./MetricCard.jsx";
import CashFlowChart from "./CashFlowChart.jsx";
import CashFlowTable from "./CashFlowTable.jsx";
import SensitivityTable from "./SensitivityTable.jsx";
import TraditionalValuation from "./TraditionalValuation.jsx";

export default function Results({ result, scenario }) {
  const [view, setView] = useState("annual");
  if (!result) return <div className="placeholder">Enter assumptions to value the deal.</div>;

  const m = result.metrics;
  const debt = m.debt;
  const npvPositive = m.npv >= 0;
  const hasMonthly = Array.isArray(result.monthly_cash_flow);
  const proformaRows = view === "monthly" && hasMonthly ? result.monthly_cash_flow : result.cash_flow;

  return (
    <div className="results">
      <div className="results-head">
        <div>
          <h1>{result.property.name}</h1>
          <p className="subhead">
            {result.property.property_type} ·{" "}
            {result.property.total_sf.toLocaleString()} SF ·{" "}
            {scenario.analysis.hold_years}-year hold
          </p>
        </div>
        <div className={`verdict ${npvPositive ? "good" : "bad"}`}>
          <span className="verdict-label">DCF value vs. price</span>
          <span className="verdict-value">
            {npvPositive ? "+" : ""}
            {currency(m.npv)}
          </span>
        </div>
      </div>

      <section className="metric-grid">
        <MetricCard label="DCF Value" value={currency(m.dcf_value)} hint={`${currency(m.dcf_value_per_sf)}/sf`} accent />
        <MetricCard label="Unlevered IRR" value={percent(m.unlevered_irr)} hint={`${multiple(m.equity_multiple_unlevered)} equity multiple`} />
        {debt && (
          <MetricCard label="Levered IRR" value={percent(debt.levered_irr)} hint={`${multiple(debt.equity_multiple_levered)} · ${percent(debt.avg_cash_on_cash)} avg CoC`} accent />
        )}
        <MetricCard label="Year-1 NOI" value={currency(m.year1_noi)} hint={`${percent(m.going_in_cap_rate)} going-in cap`} />
        <MetricCard label="Terminal Value" value={currency(m.terminal_value)} hint={`${percent(m.exit_cap_rate)} exit cap`} />
        {debt ? (
          <MetricCard label="Loan / Equity" value={`${currency(debt.loan_amount)}`} hint={`${percent(debt.ltv_pct, 0)} LTV · DSCR ${debt.dscr_year1 ?? "—"}`} />
        ) : (
          <MetricCard label="Price / SF" value={currency(m.price_per_sf)} hint={`${currency(m.purchase_price)} total`} />
        )}
        <MetricCard label="Leasing & Capital" value={currency(m.total_leasing_capital)} hint="TI + LC + reserves over hold" />
      </section>

      <section className="card">
        <h2 className="card-title">Cash Flow Over Hold</h2>
        <CashFlowChart rows={result.cash_flow} />
      </section>

      <section className="card">
        <div className="card-head">
          <h2 className="card-title">Operating Proforma</h2>
          {hasMonthly && (
            <div className="sens-toggle">
              <button
                className={`chip ${view === "annual" ? "chip-on" : ""}`}
                onClick={() => setView("annual")}
              >
                Annual
              </button>
              <button
                className={`chip ${view === "monthly" ? "chip-on" : ""}`}
                onClick={() => setView("monthly")}
              >
                Monthly
              </button>
            </div>
          )}
        </div>
        <CashFlowTable rows={proformaRows} levered={!!debt} />
      </section>

      {result.traditional_valuation && (
        <section className="card">
          <h2 className="card-title">Traditional Valuation</h2>
          <TraditionalValuation tv={result.traditional_valuation} />
        </section>
      )}

      {result.sensitivity && (
        <section className="card">
          <h2 className="card-title">Sensitivity — Discount Rate × Exit Cap</h2>
          <SensitivityTable sensitivity={result.sensitivity} />
        </section>
      )}
    </div>
  );
}
