import { useState } from "react";
import { currencyShort, percent } from "../format.js";

// Two-variable sensitivity (ARGUS "what-if"): DCF value or unlevered IRR across
// a grid of discount rate (rows) x exit cap rate (columns). The center cell is
// the base case. Cells are shaded from low (red) to high (green).
export default function SensitivityTable({ sensitivity }) {
  const [metric, setMetric] = useState("dcf_value");
  if (!sensitivity) return null;

  const { discount_rates, exit_cap_rates } = sensitivity;
  const grid = sensitivity[metric];
  const flat = grid.flat().filter((v) => v !== null);
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const mid = Math.floor(discount_rates.length / 2);

  const shade = (v) => {
    if (v === null || max === min) return "transparent";
    const t = (v - min) / (max - min); // 0..1
    const hue = 8 + t * 122; // red(8) -> green(130)
    return `hsl(${hue} 62% 90%)`;
  };
  const fmt = (v) =>
    v === null ? "—" : metric === "dcf_value" ? currencyShort(v) : percent(v, 1);

  return (
    <div>
      <div className="sens-toggle">
        <button
          className={`chip ${metric === "dcf_value" ? "chip-on" : ""}`}
          onClick={() => setMetric("dcf_value")}
        >
          DCF Value
        </button>
        <button
          className={`chip ${metric === "unlevered_irr" ? "chip-on" : ""}`}
          onClick={() => setMetric("unlevered_irr")}
        >
          Unlevered IRR
        </button>
      </div>
      <div className="table-scroll">
        <table className="sens">
          <thead>
            <tr>
              <th className="sens-corner">
                <span>Discount ↓</span>
                <span>Exit cap →</span>
              </th>
              {exit_cap_rates.map((c, j) => (
                <th key={j} className={j === mid ? "sens-base-col" : ""}>
                  {percent(c, 2)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {discount_rates.map((d, i) => (
              <tr key={i}>
                <th className={i === mid ? "sens-base-row" : ""}>{percent(d, 2)}</th>
                {grid[i].map((v, j) => {
                  const base = i === mid && j === mid;
                  return (
                    <td
                      key={j}
                      className={base ? "sens-base" : ""}
                      style={{ background: base ? undefined : shade(v) }}
                    >
                      {fmt(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
