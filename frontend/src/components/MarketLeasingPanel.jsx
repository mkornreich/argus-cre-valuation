import { NumField } from "./inputs.jsx";

// Market Leasing Assumptions (MLAs) — the ARGUS concept that drives re-leasing
// when a lease rolls: a renewal-probability-weighted blend of "renew" and
// "new tenant" outcomes, each with its own downtime, free rent, TI and LC.
export default function MarketLeasingPanel({ mla, onChange }) {
  const set = (patch) => onChange({ ...mla, ...patch });

  return (
    <section className="panel">
      <h2 className="panel-title">Market Leasing Assumptions</h2>
      <p className="panel-note">
        Applied to space that rolls or starts vacant. Renewal vs. new-tenant
        inputs are blended by the renewal probability.
      </p>

      <div className="field-row">
        <NumField
          label="Renewal probability"
          suffix="%"
          scale={100}
          value={mla.renewal_probability}
          onChange={(v) => set({ renewal_probability: v })}
        />
        <label className="field">
          <span className="field-label">Reimbursement</span>
          <span className="field-input">
            <select
              className="bare-select"
              value={mla.reimbursement_method}
              onChange={(e) => set({ reimbursement_method: e.target.value })}
            >
              <option value="net">Net (NNN)</option>
              <option value="base_stop">Base-year stop</option>
              <option value="gross">Gross</option>
            </select>
          </span>
        </label>
      </div>

      <div className="field-row">
        <NumField
          label="New term"
          suffix="yrs"
          value={mla.market_term_years}
          onChange={(v) => set({ market_term_years: v })}
        />
        <NumField
          label="Renewal term"
          suffix="yrs"
          value={mla.renewal_term_years}
          onChange={(v) => set({ renewal_term_years: v })}
        />
      </div>

      <div className="field-row">
        <NumField
          label="Downtime (new)"
          suffix="mo"
          value={mla.downtime_months}
          onChange={(v) => set({ downtime_months: v })}
        />
        <NumField
          label="Renewal rent"
          prefix="$"
          suffix="/sf"
          value={mla.renewal_market_rent_psf}
          onChange={(v) => set({ renewal_market_rent_psf: v })}
        />
      </div>

      <div className="mla-grid">
        <div className="mla-col-head" />
        <div className="mla-col-head">New</div>
        <div className="mla-col-head">Renewal</div>

        <div className="mla-row-label">TI ($/sf)</div>
        <MlaCell value={mla.new_ti_psf} onChange={(v) => set({ new_ti_psf: v })} />
        <MlaCell value={mla.renewal_ti_psf} onChange={(v) => set({ renewal_ti_psf: v })} />

        <div className="mla-row-label">LC (% of rent)</div>
        <MlaCell value={mla.new_lc_pct} scale={100} onChange={(v) => set({ new_lc_pct: v })} />
        <MlaCell value={mla.renewal_lc_pct} scale={100} onChange={(v) => set({ renewal_lc_pct: v })} />

        <div className="mla-row-label">Free rent (mo)</div>
        <MlaCell value={mla.new_free_rent_months} onChange={(v) => set({ new_free_rent_months: v })} />
        <MlaCell
          value={mla.renewal_free_rent_months}
          onChange={(v) => set({ renewal_free_rent_months: v })}
        />
      </div>
    </section>
  );
}

function MlaCell({ value, onChange, scale = 1 }) {
  const shown = value === null || value === undefined ? "" : value * scale;
  return (
    <input
      className="cell mla-cell"
      type="number"
      step="any"
      value={shown}
      onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value) / scale)}
    />
  );
}
