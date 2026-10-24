import { currency, percent } from "../format.js";

// The year-by-year operating statement — the proforma. Rows are line items,
// columns are years, matching how ARGUS presents a cash flow.
export default function CashFlowTable({ rows, levered }) {
  const years = rows.map((r) => r.year);

  const line = (label, key, { negative = false, bold = false, muted = false } = {}) => (
    <tr className={`${bold ? "row-bold" : ""} ${muted ? "row-muted" : ""}`}>
      <th scope="row">{label}</th>
      {rows.map((r) => (
        <td key={r.year} className={negative && r[key] < 0 ? "neg" : ""}>
          {currency(r[key])}
        </td>
      ))}
    </tr>
  );

  return (
    <div className="table-scroll proforma-wrap">
      <table className="proforma">
        <thead>
          <tr>
            <th scope="col">Line item</th>
            {years.map((yr) => (
              <th key={yr} scope="col">
                {yr}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {line("Base Rental Revenue", "base_rental_revenue")}
          {line("Market Rent (vacant/re-leased)", "market_rent_on_vacant", { muted: true })}
          {line("Expense Reimbursements", "expense_reimbursements")}
          {line("Potential Gross Revenue", "potential_gross_revenue", { bold: true })}
          {line("General Vacancy & Credit Loss", "general_vacancy", { negative: true })}
          {line("Effective Gross Revenue", "effective_gross_revenue", { bold: true })}
          {line("Operating Expenses", "operating_expenses", { negative: true })}
          {line("Net Operating Income", "noi", { bold: true })}
          {line("Capital Reserve", "capital_reserve", { negative: true })}
          {line("Unlevered Cash Flow", "unlevered_cash_flow", { bold: true })}
          {levered && line("Debt Service", "debt_service", { negative: true })}
          {levered && line("Levered Cash Flow", "levered_cash_flow", { bold: true })}
          <tr className="row-muted">
            <th scope="row">Occupancy</th>
            {rows.map((r) => (
              <td key={r.year}>{percent(r.occupancy_pct, 0)}</td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
