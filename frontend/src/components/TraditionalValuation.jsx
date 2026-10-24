import { currency, percent } from "../format.js";

// Traditional (non-DCF) capitalisation methods alongside the DCF: Net Initial
// Yield, Reversionary Yield and a Term & Reversion value.
export default function TraditionalValuation({ tv }) {
  if (!tv) return null;
  return (
    <div className="trad">
      <div className="trad-yields">
        <div className="trad-stat">
          <span className="trad-label">Net Initial Yield</span>
          <span className="trad-value">{percent(tv.net_initial_yield)}</span>
          <span className="trad-hint">on passing NOI {currency(tv.passing_noi)}</span>
        </div>
        <div className="trad-stat">
          <span className="trad-label">Reversionary Yield</span>
          <span className="trad-value">{percent(tv.reversionary_yield)}</span>
          <span className="trad-hint">on ERV NOI {currency(tv.reversion_noi)}</span>
        </div>
        <div className="trad-stat">
          <span className="trad-label">Equivalent Yield</span>
          <span className="trad-value">{percent(tv.equivalent_yield)}</span>
          <span className="trad-hint">single yield, iteratively solved</span>
        </div>
        <div className="trad-stat">
          <span className="trad-label">Term &amp; Reversion</span>
          <span className="trad-value accent">{currency(tv.term_and_reversion_value)}</span>
          <span className="trad-hint">
            term {currency(tv.term_value)} + reversion {currency(tv.reversion_value)}
          </span>
        </div>
        <div className="trad-stat">
          <span className="trad-label">Hardcore / Layer</span>
          <span className="trad-value">{currency(tv.hardcore_value)}</span>
          <span className="trad-hint">core + top slice at {percent(tv.hardcore_yield)}</span>
        </div>
      </div>
      <p className="trad-note">
        Term income capitalised at {percent(tv.term_yield)} for{" "}
        {tv.years_to_reversion} yrs (WALT); reversion to market rent capitalised at{" "}
        {percent(tv.reversion_yield_used)} and deferred.
      </p>
    </div>
  );
}
