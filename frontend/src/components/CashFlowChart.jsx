import { currencyShort } from "../format.js";

// Inline-SVG chart: NOI as bars, unlevered cash flow as an overlaid line.
// No chart library — just arithmetic over a fixed viewBox.
export default function CashFlowChart({ rows }) {
  const W = 720;
  const H = 260;
  const pad = { top: 20, right: 16, bottom: 28, left: 56 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const values = rows.flatMap((r) => [r.noi, r.unlevered_cash_flow]);
  const maxV = Math.max(...values, 0);
  const minV = Math.min(...values, 0);
  const span = maxV - minV || 1;

  const y = (v) => pad.top + plotH * (1 - (v - minV) / span);
  const n = rows.length;
  const bandW = plotW / n;
  const barW = Math.min(bandW * 0.5, 40);

  const zeroY = y(0);

  // gridlines at 0, mid, max
  const ticks = [minV, (minV + maxV) / 2, maxV];

  const linePts = rows
    .map((r, i) => {
      const cx = pad.left + bandW * i + bandW / 2;
      return `${cx},${y(r.unlevered_cash_flow)}`;
    })
    .join(" ");

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="NOI and cash flow by year">
        {ticks.map((t, i) => (
          <g key={i}>
            <line
              className="grid-line"
              x1={pad.left}
              x2={W - pad.right}
              y1={y(t)}
              y2={y(t)}
            />
            <text className="axis-label" x={pad.left - 8} y={y(t) + 4} textAnchor="end">
              {currencyShort(t)}
            </text>
          </g>
        ))}

        {rows.map((r, i) => {
          const cx = pad.left + bandW * i + bandW / 2;
          const top = y(Math.max(r.noi, 0));
          const h = Math.abs(zeroY - y(r.noi));
          return (
            <g key={i}>
              <rect
                className="bar"
                x={cx - barW / 2}
                y={r.noi >= 0 ? top : zeroY}
                width={barW}
                height={h}
                rx="2"
              >
                <title>
                  {r.year}: NOI {currencyShort(r.noi)}
                </title>
              </rect>
              <text className="axis-label" x={cx} y={H - 8} textAnchor="middle">
                {String(r.year).slice(-2)}
              </text>
            </g>
          );
        })}

        <polyline className="cf-line" points={linePts} fill="none" />
        {rows.map((r, i) => {
          const cx = pad.left + bandW * i + bandW / 2;
          return (
            <circle key={i} className="cf-dot" cx={cx} cy={y(r.unlevered_cash_flow)} r="3">
              <title>
                {r.year}: Cash flow {currencyShort(r.unlevered_cash_flow)}
              </title>
            </circle>
          );
        })}
      </svg>
      <div className="legend">
        <span className="legend-item">
          <span className="swatch bar-swatch" /> Net Operating Income
        </span>
        <span className="legend-item">
          <span className="swatch line-swatch" /> Unlevered Cash Flow
        </span>
      </div>
    </div>
  );
}
