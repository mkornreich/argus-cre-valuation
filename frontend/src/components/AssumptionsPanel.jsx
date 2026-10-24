import { NumField, TextField } from "./inputs.jsx";

export default function AssumptionsPanel({ scenario, onChange }) {
  const { property, analysis, capital } = scenario;

  const setProperty = (patch) =>
    onChange({ property: { ...property, ...patch } });
  const setAnalysis = (patch) =>
    onChange({ analysis: { ...analysis, ...patch } });
  const setCapital = (patch) => onChange({ capital: { ...capital, ...patch } });

  return (
    <section className="panel">
      <h2 className="panel-title">Property &amp; Assumptions</h2>

      <TextField
        label="Property name"
        value={property.name}
        onChange={(v) => setProperty({ name: v })}
      />
      <div className="field-row">
        <TextField
          label="Type"
          value={property.property_type}
          onChange={(v) => setProperty({ property_type: v })}
        />
        <NumField
          label="Total SF"
          value={property.total_sf}
          onChange={(v) => setProperty({ total_sf: v })}
          min="0"
        />
      </div>

      <div className="field-row">
        <NumField
          label="Purchase price"
          prefix="$"
          value={analysis.purchase_price}
          onChange={(v) => setAnalysis({ purchase_price: v })}
          min="0"
        />
        <NumField
          label="Hold period"
          suffix="yrs"
          value={analysis.hold_years}
          onChange={(v) => setAnalysis({ hold_years: Math.round(v) })}
          step="1"
          min="1"
        />
      </div>
      <div className="field-row">
        <NumField
          label="Start year"
          value={analysis.start_year}
          onChange={(v) => setAnalysis({ start_year: Math.round(v) })}
          step="1"
        />
        <NumField
          label="Start month"
          value={analysis.start_month}
          onChange={(v) => setAnalysis({ start_month: Math.round(v) })}
          step="1"
          min="1"
        />
      </div>
      <div className="field-row">
        <NumField
          label="Discount rate"
          suffix="%"
          scale={100}
          value={analysis.discount_rate}
          onChange={(v) => setAnalysis({ discount_rate: v })}
        />
        <NumField
          label="Expense gross-up"
          suffix="%"
          scale={100}
          value={analysis.expense_gross_up_pct}
          onChange={(v) => setAnalysis({ expense_gross_up_pct: v })}
        />
      </div>
      <div className="field-row">
        <NumField
          label="Exit cap rate"
          suffix="%"
          scale={100}
          value={analysis.exit_cap_rate}
          onChange={(v) => setAnalysis({ exit_cap_rate: v })}
        />
        <NumField
          label="Selling cost"
          suffix="%"
          scale={100}
          value={analysis.selling_cost_pct}
          onChange={(v) => setAnalysis({ selling_cost_pct: v })}
        />
      </div>
      <div className="field-row">
        <NumField
          label="Gen. vacancy"
          suffix="%"
          scale={100}
          value={analysis.general_vacancy_pct}
          onChange={(v) => setAnalysis({ general_vacancy_pct: v })}
        />
        <NumField
          label="Market rent"
          prefix="$"
          suffix="/sf"
          value={analysis.market_rent_psf}
          onChange={(v) => setAnalysis({ market_rent_psf: v })}
        />
      </div>
      <div className="field-row">
        <NumField
          label="Mkt rent growth"
          suffix="%"
          scale={100}
          value={analysis.market_rent_growth_pct}
          onChange={(v) => setAnalysis({ market_rent_growth_pct: v })}
        />
        <NumField
          label="Cap reserve"
          prefix="$"
          suffix="/sf"
          value={capital.reserve_psf}
          onChange={(v) => setCapital({ reserve_psf: v })}
        />
      </div>
    </section>
  );
}
