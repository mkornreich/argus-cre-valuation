// Editable operating-expense schedule. Each line grows at its own rate.

const BLANK_EXPENSE = {
  name: "New Expense",
  amount: 1.0,
  basis: "psf",
  growth_pct: 0.03,
  recoverable: true,
  variable: true,
};

export default function ExpensesTable({ expenses, totalSf, onChange }) {
  function edit(i, patch) {
    onChange(expenses.map((e, idx) => (idx === i ? { ...e, ...patch } : e)));
  }
  const add = () => onChange([...expenses, { ...BLANK_EXPENSE }]);
  const remove = (i) => onChange(expenses.filter((_, idx) => idx !== i));
  const num = (v) => (v === "" ? 0 : Number(v));

  const totalPsf = expenses.reduce(
    (sum, e) => sum + (e.basis === "psf" ? e.amount : e.amount / (totalSf || 1)),
    0
  );

  return (
    <section className="panel">
      <h2 className="panel-title">
        Operating Expenses
        <button className="btn tiny" onClick={add}>
          + Expense
        </button>
      </h2>
      <div className="table-scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>Expense</th>
              <th>Amount</th>
              <th>Basis</th>
              <th>Growth %</th>
              <th title="Recoverable from tenants">Rec</th>
              <th title="Variable (occupancy-sensitive) — grossed up">Var</th>
              <th aria-label="remove" />
            </tr>
          </thead>
          <tbody>
            {expenses.map((e, i) => (
              <tr key={i}>
                <td>
                  <input
                    className="cell wide"
                    value={e.name}
                    onChange={(ev) => edit(i, { name: ev.target.value })}
                  />
                </td>
                <td>
                  <input
                    className="cell"
                    type="number"
                    step="0.05"
                    value={e.amount}
                    onChange={(ev) => edit(i, { amount: num(ev.target.value) })}
                  />
                </td>
                <td>
                  <select
                    className="cell"
                    value={e.basis}
                    onChange={(ev) => edit(i, { basis: ev.target.value })}
                  >
                    <option value="psf">$/sf</option>
                    <option value="total">total $</option>
                  </select>
                </td>
                <td>
                  <input
                    className="cell sm"
                    type="number"
                    step="0.1"
                    value={(e.growth_pct * 100).toFixed(2)}
                    onChange={(ev) =>
                      edit(i, { growth_pct: num(ev.target.value) / 100 })
                    }
                  />
                </td>
                <td>
                  <div className="exp-flags">
                    <input
                      type="checkbox"
                      checked={e.recoverable !== false}
                      onChange={(ev) => edit(i, { recoverable: ev.target.checked })}
                      title="Recoverable"
                    />
                  </div>
                </td>
                <td>
                  <div className="exp-flags">
                    <input
                      type="checkbox"
                      checked={e.variable !== false}
                      onChange={(ev) => edit(i, { variable: ev.target.checked })}
                      title="Variable"
                    />
                  </div>
                </td>
                <td>
                  <button
                    className="btn tiny danger"
                    onClick={() => remove(i)}
                    title="Remove expense"
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel-foot">
        Year-1 operating expenses ≈ <strong>${totalPsf.toFixed(2)}/sf</strong>
      </div>
    </section>
  );
}
