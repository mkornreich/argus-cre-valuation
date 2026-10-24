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

Modeled after the real ARGUS Enterprise workflow (studied from Altus's feature
documentation and market-leasing references):

- **Monthly engine.** Like ARGUS, the model computes every line on a **monthly**
  axis with exact proration — a lease that commences or expires mid-month,
  fractional downtime from probability weighting, free-rent burn-off and the
  month a TI/LC check is cut are all precise, not rounded to whole years. The UI
  shows either the annual roll-up or the full monthly cash flow.
- **Rent roll** — in-place leases with suite SF, start year/month, term, base
  rent $/SF, annual escalations, free rent, a per-lease reimbursement method,
  optional upfront TI/LC and optional **percentage rent** (retail).
- **Market Leasing Assumptions (MLAs)** — the defining ARGUS feature. When a
  lease rolls (or space starts vacant), it re-leases on a **renewal-probability-
  weighted blend** of "renew" and "new tenant" outcomes, each with its own
  market rent, **term, downtime, free rent, tenant improvements (TI) and leasing
  commissions (LC)**. Space re-leases recursively for the length of the analysis.
- **Absorption & turnover vacancy** — downtime on rollover is an explicit line,
  and general vacancy is netted against it (ARGUS convention) to avoid double
  counting.
- **Reimbursement methods** — each lease recovers operating expenses as **Net**
  (pro-rata share), **Base-Year Stop** (share of the increase over the lease's
  own first twelve months) or **Gross** (none), with optional **occupancy
  gross-up** of variable recoverable expenses and recoverable / non-recoverable
  and fixed / variable expense flags.
- **Operating expenses** — line-item schedule, each on a $/SF or total basis with
  its own growth rate.
- **Leasing & capital costs below NOI** — TI, LC and $/SF capital reserves reduce
  the unlevered cash flow, exactly as in an ARGUS cash flow.
- **Valuation** — going-in cap rate, terminal value from forward (year *N+1*) NOI
  at an exit cap, selling costs, PV of cash flows at the discount rate, NPV vs.
  purchase price, and unlevered IRR / equity multiple.
- **Financing** — sizing by LTV, monthly-amortizing or interest-only debt, DSCR,
  levered IRR, equity multiple and average cash-on-cash.
- **Sensitivity analysis** — a discount-rate × exit-cap grid of DCF value and
  unlevered IRR (ARGUS "what-if").

The proforma is laid out in ARGUS Enterprise order: Potential Base Rent →
Absorption & Turnover Vacancy → Base Rent Abatements → Scheduled Base Rent →
Expense Reimbursements → Total Tenant Revenue → General Vacancy → Effective
Gross Revenue → Operating Expenses → NOI → TI / LC / Capital → Unlevered Cash
Flow → Debt Service → Levered Cash Flow.

The included sample is a 100,000 SF, $28.5M office deal (*Harbor Point Office
Tower*) with three in-place tenants (one on a base-year stop) plus 12,000 SF of
day-one vacancy that leases up under the MLA profile.

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
│       └── components/             assumptions, market leasing, rent roll,
│                                   expenses, results, chart, proforma, sensitivity
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
| GET    | `/api/scenarios`         | List saved scenarios (persisted)     |
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

## Modeling notes

The engine computes the way ARGUS does — monthly, lease-by-lease, with market
leasing assumptions, reimbursement structures, gross-up, percentage rent, and
precise downtime/free-rent/TI/LC timing. Saved scenarios persist to disk.

What is *not* replicated (ARGUS's deeper, mostly enterprise, surface area):
daily (sub-monthly) proration — ARGUS is internally daily, this engine is
monthly; CPI-indexed or stepped rent-review schedules; expense caps/floors and
recovery pools with their own caps; debt tranches, mezzanine and participating
loans; portfolio/fund consolidation; and the traditional (non-DCF) valuation
methods (Term & Reversion, Hardcore, Initial Yield). LC is entered as a % of
total lease rent (one of ARGUS's own options; $/SF and stepped schedules are
not). The engine (`backend/engine.py`) is small, documented and unit-tested
(20 tests), so extending it further is straightforward.
