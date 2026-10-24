import { Toggle } from "./inputs.jsx";

// Capital stack: any number of debt tranches (senior / mezzanine), each
// interest-only or amortizing, optionally participating in the reversion.
const BLANK_TRANCHE = {
  name: "New Tranche",
  kind: "senior",
  ltv_pct: 0.1,
  interest_rate: 0.08,
  amortization_years: 30,
  io: false,
  participation_pct: 0,
};

export default function DebtTranchesPanel({ debt, onChange }) {
  const tranches = debt.tranches || [];
  const set = (patch) => onChange({ ...debt, ...patch });
  const editT = (i, patch) =>
    set({ tranches: tranches.map((t, idx) => (idx === i ? { ...t, ...patch } : t)) });
  const addT = () => set({ enabled: true, tranches: [...tranches, { ...BLANK_TRANCHE }] });
  const removeT = (i) => set({ tranches: tranches.filter((_, idx) => idx !== i) });
  const num = (v) => (v === "" ? 0 : Number(v));

  return (
    <section className="panel">
      <h2 className="panel-title">
        Capital Stack
        <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Toggle label="Use debt" checked={debt.enabled} onChange={(v) => set({ enabled: v })} />
          <button className="btn tiny" onClick={addT}>
            + Tranche
          </button>
        </span>
      </h2>
      {debt.enabled && (
        <div className="table-scroll">
          <table className="grid">
            <thead>
              <tr>
                <th>Tranche</th>
                <th>Type</th>
                <th>LTV %</th>
                <th>Rate %</th>
                <th>Amort</th>
                <th title="Interest-only">IO</th>
                <th title="Lender participation in reversion">Rev %</th>
                <th title="Lender participation in annual cash flow">CF %</th>
                <th aria-label="remove" />
              </tr>
            </thead>
            <tbody>
              {tranches.map((t, i) => (
                <tr key={i}>
                  <td>
                    <input
                      className="cell wide"
                      value={t.name}
                      onChange={(e) => editT(i, { name: e.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      className="cell"
                      value={t.kind}
                      onChange={(e) => editT(i, { kind: e.target.value })}
                    >
                      <option value="senior">Senior</option>
                      <option value="mezzanine">Mezz</option>
                    </select>
                  </td>
                  <td>
                    <input
                      className="cell sm"
                      type="number"
                      step="1"
                      value={(t.ltv_pct * 100).toFixed(1)}
                      onChange={(e) => editT(i, { ltv_pct: num(e.target.value) / 100, loan_amount: 0 })}
                    />
                  </td>
                  <td>
                    <input
                      className="cell sm"
                      type="number"
                      step="0.05"
                      value={(t.interest_rate * 100).toFixed(2)}
                      onChange={(e) => editT(i, { interest_rate: num(e.target.value) / 100 })}
                    />
                  </td>
                  <td>
                    <input
                      className="cell sm"
                      type="number"
                      value={t.amortization_years}
                      onChange={(e) => editT(i, { amortization_years: num(e.target.value) })}
                    />
                  </td>
                  <td>
                    <div className="exp-flags">
                      <input
                        type="checkbox"
                        checked={!!t.io}
                        onChange={(e) => editT(i, { io: e.target.checked })}
                      />
                    </div>
                  </td>
                  <td>
                    <input
                      className="cell sm"
                      type="number"
                      step="1"
                      value={((t.participation_pct || 0) * 100).toFixed(0)}
                      onChange={(e) => editT(i, { participation_pct: num(e.target.value) / 100 })}
                    />
                  </td>
                  <td>
                    <input
                      className="cell sm"
                      type="number"
                      step="1"
                      value={((t.participation_cf_pct || 0) * 100).toFixed(0)}
                      onChange={(e) => editT(i, { participation_cf_pct: num(e.target.value) / 100 })}
                    />
                  </td>
                  <td>
                    <button className="btn tiny danger" onClick={() => removeT(i)} title="Remove">
                      ×
                    </button>
                  </td>
                </tr>
              ))}
              {tranches.length === 0 && (
                <tr>
                  <td colSpan={9} className="empty">
                    No debt — unlevered analysis. Add a tranche to lever the deal.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
