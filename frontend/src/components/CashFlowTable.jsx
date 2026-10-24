import { currency, percent } from "../format.js";

// The year-by-year cash flow, laid out in ARGUS Enterprise order:
// Potential Base Rent -> (Absorption & Turnover Vacancy, Abatements) ->
// Scheduled Base Rent -> + Reimbursements -> Total Tenant Revenue ->
// (General Vacancy) -> EGR -> (Opex) -> NOI -> (TI, LC, Capital) ->
// Unlevered Cash Flow -> (Debt Service) -> Levered Cash Flow.
export default function CashFlowTable({ rows, levered }) {
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
            {rows.map((r) => (
              <th key={r.year} scope="col">
                {r.year}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {line("Potential Base Rent", "potential_base_rent")}
          {line("Absorption & Turnover Vacancy", "absorption_turnover_vacancy", { negative: true, muted: true })}
          {line("Base Rent Abatements", "base_rent_abatements", { negative: true, muted: true })}
          {line("Scheduled Base Rent", "scheduled_base_rent", { bold: true })}
          {line("Expense Reimbursements", "expense_reimbursements")}
          {line("Total Tenant Revenue", "total_tenant_revenue", { bold: true })}
          {line("General Vacancy & Credit Loss", "general_vacancy", { negative: true })}
          {line("Effective Gross Revenue", "effective_gross_revenue", { bold: true })}
          {line("Operating Expenses", "operating_expenses", { negative: true })}
          {line("Net Operating Income", "noi", { bold: true })}
          {line("Tenant Improvements", "tenant_improvements", { negative: true, muted: true })}
          {line("Leasing Commissions", "leasing_commissions", { negative: true, muted: true })}
          {line("Capital Reserve", "capital_reserve", { negative: true, muted: true })}
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
