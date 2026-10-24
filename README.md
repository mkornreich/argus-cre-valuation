# ARGUS — CRE Valuation & DCF

A working re-creation of the core of **ARGUS**: a lease-by-lease commercial
real-estate **discounted-cash-flow (DCF) valuation** tool. Enter a property, its
rent roll, operating expenses and (optionally) debt; the engine projects an
annual cash flow over the hold period and values the asset with a direct-cap
terminal value and a full DCF — returning NOI, cap rates, DCF value, NPV,
unlevered/levered IRR, equity multiples and cash-on-cash.

> Built as **Python / Flask** (financial engine + REST API) and **React / Vite**
> (interactive UI). Figures are illustrative — not investment advice.

![stack](https://img.shields.io/badge/backend-Flask-blue) ![stack](https://img.shields.io/badge/frontend-React%2BVite-success)

---

## What it models

- **Rent roll** — any number of leases, each with suite SF, start year, term,
  base rent $/SF, annual escalations, expense recoveries and free rent.
- **Re-leasing** — space not covered by an in-place lease is re-leased at market
  rent (with growth), so a deal where leases roll before exit still has a
  sensible going-concern value. Turnover/downtime is approximated by a general
  vacancy & credit-loss allowance.
- **Operating expenses** — line-item schedule, each on a $/SF or total basis with
  its own growth rate.
- **Capital reserves** — $/SF reserve with growth.
- **Valuation** — going-in cap rate, terminal value from forward (year *N+1*) NOI
  at an exit cap, selling costs, PV of cash flows at the discount rate, NPV vs.
  purchase price, and unlevered IRR / equity multiple.
- **Financing** — sizing by LTV, monthly-amortizing or interest-only debt, DSCR,
  levered IRR, equity multiple and average cash-on-cash.

The included sample is a 100,000 SF, $28.5M office deal (*Harbor Point Office
Tower*) with four tenants.

## Project layout

```
argussoftware/
├── backend/            Flask API + valuation engine
│   ├── engine.py       Pure-Python DCF model (no numpy) — the core
│   ├── app.py          REST API
│   ├── requirements.txt
│   └── tests/test_engine.py
├── frontend/           React + Vite single-page app
│   └── src/
│       ├── App.jsx                 state, data fetching, layout
│       ├── api.js / format.js
│       └── components/             assumptions, rent roll, expenses, results, chart
└── README.md
```

## Running it

Two processes: the Flask API on **:5001** and the Vite dev server on **:5173**
(Vite proxies `/api` to Flask, so just open the frontend).

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --port 5001
```

### 2. Frontend (in a second terminal)

```bash
cd frontend
npm install
npm run dev
```

Then open **http://localhost:5173**. Edit any assumption, lease or expense and the
valuation re-runs automatically.

### Tests

```bash
cd backend && source .venv/bin/activate && pytest
```

## API

| Method | Path                     | Purpose                              |
|-------:|--------------------------|--------------------------------------|
| GET    | `/api/health`            | Liveness check                       |
| GET    | `/api/sample`            | Default sample scenario              |
| POST   | `/api/analyze`           | Run a valuation on a posted scenario |
| GET    | `/api/scenarios`         | List saved scenarios (in-memory)     |
| POST   | `/api/scenarios`         | Save a scenario                      |
| GET/PUT/DELETE | `/api/scenarios/<id>` | Fetch / update / delete a scenario |

**Analyze example:**

```bash
curl -s localhost:5001/api/sample \
  | curl -s -X POST -H 'Content-Type: application/json' \
         --data-binary @- localhost:5001/api/analyze
```

Returns the property, echoed assumptions, a per-year `cash_flow` proforma and a
`metrics` block (DCF value, cap rates, IRRs, equity multiples, debt metrics).

## Modeling notes & simplifications

This captures the *shape* of an ARGUS analysis, not every feature. Intentional
simplifications: no explicit tenant-improvement / leasing-commission (TI/LC)
cashflows on rollover (approximated via the vacancy allowance), annual rather
than monthly cash-flow periods, recoveries grown at the lease escalator, and an
in-memory scenario store. The engine (`backend/engine.py`) is small, documented
and unit-tested, so extending it (TI/LC, percentage rent, partial-year timing,
a database) is straightforward.
