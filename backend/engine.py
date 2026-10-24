"""ARGUS-style commercial real estate DCF valuation engine (v4 — daily).

ARGUS Enterprise runs an internally *daily* cash-flow engine. This module does
the same: every lease, expense, reimbursement, rollover, downtime period,
free-rent abatement and capital cost is accrued on a day grid and rolled up to
months and financial years. On top of the daily core it implements the broader
ARGUS feature surface:

* **Daily proration.** A 365.25-day year; fractional downtime, mid-period lease
  commencements and free-rent burn-off are exact to the day.
* **Rent reviews.** Fixed escalations, **CPI indexation**, or an explicit
  **stepped** rent schedule per lease.
* **Reimbursements.** Net / Base-Year Stop / Gross with occupancy gross-up,
  recoverable vs. non-recoverable and fixed vs. variable expense pools, an
  **annual cap** on recoverable-expense growth, an **expense stop ($/SF)** and an
  **admin fee** on recoveries.
* **Market Leasing Assumptions.** Renewal-probability-weighted re-leasing with
  separate renewal rent/term, downtime, free rent, TI and LC.
* **Leasing commissions** as a percent of lease rent **or $/SF**.
* **Percentage rent** over a natural or specified breakpoint.
* **Debt.** Multiple **tranches** (senior / mezzanine), each interest-only or
  amortizing, plus **participating** loans (a lender share of net reversion).
* **Valuation.** DCF (NPV, unlevered/levered IRR, equity multiples) and the
  **traditional methods** — Net Initial Yield, Reversionary Yield, and a Term &
  Reversion capitalisation.
* **Sensitivity** across a discount-rate x exit-cap grid (reuses one projection).
* **Portfolio consolidation** (see ``consolidate``).

All money is in whole dollars; all rates are decimals (0.08 == 8%).
"""

from __future__ import annotations

from typing import Any

DPY = 365.25                 # days per year
DPM = 365.25 / 12.0          # days per month


# --------------------------------------------------------------------------- #
# Financial helpers
# --------------------------------------------------------------------------- #

def npv(rate: float, cash_flows: list[float]) -> float:
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cash_flows))


def irr(cash_flows: list[float], lo: float = -0.9999, hi: float = 10.0) -> float | None:
    if not cash_flows or all(cf >= 0 for cf in cash_flows) or all(cf <= 0 for cf in cash_flows):
        return None
    f_lo, f_hi = npv(lo, cash_flows), npv(hi, cash_flows)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if (f_lo > 0) == (f_hi > 0):
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid, cash_flows)
        if abs(f_mid) < 1e-6:
            return mid
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def annuity_pv(rate: float, n_years: float) -> float:
    """Present value of $1/year for ``n_years`` at ``rate`` (years' purchase)."""
    if rate == 0:
        return n_years
    return (1 - (1 + rate) ** (-n_years)) / rate


def _mortgage_schedule(principal: float, annual_rate: float, amort_years: int,
                       hold_years: int, interest_only: bool) -> dict[str, Any]:
    if principal <= 0:
        return {"annual_debt_service": [0.0] * hold_years, "annual_interest": [0.0] * hold_years,
                "annual_principal": [0.0] * hold_years, "ending_balance": 0.0, "monthly_payment": 0.0}
    mr = annual_rate / 12.0
    balance = principal
    if interest_only or amort_years <= 0:
        mp = balance * mr
        return {"annual_debt_service": [mp * 12 for _ in range(hold_years)],
                "annual_interest": [balance * annual_rate for _ in range(hold_years)],
                "annual_principal": [0.0] * hold_years, "ending_balance": principal, "monthly_payment": mp}
    n = amort_years * 12
    mp = principal / n if mr == 0 else principal * mr / (1 - (1 + mr) ** (-n))
    per_int, per_prin, per_ds = [], [], []
    for _ in range(hold_years):
        yi = yp = 0.0
        for _m in range(12):
            interest = balance * mr
            pp = min(mp - interest, balance)
            balance -= pp
            yi += interest
            yp += pp
        per_int.append(yi)
        per_prin.append(yp)
        per_ds.append(yi + yp)
    return {"annual_debt_service": per_ds, "annual_interest": per_int, "annual_principal": per_prin,
            "ending_balance": max(balance, 0.0), "monthly_payment": mp}


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "")
    return bool(value)


_REIMB = ("net", "base_stop", "gross")


def _reimb_method(value: Any, default: str = "net") -> str:
    v = str(value or default).lower().replace("-", "_").replace(" ", "_")
    return v if v in _REIMB else default


def _esc_type(value: Any, default: str = "fixed") -> str:
    v = str(value or default).lower()
    return v if v in ("fixed", "cpi", "stepped") else default


def _percentage_rent(pr: Any) -> dict | None:
    if not pr:
        return None
    pr = dict(pr)
    sales, pct = _num(pr.get("sales_psf")), _num(pr.get("percent"))
    if sales <= 0 or pct <= 0:
        return None
    return {"sales_psf": sales, "percent": pct, "breakpoint_psf": _num(pr.get("breakpoint_psf")),
            "sales_growth_pct": _num(pr.get("sales_growth_pct"))}


def _rent_steps(steps: Any) -> list[dict]:
    out = []
    for s in steps or []:
        s = dict(s)
        out.append({"lease_year": max(int(_num(s.get("lease_year"), 1)), 1),
                    "rent_psf": _num(s.get("rent_psf"), 0.0)})
    out.sort(key=lambda s: s["lease_year"])
    return out


def _recovery(rec: Any) -> dict:
    rec = dict(rec or {})
    return {
        "cap_pct": _num(rec.get("cap_pct"), 0.0),          # 0 -> no cap on growth
        "stop_psf": _num(rec.get("stop_psf"), 0.0),        # expense stop $/SF
        "admin_fee_pct": _num(rec.get("admin_fee_pct"), 0.0),
    }


def _tranche(t: dict, default_name: str) -> dict:
    return {
        "name": str(t.get("name") or default_name),
        "kind": "mezzanine" if str(t.get("kind", "")).lower().startswith("mezz") else "senior",
        "ltv_pct": _num(t.get("ltv_pct"), 0.0),
        "loan_amount": _num(t.get("loan_amount"), 0.0),
        "interest_rate": _num(t.get("interest_rate"), 0.065),
        "amortization_years": int(_num(t.get("amortization_years"), 30)),
        "io": _bool(t.get("io"), False),
        "participation_pct": _num(t.get("participation_pct"), 0.0),  # lender share of net reversion
    }


def _normalize_debt(debt: dict) -> dict:
    debt = dict(debt or {})
    enabled = _bool(debt.get("enabled"), False)
    tranches = debt.get("tranches")
    if tranches:
        norm = [_tranche(dict(t), f"Tranche {i + 1}") for i, t in enumerate(tranches)]
    elif enabled or debt.get("ltv_pct") or debt.get("loan_amount"):
        norm = [_tranche(debt, "Senior Loan")]  # legacy single-loan form
    else:
        norm = []
    return {"enabled": enabled and bool(norm), "tranches": norm}


def normalize_scenario(scenario: dict | None) -> dict:
    scenario = dict(scenario or {})
    prop = dict(scenario.get("property", {}))
    ana = dict(scenario.get("analysis", {}))
    cap = dict(scenario.get("capital", {}))
    mla = dict(scenario.get("market_leasing", {}))
    val = dict(scenario.get("valuation", {}))

    norm = {
        "property": {
            "name": str(prop.get("name") or "Untitled Property"),
            "property_type": str(prop.get("property_type") or "Office"),
            "total_sf": max(_num(prop.get("total_sf"), 1.0), 1.0),
        },
        "analysis": {
            "start_year": int(_num(ana.get("start_year"), 2026)),
            "start_month": min(max(int(_num(ana.get("start_month"), 1)), 1), 12),
            "hold_years": max(int(_num(ana.get("hold_years"), 10)), 1),
            "purchase_price": _num(ana.get("purchase_price"), 0.0),
            "discount_rate": _num(ana.get("discount_rate"), 0.08),
            "exit_cap_rate": _num(ana.get("exit_cap_rate"), 0.065),
            "selling_cost_pct": _num(ana.get("selling_cost_pct"), 0.02),
            "general_vacancy_pct": _num(ana.get("general_vacancy_pct"), 0.05),
            "market_rent_psf": _num(ana.get("market_rent_psf"), 0.0),
            "market_rent_growth_pct": _num(ana.get("market_rent_growth_pct"), 0.03),
            "expense_gross_up_pct": _num(ana.get("expense_gross_up_pct"), 0.0),
            "cpi_rate": _num(ana.get("cpi_rate"), 0.025),
        },
        "market_leasing": {
            "renewal_probability": min(max(_num(mla.get("renewal_probability"), 0.65), 0.0), 1.0),
            "market_term_years": max(_num(mla.get("market_term_years"), 5.0), 0.5),
            "renewal_term_years": max(_num(mla.get("renewal_term_years"),
                                            _num(mla.get("market_term_years"), 5.0)), 0.5),
            "downtime_months": max(_num(mla.get("downtime_months"), 9.0), 0.0),
            "renewal_market_rent_psf": _num(mla.get("renewal_market_rent_psf"), 0.0),
            "new_free_rent_months": max(_num(mla.get("new_free_rent_months"), 4.0), 0.0),
            "renewal_free_rent_months": max(_num(mla.get("renewal_free_rent_months"), 1.0), 0.0),
            "new_ti_psf": max(_num(mla.get("new_ti_psf"), 35.0), 0.0),
            "renewal_ti_psf": max(_num(mla.get("renewal_ti_psf"), 12.0), 0.0),
            "new_lc_pct": max(_num(mla.get("new_lc_pct"), 0.06), 0.0),
            "renewal_lc_pct": max(_num(mla.get("renewal_lc_pct"), 0.03), 0.0),
            "lc_basis": "psf" if str(mla.get("lc_basis", "percent")).lower() == "psf" else "percent",
            "reimbursement_method": _reimb_method(mla.get("reimbursement_method"), "net"),
            "recovery": _recovery(mla.get("recovery")),
        },
        "valuation": {
            "term_yield": _num(val.get("term_yield"), 0.0),       # 0 -> default to going-in cap
            "reversion_yield": _num(val.get("reversion_yield"), 0.0),  # 0 -> default to exit cap
        },
        "leases": [],
        "expenses": [],
        "capital": {"reserve_psf": _num(cap.get("reserve_psf"), 0.0),
                    "growth_pct": _num(cap.get("growth_pct"), 0.02)},
        "debt": _normalize_debt(scenario.get("debt", {})),
    }

    for lease in scenario.get("leases", []) or []:
        lease = dict(lease)
        norm["leases"].append({
            "tenant": str(lease.get("tenant") or "Tenant"),
            "suite_sf": max(_num(lease.get("suite_sf"), 0.0), 0.0),
            "start_year": max(int(_num(lease.get("start_year"), 1)), 1),
            "start_month": min(max(int(_num(lease.get("start_month"), 1)), 1), 12),
            "term_years": max(_num(lease.get("term_years"), 1.0), 0.1),
            "base_rent_psf": _num(lease.get("base_rent_psf"), 0.0),
            "escalation_type": _esc_type(lease.get("escalation_type"), "fixed"),
            "annual_escalation_pct": _num(lease.get("annual_escalation_pct"), 0.0),
            "cpi_rate": _num(lease.get("cpi_rate"), 0.0),       # 0 -> use analysis cpi_rate
            "rent_steps": _rent_steps(lease.get("rent_steps")),
            "free_rent_months": max(_num(lease.get("free_rent_months"), 0.0), 0.0),
            "ti_psf": max(_num(lease.get("ti_psf"), 0.0), 0.0),
            "lc_pct": max(_num(lease.get("lc_pct"), 0.0), 0.0),
            "lc_basis": "psf" if str(lease.get("lc_basis", "percent")).lower() == "psf" else "percent",
            "reimbursement_method": _reimb_method(lease.get("reimbursement_method"), "net"),
            "recovery": _recovery(lease.get("recovery")),
            "percentage_rent": _percentage_rent(lease.get("percentage_rent")),
        })

    for exp in scenario.get("expenses", []) or []:
        exp = dict(exp)
        basis = str(exp.get("basis") or "psf").lower()
        norm["expenses"].append({
            "name": str(exp.get("name") or "Expense"),
            "amount": _num(exp.get("amount"), 0.0),
            "basis": basis if basis in ("psf", "total") else "psf",
            "growth_pct": _num(exp.get("growth_pct"), 0.0),
            "recoverable": _bool(exp.get("recoverable"), True),
            "variable": _bool(exp.get("variable"), True),
        })

    return norm


# --------------------------------------------------------------------------- #
# Lease segments (day-offset axis)
# --------------------------------------------------------------------------- #

def _build_segments(inplace: dict | None, mla: dict, analysis: dict, horizon_d: float) -> list[dict]:
    p = mla["renewal_probability"]
    mkt0 = analysis["market_rent_psf"]
    renewal_mkt0 = mla["renewal_market_rent_psf"] or mkt0
    mg = analysis["market_rent_growth_pct"]

    down_eff_d = (1 - p) * mla["downtime_months"] * DPM
    free_eff_d = (p * mla["renewal_free_rent_months"] + (1 - p) * mla["new_free_rent_months"]) * DPM
    ti_eff = p * mla["renewal_ti_psf"] + (1 - p) * mla["new_ti_psf"]
    lc_eff = p * mla["renewal_lc_pct"] + (1 - p) * mla["new_lc_pct"]
    term_eff_d = (p * mla["renewal_term_years"] + (1 - p) * mla["market_term_years"]) * DPY
    blended_rent0 = p * renewal_mkt0 + (1 - p) * mkt0

    segs: list[dict] = []
    if inplace:
        start_d = ((inplace["start_year"] - 1) * 12 + (inplace["start_month"] - 1)) * DPM
        term_d = inplace["term_years"] * DPY
        segs.append({
            "start_d": start_d, "end_d": start_d + term_d, "term_d": term_d, "down_before_d": 0.0,
            "rent_psf0": inplace["base_rent_psf"], "esc": inplace["annual_escalation_pct"],
            "esc_type": inplace["escalation_type"],
            "cpi": inplace["cpi_rate"] or analysis["cpi_rate"], "rent_steps": inplace["rent_steps"],
            "is_inplace": True, "free_d": inplace["free_rent_months"] * DPM,
            "ti_psf": inplace["ti_psf"], "lc": inplace["lc_pct"], "lc_basis": inplace["lc_basis"],
            "reimb": inplace["reimbursement_method"], "recovery": inplace["recovery"],
            "percentage_rent": inplace["percentage_rent"],
        })
        next_start = start_d + term_d + down_eff_d
    else:
        next_start = down_eff_d

    while next_start < horizon_d and term_eff_d > 0:
        rent0 = blended_rent0 * (1 + mg) ** (next_start / DPY)
        segs.append({
            "start_d": next_start, "end_d": next_start + term_eff_d, "term_d": term_eff_d,
            "down_before_d": down_eff_d, "rent_psf0": rent0, "esc": mg, "esc_type": "fixed",
            "cpi": 0.0, "rent_steps": [], "is_inplace": False, "free_d": free_eff_d,
            "ti_psf": ti_eff, "lc": lc_eff, "lc_basis": mla["lc_basis"],
            "reimb": mla["reimbursement_method"], "recovery": mla["recovery"],
            "percentage_rent": None,
        })
        next_start += term_eff_d + down_eff_d
    return segs


def _seg_rent_psf(seg: dict, d: float) -> float:
    """Face rent $/SF for a segment on day offset ``d`` (fixed / CPI / stepped)."""
    years_in = (d - seg["start_d"]) / DPY
    whole_years = int(years_in + 1e-9)
    if seg["esc_type"] == "stepped" and seg["rent_steps"]:
        rate = seg["rent_steps"][0]["rent_psf"]
        for step in seg["rent_steps"]:
            if step["lease_year"] <= whole_years + 1:
                rate = step["rent_psf"]
        return rate
    if seg["esc_type"] == "cpi":
        return seg["rent_psf0"] * (1 + seg["cpi"]) ** whole_years
    return seg["rent_psf0"] * (1 + seg["esc"]) ** whole_years


def _seg_lc_amount(seg: dict, suite_sf: float) -> float:
    if seg["lc_basis"] == "psf":
        return seg["lc"] * suite_sf
    return seg["lc"] * (suite_sf * seg["rent_psf0"] * seg["term_d"] / DPY)


# --------------------------------------------------------------------------- #
# Expenses (annual, by financial year)
# --------------------------------------------------------------------------- #

def _annual_expenses(expenses: list[dict], total_sf: float, fy: int) -> dict[str, Any]:
    detail: dict[str, float] = {}
    total = rec_fixed = rec_variable = 0.0
    for e in expenses:
        base = e["amount"] * total_sf if e["basis"] == "psf" else e["amount"]
        amt = base * (1 + e["growth_pct"]) ** fy
        detail[e["name"]] = amt
        total += amt
        if e["recoverable"]:
            if e["variable"]:
                rec_variable += amt
            else:
                rec_fixed += amt
    return {"detail": detail, "total": total, "rec_fixed": rec_fixed, "rec_variable": rec_variable}


# --------------------------------------------------------------------------- #
# Daily projection
# --------------------------------------------------------------------------- #

def _build_spaces(scenario: dict, horizon_d: float) -> list[dict]:
    total_sf = scenario["property"]["total_sf"]
    mla, ana = scenario["market_leasing"], scenario["analysis"]
    spaces = [{"suite_sf": l["suite_sf"], "segments": _build_segments(l, mla, ana, horizon_d)}
              for l in scenario["leases"]]
    vacant = max(total_sf - sum(l["suite_sf"] for l in scenario["leases"]), 0.0)
    if vacant > 0.5 and ana["market_rent_psf"] > 0:
        spaces.append({"suite_sf": vacant, "segments": _build_segments(None, mla, ana, horizon_d)})
    return spaces


_SUM_FIELDS = (
    "potential_base_rent", "absorption_turnover_vacancy", "base_rent_abatements",
    "scheduled_base_rent", "percentage_rent", "expense_reimbursements",
    "total_tenant_revenue", "general_vacancy", "effective_gross_revenue",
    "operating_expenses", "noi", "tenant_improvements", "leasing_commissions",
    "capital_reserve", "unlevered_cash_flow",
)


def _project(scenario: dict) -> dict:
    """Daily accrual rolled up to financial years (and months). One pass."""
    ana = scenario["analysis"]
    hold = ana["hold_years"]
    total_sf = scenario["property"]["total_sf"]
    exp = scenario["expenses"]
    gross_up = ana["expense_gross_up_pct"]
    gen_vac = ana["general_vacancy_pct"]
    reserve_psf = scenario["capital"]["reserve_psf"]
    reserve_growth = scenario["capital"]["growth_pct"]
    mkt0, mg = ana["market_rent_psf"], ana["market_rent_growth_pct"]

    n_years = hold + 1
    total_days = int(round(n_years * DPY))
    horizon_d = float(total_days)
    spaces = _build_spaces(scenario, horizon_d)

    # Precompute annual expense pools per financial year.
    exp_year = [_annual_expenses(exp, total_sf, fy) for fy in range(n_years)]

    # Blank annual and monthly accumulators.
    def blank():
        return {f: 0.0 for f in _SUM_FIELDS} | {"occ_days": 0.0, "days": 0}
    annual = [blank() for _ in range(n_years)]
    monthly = [blank() for _ in range(hold * 12 + 1)]

    for d in range(total_days):
        fy = min(int(d / DPY), n_years - 1)
        mo = int(d / DPM)
        ey = exp_year[fy]
        day_opex = ey["total"] / DPY
        mkt_psf_day = mkt0 * (1 + mg) ** (d / DPY)

        potential = turnover = abate = ti = lc = pct_rent = occ_sf = 0.0
        reimb = 0.0

        # Occupancy first (needed for gross-up).
        occ_today = 0.0
        active = []  # (space, seg)
        for sp in spaces:
            seg = next((s for s in sp["segments"] if s["start_d"] <= d < s["end_d"]), None)
            if seg is not None:
                occ_sf += sp["suite_sf"]
                occ_today += sp["suite_sf"]
                active.append((sp, seg))
        occupancy = min(occ_today / total_sf, 1.0) if total_sf else 0.0

        gu_factor = (gross_up / occupancy) if (gross_up > 0 and 0 < occupancy < gross_up) else 1.0
        rec_pool_day = (ey["rec_fixed"] + ey["rec_variable"] * gu_factor) / DPY

        for sp, seg in active:
            suite = sp["suite_sf"]
            rent_psf = _seg_rent_psf(seg, d)
            day_rent = suite * rent_psf / DPY
            potential += day_rent
            if seg["start_d"] <= d < seg["start_d"] + seg["free_d"]:
                abate += day_rent

            pr = seg["percentage_rent"]
            if pr:
                yrs = (d - seg["start_d"]) / DPY
                sales = pr["sales_psf"] * (1 + pr["sales_growth_pct"]) ** int(yrs)
                bp = pr["breakpoint_psf"] or (rent_psf / pr["percent"] if pr["percent"] else 0.0)
                pct_rent += suite * max(sales - bp, 0.0) * pr["percent"] / DPY

            # Reimbursement (net / base-year stop) with cap, stop, admin fee.
            method = seg["reimb"]
            if method != "gross":
                share = suite / total_sf if total_sf else 0.0
                rec = seg["recovery"]
                pool = rec_pool_day
                base_fy = min(max(int(seg["start_d"] / DPY), 0), n_years - 1)
                if method == "base_stop":
                    base_pool = (exp_year[base_fy]["rec_fixed"]
                                 + exp_year[base_fy]["rec_variable"] * gu_factor) / DPY
                    recoverable = max(pool - base_pool, 0.0)
                else:
                    recoverable = pool
                if rec["cap_pct"] > 0:  # cap growth of the pool since the base year
                    base_pool_full = (exp_year[base_fy]["rec_fixed"]
                                      + exp_year[base_fy]["rec_variable"]) / DPY
                    capped = base_pool_full * (1 + rec["cap_pct"]) ** (fy - base_fy)
                    recoverable = min(recoverable, max(capped, 0.0))
                tenant_reimb = share * recoverable
                if rec["stop_psf"] > 0:  # expense stop $/SF/yr
                    tenant_reimb = max(tenant_reimb - rec["stop_psf"] * suite / DPY, 0.0)
                reimb += tenant_reimb * (1 + rec["admin_fee_pct"])

        # Turnover vacancy: a space sitting in a segment's downtime window earns
        # no rent; the forgone market rent is the absorption & turnover vacancy.
        if occ_today < total_sf - 0.5:
            for sp in spaces:
                for seg in sp["segments"]:
                    if (seg["start_d"] - seg["down_before_d"]) <= d < seg["start_d"]:
                        lost = sp["suite_sf"] * mkt_psf_day / DPY
                        potential += lost
                        turnover += lost

        # TI / LC land on the commencement day of each segment.
        for sp in spaces:
            for seg in sp["segments"]:
                if int(seg["start_d"]) == d and seg["start_d"] >= 0:
                    ti += sp["suite_sf"] * seg["ti_psf"]
                    lc += _seg_lc_amount(seg, sp["suite_sf"])

        scheduled = potential - turnover - abate
        ttr = scheduled + reimb + pct_rent
        general_vacancy = -max(gen_vac * potential - turnover, 0.0)
        egr = ttr + general_vacancy
        noi = egr - day_opex
        reserve = total_sf * reserve_psf * (1 + reserve_growth) ** fy / DPY
        ucf = noi - ti - lc - reserve

        vals = {
            "potential_base_rent": potential, "absorption_turnover_vacancy": -turnover,
            "base_rent_abatements": -abate, "scheduled_base_rent": scheduled,
            "percentage_rent": pct_rent, "expense_reimbursements": reimb,
            "total_tenant_revenue": ttr, "general_vacancy": general_vacancy,
            "effective_gross_revenue": egr, "operating_expenses": -day_opex, "noi": noi,
            "tenant_improvements": -ti, "leasing_commissions": -lc, "capital_reserve": -reserve,
            "unlevered_cash_flow": ucf,
        }
        for bucket in (annual[fy], monthly[mo] if mo < len(monthly) else None):
            if bucket is None:
                continue
            for f in _SUM_FIELDS:
                bucket[f] += vals[f]
            bucket["occ_days"] += occupancy
            bucket["days"] += 1

    return {"annual": annual, "monthly": monthly, "exp_year": exp_year,
            "total_sf": total_sf, "hold": hold, "start_year": ana["start_year"],
            "start_month": ana["start_month"]}


def _label_annual(annual: list[dict], exp_year: list[dict], start_year: int, hold: int) -> list[dict]:
    rows = []
    for y in range(hold):
        a = annual[y]
        row = {"year_index": y + 1, "year": start_year + y}
        for f in _SUM_FIELDS:
            row[f] = round(a[f], 2)
        row["occupancy_pct"] = round(a["occ_days"] / a["days"], 4) if a["days"] else 0.0
        row["operating_expenses_detail"] = {k: round(-v, 2) for k, v in exp_year[y]["detail"].items()}
        row["_noi"] = a["noi"]
        row["_unlevered_cf"] = a["unlevered_cash_flow"]
        rows.append(row)
    return rows


def _label_monthly(monthly: list[dict], start_year: int, start_month: int, hold: int) -> list[dict]:
    rows = []
    for mo in range(hold * 12):
        a = monthly[mo]
        if not a["days"]:
            continue
        month0 = (start_month - 1) + mo
        row = {"year": start_year + month0 // 12, "month": month0 % 12 + 1}
        row["period"] = f"{row['year']}-{row['month']:02d}"
        for f in _SUM_FIELDS:
            row[f] = round(a[f], 2)
        row["occupancy_pct"] = round(a["occ_days"] / a["days"], 4)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Valuation (DCF + traditional) with sensitivity reuse
# --------------------------------------------------------------------------- #

def _dcf(flows: list[float], forward_noi: float, price: float, discount: float,
         exit_cap: float, selling_cost: float, hold: int) -> dict:
    terminal = forward_noi / exit_cap if exit_cap > 0 else 0.0
    net_reversion = terminal * (1 - selling_cost)
    pv_ops = sum(cf / (1 + discount) ** (i + 1) for i, cf in enumerate(flows))
    dcf_value = pv_ops + net_reversion / (1 + discount) ** hold
    rev_flows = flows[:]
    rev_flows[-1] += net_reversion
    unlevered_irr = irr([-price] + rev_flows) if price > 0 else None
    return {"terminal_value": terminal, "net_reversion": net_reversion, "dcf_value": dcf_value,
            "unlevered_irr": unlevered_irr, "rev_flows": rev_flows}


def _traditional_valuation(scenario: dict, projection: list[dict], price: float,
                           forward_noi: float) -> dict:
    """Net Initial Yield, Reversionary Yield, and a Term & Reversion value."""
    ana, val = scenario["analysis"], scenario["valuation"]
    total_sf = scenario["property"]["total_sf"]
    year1_noi = projection[0]["_noi"]

    # ERV-based (fully reversioned) NOI: all space re-let at market rent today.
    # On a net lease recoverable expenses wash out against recoveries, so the
    # reversion net income is market rent less only the non-recoverable expenses
    # (keeping it comparable to the passing NOI, which also recovers opex).
    e1 = _annual_expenses(scenario["expenses"], total_sf, 0)
    non_recoverable = e1["total"] - e1["rec_fixed"] - e1["rec_variable"]
    market_income = ana["market_rent_psf"] * total_sf * (1 - ana["general_vacancy_pct"])
    reversion_noi = market_income - non_recoverable

    term_yield = val["term_yield"] or (year1_noi / price if price > 0 else ana["discount_rate"])
    reversion_yield = val["reversion_yield"] or ana["exit_cap_rate"]

    # Years to reversion: weighted-average unexpired lease term (WALT) of in-place space.
    leased = sum(l["suite_sf"] for l in scenario["leases"]) or 1.0
    walt = sum(l["suite_sf"] * l["term_years"] for l in scenario["leases"]) / leased
    walt = max(walt, 0.5)

    term_value = year1_noi * annuity_pv(term_yield, walt)
    reversion_capital = reversion_noi / reversion_yield if reversion_yield > 0 else 0.0
    reversion_value = reversion_capital / (1 + term_yield) ** walt
    tr_value = term_value + reversion_value

    return {
        "net_initial_yield": round(year1_noi / price, 4) if price > 0 else None,
        "reversionary_yield": round(reversion_noi / price, 4) if price > 0 else None,
        "passing_noi": round(year1_noi, 2),
        "reversion_noi": round(reversion_noi, 2),
        "term_yield": round(term_yield, 4),
        "reversion_yield_used": round(reversion_yield, 4),
        "years_to_reversion": round(walt, 2),
        "term_value": round(term_value, 2),
        "reversion_value": round(reversion_value, 2),
        "term_and_reversion_value": round(tr_value, 2),
    }


def _finalize(proj: dict, scenario: dict) -> dict:
    ana = scenario["analysis"]
    hold, price, total_sf = proj["hold"], ana["purchase_price"], proj["total_sf"]
    projection = _label_annual(proj["annual"], proj["exp_year"], proj["start_year"], hold)
    forward_noi = proj["annual"][hold]["noi"]
    flows = [row["_unlevered_cf"] for row in projection]

    dcf = _dcf(flows, forward_noi, price, ana["discount_rate"], ana["exit_cap_rate"],
               ana["selling_cost_pct"], hold)
    total_unlevered = sum(flows) + dcf["net_reversion"]
    year1_noi = projection[0]["_noi"]
    going_in = (year1_noi / price) if price > 0 else None

    metrics: dict[str, Any] = {
        "purchase_price": round(price, 2),
        "price_per_sf": round(price / total_sf, 2) if total_sf else None,
        "year1_noi": round(year1_noi, 2), "forward_noi": round(forward_noi, 2),
        "going_in_cap_rate": round(going_in, 4) if going_in is not None else None,
        "exit_cap_rate": ana["exit_cap_rate"], "discount_rate": ana["discount_rate"],
        "terminal_value": round(dcf["terminal_value"], 2),
        "net_reversion": round(dcf["net_reversion"], 2),
        "dcf_value": round(dcf["dcf_value"], 2),
        "dcf_value_per_sf": round(dcf["dcf_value"] / total_sf, 2) if total_sf else None,
        "npv": round(dcf["dcf_value"] - price, 2) if price > 0 else round(dcf["dcf_value"], 2),
        "unlevered_irr": round(dcf["unlevered_irr"], 4) if dcf["unlevered_irr"] is not None else None,
        "equity_multiple_unlevered": round(total_unlevered / price, 3) if price > 0 else None,
        "total_leasing_capital": round(
            sum(r["tenant_improvements"] + r["leasing_commissions"] + r["capital_reserve"]
                for r in projection), 2),
    }

    debt = scenario["debt"]
    if debt["enabled"]:
        metrics["debt"] = _finalize_debt(debt, projection, flows, dcf["net_reversion"], price,
                                          hold, year1_noi)

    trad = _traditional_valuation(scenario, projection, price, forward_noi)

    for row in projection:
        row.pop("_noi", None)
        row.pop("_unlevered_cf", None)

    return {"property": scenario["property"], "assumptions": ana,
            "market_leasing": scenario["market_leasing"], "valuation_inputs": scenario["valuation"],
            "years": [r["year"] for r in projection], "cash_flow": projection, "metrics": metrics,
            "traditional_valuation": trad,
            "_flows": flows, "_forward_noi": forward_noi}


def _finalize_debt(debt, projection, flows, net_reversion, price, hold, year1_noi):
    tranches_out, total_loan, total_ds_y1, total_payoff = [], 0.0, 0.0, 0.0
    total_participation = 0.0
    annual_ds = [0.0] * hold
    monthly_pay = 0.0
    for tr in debt["tranches"]:
        loan = tr["loan_amount"] or tr["ltv_pct"] * price
        sched = _mortgage_schedule(loan, tr["interest_rate"], tr["amortization_years"], hold, tr["io"])
        total_loan += loan
        total_payoff += sched["ending_balance"]
        total_ds_y1 += sched["annual_debt_service"][0]
        monthly_pay += sched["monthly_payment"]
        for i in range(hold):
            annual_ds[i] += sched["annual_debt_service"][i]
        total_participation += tr["participation_pct"]
        tranches_out.append({
            "name": tr["name"], "kind": tr["kind"], "loan_amount": round(loan, 2),
            "interest_rate": tr["interest_rate"], "amortization_years": tr["amortization_years"],
            "io": tr["io"], "monthly_payment": round(sched["monthly_payment"], 2),
            "loan_payoff": round(sched["ending_balance"], 2),
            "participation_pct": tr["participation_pct"],
        })

    equity = price - total_loan
    levered = []
    coc = []
    for i, row in enumerate(projection):
        lcf = row["_unlevered_cf"] - annual_ds[i]
        row["debt_service"] = round(-annual_ds[i], 2)
        row["levered_cash_flow"] = round(lcf, 2)
        levered.append(lcf)
        coc.append(lcf / equity if equity > 0 else 0.0)

    participation_amount = min(max(total_participation, 0.0), 1.0) * max(net_reversion - total_payoff, 0.0)
    net_equity_reversion = net_reversion - total_payoff - participation_amount
    lev_flows = levered[:]
    lev_flows[-1] += net_equity_reversion
    levered_irr = irr([-equity] + lev_flows) if equity > 0 else None
    total_levered = sum(levered) + net_equity_reversion

    return {
        "tranches": tranches_out, "loan_amount": round(total_loan, 2),
        "equity_invested": round(equity, 2),
        "ltv_pct": round(total_loan / price, 4) if price > 0 else None,
        "monthly_payment": round(monthly_pay, 2), "annual_debt_service": round(annual_ds[0], 2),
        "dscr_year1": round(year1_noi / annual_ds[0], 2) if annual_ds[0] else None,
        "loan_payoff": round(total_payoff, 2),
        "lender_participation": round(participation_amount, 2),
        "net_equity_reversion": round(net_equity_reversion, 2),
        "levered_irr": round(levered_irr, 4) if levered_irr is not None else None,
        "equity_multiple_levered": round(total_levered / equity, 3) if equity > 0 else None,
        "avg_cash_on_cash": round(sum(coc) / len(coc), 4) if coc else None,
    }


def _sensitivity(flows, forward_noi, price, scenario) -> dict:
    ana = scenario["analysis"]
    d0, c0 = ana["discount_rate"], ana["exit_cap_rate"]
    d_axis = [round(d0 + s, 4) for s in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    c_axis = [round(c0 + s, 4) for s in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    vgrid, igrid = [], []
    for d in d_axis:
        vr, ir = [], []
        for c in c_axis:
            if c <= 0:
                vr.append(None)
                ir.append(None)
                continue
            r = _dcf(flows, forward_noi, price, d, c, ana["selling_cost_pct"], scenario["analysis"]["hold_years"])
            vr.append(round(r["dcf_value"], 2))
            ir.append(round(r["unlevered_irr"], 4) if r["unlevered_irr"] is not None else None)
        vgrid.append(vr)
        igrid.append(ir)
    return {"discount_rates": d_axis, "exit_cap_rates": c_axis, "dcf_value": vgrid, "unlevered_irr": igrid}


def analyze(scenario: dict | None, with_sensitivity: bool = True,
            include_monthly: bool = True) -> dict:
    scenario = normalize_scenario(scenario)
    proj = _project(scenario)
    result = _finalize(proj, scenario)
    flows = result.pop("_flows")
    forward_noi = result.pop("_forward_noi")
    price = scenario["analysis"]["purchase_price"]
    if with_sensitivity:
        result["sensitivity"] = _sensitivity(flows, forward_noi, price, scenario)
    if include_monthly:
        monthly = _label_monthly(proj["monthly"], proj["start_year"], proj["start_month"], proj["hold"])
        if scenario["debt"]["enabled"] and result["metrics"].get("debt"):
            mpay = result["metrics"]["debt"]["monthly_payment"]
            for r in monthly:
                r["debt_service"] = round(-mpay, 2)
                r["levered_cash_flow"] = round(r["unlevered_cash_flow"] - mpay, 2)
        result["monthly_cash_flow"] = monthly
    return result


# --------------------------------------------------------------------------- #
# Portfolio / fund consolidation
# --------------------------------------------------------------------------- #

def consolidate(scenarios: list[dict]) -> dict:
    """Roll up several property scenarios into a fund-level summary."""
    assets, years = [], None
    agg_cf: list[float] = []
    agg_lev: list[float] = []
    totals = {"purchase_price": 0.0, "dcf_value": 0.0, "year1_noi": 0.0, "net_reversion": 0.0,
              "equity": 0.0, "loan": 0.0, "total_sf": 0.0}

    for sc in scenarios:
        r = analyze(sc, with_sensitivity=False, include_monthly=False)
        m = r["metrics"]
        hold = len(r["cash_flow"])
        if years is None:
            years = r["years"]
            agg_cf = [0.0] * hold
            agg_lev = [0.0] * hold
        for i, row in enumerate(r["cash_flow"][:len(agg_cf)]):
            agg_cf[i] += row["unlevered_cash_flow"]
            agg_lev[i] += row.get("levered_cash_flow", row["unlevered_cash_flow"])
        totals["purchase_price"] += m["purchase_price"]
        totals["dcf_value"] += m["dcf_value"]
        totals["year1_noi"] += m["year1_noi"]
        totals["net_reversion"] += m["net_reversion"]
        totals["total_sf"] += r["property"]["total_sf"]
        if m.get("debt"):
            totals["equity"] += m["debt"]["equity_invested"]
            totals["loan"] += m["debt"]["loan_amount"]
        else:
            totals["equity"] += m["purchase_price"]
        assets.append({
            "name": r["property"]["name"], "price": m["purchase_price"],
            "dcf_value": m["dcf_value"], "year1_noi": m["year1_noi"],
            "going_in_cap_rate": m["going_in_cap_rate"], "unlevered_irr": m["unlevered_irr"],
            "levered_irr": (m.get("debt") or {}).get("levered_irr"),
        })

    unlevered_flows = agg_cf[:]
    if unlevered_flows:
        unlevered_flows[-1] += totals["net_reversion"]
    port_irr = irr([-totals["purchase_price"]] + unlevered_flows) if totals["purchase_price"] > 0 else None

    return {
        "assets": assets, "years": years or [],
        "consolidated_cash_flow": [round(x, 2) for x in agg_cf],
        "consolidated_levered_cash_flow": [round(x, 2) for x in agg_lev],
        "totals": {
            "purchase_price": round(totals["purchase_price"], 2),
            "dcf_value": round(totals["dcf_value"], 2),
            "year1_noi": round(totals["year1_noi"], 2),
            "equity_invested": round(totals["equity"], 2),
            "loan_amount": round(totals["loan"], 2),
            "total_sf": round(totals["total_sf"], 0),
            "blended_going_in_cap": round(totals["year1_noi"] / totals["purchase_price"], 4)
            if totals["purchase_price"] else None,
            "portfolio_unlevered_irr": round(port_irr, 4) if port_irr is not None else None,
            "price_per_sf": round(totals["purchase_price"] / totals["total_sf"], 2)
            if totals["total_sf"] else None,
        },
    }


# --------------------------------------------------------------------------- #
# Sample deal
# --------------------------------------------------------------------------- #

def sample_scenario() -> dict:
    """A representative 100,000 SF office deal used as the default scenario."""
    return {
        "property": {"name": "Harbor Point Office Tower", "property_type": "Office",
                     "total_sf": 100000},
        "analysis": {
            "start_year": 2026, "start_month": 1, "hold_years": 10, "purchase_price": 28500000,
            "discount_rate": 0.0825, "exit_cap_rate": 0.0675, "selling_cost_pct": 0.02,
            "general_vacancy_pct": 0.05, "market_rent_psf": 34.0, "market_rent_growth_pct": 0.03,
            "expense_gross_up_pct": 0.95, "cpi_rate": 0.025,
        },
        "market_leasing": {
            "renewal_probability": 0.65, "market_term_years": 7, "renewal_term_years": 5,
            "downtime_months": 9.0, "renewal_market_rent_psf": 0.0,
            "new_free_rent_months": 5.0, "renewal_free_rent_months": 1.0,
            "new_ti_psf": 45.0, "renewal_ti_psf": 15.0,
            "new_lc_pct": 0.06, "renewal_lc_pct": 0.03, "lc_basis": "percent",
            "reimbursement_method": "net", "recovery": {"cap_pct": 0.0, "admin_fee_pct": 0.0},
        },
        "valuation": {"term_yield": 0.0, "reversion_yield": 0.0},
        "leases": [
            {"tenant": "Meridian Capital (Anchor)", "suite_sf": 45000, "start_year": 1,
             "term_years": 10, "base_rent_psf": 33.0, "escalation_type": "fixed",
             "annual_escalation_pct": 0.03, "reimbursement_method": "net"},
            {"tenant": "Lumen Health Systems", "suite_sf": 28000, "start_year": 1,
             "term_years": 7, "base_rent_psf": 31.5, "escalation_type": "cpi", "cpi_rate": 0.025,
             "free_rent_months": 3, "reimbursement_method": "base_stop",
             "recovery": {"admin_fee_pct": 0.03}},
            {"tenant": "Northwind Advisory", "suite_sf": 15000, "start_year": 1,
             "term_years": 5, "base_rent_psf": 30.0, "escalation_type": "stepped",
             "rent_steps": [{"lease_year": 1, "rent_psf": 30}, {"lease_year": 3, "rent_psf": 33},
                            {"lease_year": 5, "rent_psf": 36}], "reimbursement_method": "net"},
        ],
        "expenses": [
            {"name": "Property Taxes", "amount": 5.25, "basis": "psf", "growth_pct": 0.025,
             "recoverable": True, "variable": False},
            {"name": "Insurance", "amount": 1.10, "basis": "psf", "growth_pct": 0.03,
             "recoverable": True, "variable": False},
            {"name": "Utilities", "amount": 2.40, "basis": "psf", "growth_pct": 0.03,
             "recoverable": True, "variable": True},
            {"name": "Repairs & Maintenance", "amount": 2.10, "basis": "psf", "growth_pct": 0.03,
             "recoverable": True, "variable": True},
            {"name": "Management Fee", "amount": 1.95, "basis": "psf", "growth_pct": 0.03,
             "recoverable": True, "variable": True},
            {"name": "General & Administrative", "amount": 0.85, "basis": "psf", "growth_pct": 0.025,
             "recoverable": False, "variable": True},
        ],
        "capital": {"reserve_psf": 0.25, "growth_pct": 0.025},
        "debt": {"enabled": True, "tranches": [
            {"name": "Senior Loan", "kind": "senior", "ltv_pct": 0.55, "interest_rate": 0.0600,
             "amortization_years": 30, "io": False},
            {"name": "Mezzanine", "kind": "mezzanine", "ltv_pct": 0.10, "interest_rate": 0.1000,
             "amortization_years": 0, "io": True, "participation_pct": 0.10},
        ]},
    }
