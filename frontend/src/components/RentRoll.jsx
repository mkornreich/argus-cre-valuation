// Editable lease rent roll. Each row is one lease; values write straight back
// into the scenario so the valuation re-runs on every keystroke (debounced).

const BLANK_LEASE = {
  tenant: "New Tenant",
  suite_sf: 5000,
  start_year: 1,
  term_years: 5,
  base_rent_psf: 32,
  escalation_type: "fixed",
  annual_escalation_pct: 0.03,
  reimbursement_method: "net",
  free_rent_months: 0,
};

export default function RentRoll({ leases, onChange }) {
  function edit(i, patch) {
    onChange(leases.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }
  const addLease = () => onChange([...leases, { ...BLANK_LEASE }]);
  const removeLease = (i) => onChange(leases.filter((_, idx) => idx !== i));

  const num = (v) => (v === "" ? 0 : Number(v));

  return (
    <section className="panel">
      <h2 className="panel-title">
        Rent Roll
        <button className="btn tiny" onClick={addLease}>
          + Lease
        </button>
      </h2>
      <div className="table-scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>Tenant</th>
              <th>SF</th>
              <th>Start</th>
              <th>Term</th>
              <th>Rent/SF</th>
              <th>Review</th>
              <th>Esc %</th>
              <th>Reimburse</th>
              <th>Free mo</th>
              <th aria-label="remove" />
            </tr>
          </thead>
          <tbody>
            {leases.map((l, i) => (
              <tr key={i}>
                <td>
                  <input
                    className="cell wide"
                    value={l.tenant}
                    onChange={(e) => edit(i, { tenant: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    className="cell"
                    type="number"
                    value={l.suite_sf}
                    onChange={(e) => edit(i, { suite_sf: num(e.target.value) })}
                  />
                </td>
                <td>
                  <input
                    className="cell sm"
                    type="number"
                    value={l.start_year}
                    onChange={(e) =>
                      edit(i, { start_year: num(e.target.value) })
                    }
                  />
                </td>
                <td>
                  <input
                    className="cell sm"
                    type="number"
                    value={l.term_years}
                    onChange={(e) =>
                      edit(i, { term_years: num(e.target.value) })
                    }
                  />
                </td>
                <td>
                  <input
                    className="cell"
                    type="number"
                    step="0.25"
                    value={l.base_rent_psf}
                    onChange={(e) =>
                      edit(i, { base_rent_psf: num(e.target.value) })
                    }
                  />
                </td>
                <td>
                  <select
                    className="cell"
                    value={l.escalation_type || "fixed"}
                    onChange={(e) => edit(i, { escalation_type: e.target.value })}
                    title="Rent review basis"
                  >
                    <option value="fixed">Fixed</option>
                    <option value="cpi">CPI</option>
                    <option value="stepped">Stepped</option>
                  </select>
                </td>
                <td>
                  <input
                    className="cell sm"
                    type="number"
                    step="0.1"
                    disabled={l.escalation_type && l.escalation_type !== "fixed"}
                    value={((l.annual_escalation_pct || 0) * 100).toFixed(2)}
                    onChange={(e) =>
                      edit(i, {
                        annual_escalation_pct: num(e.target.value) / 100,
                      })
                    }
                  />
                </td>
                <td>
                  <select
                    className="cell"
                    value={l.reimbursement_method || "net"}
                    onChange={(e) =>
                      edit(i, { reimbursement_method: e.target.value })
                    }
                  >
                    <option value="net">Net</option>
                    <option value="base_stop">Base stop</option>
                    <option value="gross">Gross</option>
                  </select>
                </td>
                <td>
                  <input
                    className="cell sm"
                    type="number"
                    value={l.free_rent_months || 0}
                    onChange={(e) =>
                      edit(i, { free_rent_months: num(e.target.value) })
                    }
                  />
                </td>
                <td>
                  <button
                    className="btn tiny danger"
                    onClick={() => removeLease(i)}
                    title="Remove lease"
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
            {leases.length === 0 && (
              <tr>
                <td colSpan={10} className="empty">
                  No leases — space is modeled as vacant / re-leased at market.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
