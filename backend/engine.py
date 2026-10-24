"""ARGUS-style commercial real estate valuation engine (v5 — calendar-daily).

A dependency-free model that computes the way ARGUS Enterprise does: a daily
cash flow accrued on the **actual calendar** (real dates, leap years,
calendar-aligned financial years), rolled up to months and financial years.

Feature surface
---------------
* **Calendar-exact daily accrual.** Rent, expenses, recoveries, downtime,
  free rent and capital are accrued per real day; financial years are true
  12-month calendar periods from the analysis start (so fiscal-year starts work).
* **Rent reviews.** Fixed, CPI (flat rate *or* a published **index series**),
  or an explicit **stepped** schedule, per lease.
* **Market Leasing Assumptions.** Renewal-probability-weighted re-leasing with
  separate renewal rent/term, downtime, free rent, TI and LC.
* **Reimbursements.** Net / Base-Year Stop / Gross with occupancy gross-up, an
  annual cap, an expense stop ($/SF), an admin fee, and recoverable /
  non-recoverable + fixed / variable expense pools.
* **Leasing commissions** as a percent of rent or $/SF; **percentage rent**.
* **Debt.** Multiple tranches (senior / mezzanine), interest-only or amortizing,
  with **participation in the reversion and/or in annual cash flow**.
* **Valuation.** DCF (NPV, IRR, equity multiples) plus the traditional methods:
  Net Initial Yield, Reversionary Yield, **Equivalent Yield** (iteratively
  solved), **Term & Reversion** and the **Hardcore / layer** method.
* **Sensitivity** across a discount-rate x exit-cap grid.
* **Portfolio consolidation** with optional **cross-collateralised fund debt**.

All money is in whole dollars; all rates are decimals (0.08 == 8%).
"""

from __future__ import annotations

import datetime as _dt
from calendar import monthrange
from typing import Any

DPY = 365.25
DPM = 365.25 / 12.0


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
    """PV of $1/year for ``n_years`` at ``rate`` (years' purchase)."""
    if rate == 0:
        return n_years
    return (1 - (1 + rate) ** (-n_years)) / rate


def solve_decreasing(fn, target: float, lo: float = 1e-4, hi: float = 0.75,
                     tol: float = 1.0) -> float | None:
    """Bisection for a monotonically *decreasing* fn(x) == target."""
    f_lo, f_hi = fn(lo) - target, fn(hi) - target
    if (f_lo > 0) == (f_hi > 0):
        return None
    for _ in range(100):
        mid = (lo + hi) / 2.0
        fm = fn(mid) - target
        if abs(fm) < tol:
            return mid
        if (fm > 0) == (f_lo > 0):
            lo, f_lo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2.0


def _mortgage_schedule(principal, annual_rate, amort_years, hold_years, interest_only):
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


def _add_months(d: _dt.date, months: int) -> _dt.date:
    total = d.month - 1 + months
    y = d.year + total // 12
    m = total % 12 + 1
    return _dt.date(y, m, min(d.day, monthrange(y, m)[1]))


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

def _num(value, default=0.0):
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _bool(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "")
    return bool(value)


_REIMB = ("net", "base_stop", "gross")


def _reimb_method(value, default="net"):
    v = str(value or default).lower().replace("-", "_").replace(" ", "_")
    return v if v in _REIMB else default


def _esc_type(value, default="fixed"):
    v = str(value or default).lower()
    return v if v in ("fixed", "cpi", "stepped") else default


def _series(value):
    out = []
    for x in value or []:
        out.append(_num(x, 0.0))
    return out


def _percentage_rent(pr):
    if not pr:
        return None
    pr = dict(pr)
    sales, pct = _num(pr.get("sales_psf")), _num(pr.get("percent"))
    if sales <= 0 or pct <= 0:
        return None
    return {"sales_psf": sales, "percent": pct, "breakpoint_psf": _num(pr.get("breakpoint_psf")),
            "sales_growth_pct": _num(pr.get("sales_growth_pct"))}


def _rent_steps(steps):
    out = [{"lease_year": max(int(_num(s.get("lease_year"), 1)), 1),
            "rent_psf": _num(s.get("rent_psf"), 0.0)} for s in (steps or [])]
    out.sort(key=lambda s: s["lease_year"])
    return out


def _recovery(rec):
    rec = dict(rec or {})
    return {"cap_pct": _num(rec.get("cap_pct")), "stop_psf": _num(rec.get("stop_psf")),
            "admin_fee_pct": _num(rec.get("admin_fee_pct"))}


def _tranche(t, default_name):
    return {"name": str(t.get("name") or default_name),
            "kind": "mezzanine" if str(t.get("kind", "")).lower().startswith("mezz") else "senior",
            "ltv_pct": _num(t.get("ltv_pct")), "loan_amount": _num(t.get("loan_amount")),
            "interest_rate": _num(t.get("interest_rate"), 0.065),
            "amortization_years": int(_num(t.get("amortization_years"), 30)),
            "io": _bool(t.get("io"), False),
            "participation_pct": _num(t.get("participation_pct")),
            "participation_cf_pct": _num(t.get("participation_cf_pct"))}


def _normalize_debt(debt):
    debt = dict(debt or {})
    enabled = _bool(debt.get("enabled"), False)
    tranches = debt.get("tranches")
    if tranches:
        norm = [_tranche(dict(t), f"Tranche {i + 1}") for i, t in enumerate(tranches)]
    elif enabled or debt.get("ltv_pct") or debt.get("loan_amount"):
        norm = [_tranche(debt, "Senior Loan")]
    else:
        norm = []
    return {"enabled": enabled and bool(norm), "tranches": norm}


def normalize_scenario(scenario):
    scenario = dict(scenario or {})
    prop = dict(scenario.get("property", {}))
    ana = dict(scenario.get("analysis", {}))
    cap = dict(scenario.get("capital", {}))
    mla = dict(scenario.get("market_leasing", {}))
    val = dict(scenario.get("valuation", {}))

    norm = {
        "property": {"name": str(prop.get("name") or "Untitled Property"),
                     "property_type": str(prop.get("property_type") or "Office"),
                     "total_sf": max(_num(prop.get("total_sf"), 1.0), 1.0)},
        "analysis": {
            "start_year": int(_num(ana.get("start_year"), 2026)),
            "start_month": min(max(int(_num(ana.get("start_month"), 1)), 1), 12),
            "hold_years": max(int(_num(ana.get("hold_years"), 10)), 1),
            "purchase_price": _num(ana.get("purchase_price")),
            "discount_rate": _num(ana.get("discount_rate"), 0.08),
            "exit_cap_rate": _num(ana.get("exit_cap_rate"), 0.065),
            "selling_cost_pct": _num(ana.get("selling_cost_pct"), 0.02),
            "general_vacancy_pct": _num(ana.get("general_vacancy_pct"), 0.05),
            "market_rent_psf": _num(ana.get("market_rent_psf")),
            "market_rent_growth_pct": _num(ana.get("market_rent_growth_pct"), 0.03),
            "expense_gross_up_pct": _num(ana.get("expense_gross_up_pct")),
            "cpi_rate": _num(ana.get("cpi_rate"), 0.025),
            "cpi_series": _series(ana.get("cpi_series")),
        },
        "market_leasing": {
            "renewal_probability": min(max(_num(mla.get("renewal_probability"), 0.65), 0.0), 1.0),
            "market_term_years": max(_num(mla.get("market_term_years"), 5.0), 0.5),
            "renewal_term_years": max(_num(mla.get("renewal_term_years"),
                                            _num(mla.get("market_term_years"), 5.0)), 0.5),
            "downtime_months": max(_num(mla.get("downtime_months"), 9.0), 0.0),
            "renewal_market_rent_psf": _num(mla.get("renewal_market_rent_psf")),
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
        "valuation": {"term_yield": _num(val.get("term_yield")),
                      "reversion_yield": _num(val.get("reversion_yield")),
                      "hardcore_yield": _num(val.get("hardcore_yield"))},
        "leases": [], "expenses": [],
        "capital": {"reserve_psf": _num(cap.get("reserve_psf")),
                    "growth_pct": _num(cap.get("growth_pct"), 0.02)},
        "debt": _normalize_debt(scenario.get("debt", {})),
    }

    for lease in scenario.get("leases", []) or []:
        lease = dict(lease)
        norm["leases"].append({
            "tenant": str(lease.get("tenant") or "Tenant"),
            "suite_sf": max(_num(lease.get("suite_sf")), 0.0),
            "start_year": max(int(_num(lease.get("start_year"), 1)), 1),
            "start_month": min(max(int(_num(lease.get("start_month"), 1)), 1), 12),
            "term_years": max(_num(lease.get("term_years"), 1.0), 0.1),
            "base_rent_psf": _num(lease.get("base_rent_psf")),
            "escalation_type": _esc_type(lease.get("escalation_type"), "fixed"),
            "annual_escalation_pct": _num(lease.get("annual_escalation_pct")),
            "cpi_rate": _num(lease.get("cpi_rate")),
            "cpi_series": _series(lease.get("cpi_series")),
            "rent_steps": _rent_steps(lease.get("rent_steps")),
            "free_rent_months": max(_num(lease.get("free_rent_months")), 0.0),
            "ti_psf": max(_num(lease.get("ti_psf")), 0.0),
            "lc_pct": max(_num(lease.get("lc_pct")), 0.0),
            "lc_basis": "psf" if str(lease.get("lc_basis", "percent")).lower() == "psf" else "percent",
            "reimbursement_method": _reimb_method(lease.get("reimbursement_method"), "net"),
            "recovery": _recovery(lease.get("recovery")),
            "percentage_rent": _percentage_rent(lease.get("percentage_rent")),
        })

    for exp in scenario.get("expenses", []) or []:
        exp = dict(exp)
        basis = str(exp.get("basis") or "psf").lower()
        norm["expenses"].append({
            "name": str(exp.get("name") or "Expense"), "amount": _num(exp.get("amount")),
            "basis": basis if basis in ("psf", "total") else "psf",
            "growth_pct": _num(exp.get("growth_pct")),
            "recoverable": _bool(exp.get("recoverable"), True),
            "variable": _bool(exp.get("variable"), True)})

    return norm


# --------------------------------------------------------------------------- #
# CPI index helper
# --------------------------------------------------------------------------- #

def _cpi_factor(seg, whole_years, analysis):
    """Cumulative CPI index factor after ``whole_years`` of a CPI lease."""
    series = seg["cpi_series"] or analysis["cpi_series"]
    if series:
        factor = 1.0
        for i in range(whole_years):
            factor *= 1 + (series[i] if i < len(series) else series[-1])
        return factor
    rate = seg["cpi"] if seg["cpi"] else analysis["cpi_rate"]
    return (1 + rate) ** whole_years


# --------------------------------------------------------------------------- #
# Lease segments (ordinal-day axis on the real calendar)
# --------------------------------------------------------------------------- #

def _build_segments(inplace, mla, analysis, start_ord, horizon_ord):
    p = mla["renewal_probability"]
    mkt0 = analysis["market_rent_psf"]
    renewal_mkt0 = mla["renewal_market_rent_psf"] or mkt0
    mg = analysis["market_rent_growth_pct"]
    start_date = _dt.date.fromordinal(start_ord)

    down_eff_d = round((1 - p) * mla["downtime_months"] * DPM)
    free_eff_d = round((p * mla["renewal_free_rent_months"]
                        + (1 - p) * mla["new_free_rent_months"]) * DPM)
    ti_eff = p * mla["renewal_ti_psf"] + (1 - p) * mla["new_ti_psf"]
    lc_eff = p * mla["renewal_lc_pct"] + (1 - p) * mla["new_lc_pct"]
    term_eff_d = round((p * mla["renewal_term_years"] + (1 - p) * mla["market_term_years"]) * DPY)
    blended_rent0 = p * renewal_mkt0 + (1 - p) * mkt0

    def market_seg(commence_ord, down_before):
        rent0 = blended_rent0 * (1 + mg) ** ((commence_ord - start_ord) / DPY)
        return {"start_ord": commence_ord, "end_ord": commence_ord + term_eff_d,
                "term_years": term_eff_d / DPY, "down_before_d": down_before,
                "rent_psf0": rent0, "esc": mg, "esc_type": "fixed", "cpi": 0.0, "cpi_series": [],
                "rent_steps": [], "is_inplace": False, "free_d": free_eff_d, "ti_psf": ti_eff,
                "lc": lc_eff, "lc_basis": mla["lc_basis"], "reimb": mla["reimbursement_method"],
                "recovery": mla["recovery"], "percentage_rent": None}

    segs = []
    if inplace:
        seg_start = _add_months(start_date,
                                (inplace["start_year"] - 1) * 12 + (inplace["start_month"] - 1))
        s_ord = seg_start.toordinal()
        term_d = round(inplace["term_years"] * DPY)
        segs.append({"start_ord": s_ord, "end_ord": s_ord + term_d, "term_years": inplace["term_years"],
                     "down_before_d": 0, "rent_psf0": inplace["base_rent_psf"],
                     "esc": inplace["annual_escalation_pct"], "esc_type": inplace["escalation_type"],
                     "cpi": inplace["cpi_rate"], "cpi_series": inplace["cpi_series"],
                     "rent_steps": inplace["rent_steps"], "is_inplace": True,
                     "free_d": round(inplace["free_rent_months"] * DPM), "ti_psf": inplace["ti_psf"],
                     "lc": inplace["lc_pct"], "lc_basis": inplace["lc_basis"],
                     "reimb": inplace["reimbursement_method"], "recovery": inplace["recovery"],
                     "percentage_rent": inplace["percentage_rent"]})
        next_commence = s_ord + term_d + down_eff_d
    else:
        next_commence = start_ord + down_eff_d

    while next_commence < horizon_ord and term_eff_d > 0:
        segs.append(market_seg(next_commence, down_eff_d))
        next_commence += term_eff_d + down_eff_d
    return segs


def _seg_rent_psf(seg, d_ord, analysis):
    years_in = (d_ord - seg["start_ord"]) / DPY
    whole = int(years_in + 1e-9)
    if seg["esc_type"] == "stepped" and seg["rent_steps"]:
        rate = seg["rent_steps"][0]["rent_psf"]
        for step in seg["rent_steps"]:
            if step["lease_year"] <= whole + 1:
                rate = step["rent_psf"]
        return rate
    if seg["esc_type"] == "cpi":
        return seg["rent_psf0"] * _cpi_factor(seg, whole, analysis)
    return seg["rent_psf0"] * (1 + seg["esc"]) ** whole


def _seg_lc_amount(seg, suite_sf):
    if seg["lc_basis"] == "psf":
        return seg["lc"] * suite_sf
    return seg["lc"] * (suite_sf * seg["rent_psf0"] * seg["term_years"])


# --------------------------------------------------------------------------- #
# Expenses
# --------------------------------------------------------------------------- #

def _annual_expenses(expenses, total_sf, fy):
    detail, total, rec_fixed, rec_variable = {}, 0.0, 0.0, 0.0
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
# Daily projection (calendar-exact)
# --------------------------------------------------------------------------- #

def _build_spaces(scenario, start_ord, horizon_ord):
    total_sf = scenario["property"]["total_sf"]
    mla, ana = scenario["market_leasing"], scenario["analysis"]
    spaces = [{"suite_sf": l["suite_sf"],
               "segments": _build_segments(l, mla, ana, start_ord, horizon_ord)}
              for l in scenario["leases"]]
    vacant = max(total_sf - sum(l["suite_sf"] for l in scenario["leases"]), 0.0)
    if vacant > 0.5 and ana["market_rent_psf"] > 0:
        spaces.append({"suite_sf": vacant,
                       "segments": _build_segments(None, mla, ana, start_ord, horizon_ord)})
    return spaces


_SUM_FIELDS = (
    "potential_base_rent", "absorption_turnover_vacancy", "base_rent_abatements",
    "scheduled_base_rent", "percentage_rent", "expense_reimbursements",
    "total_tenant_revenue", "general_vacancy", "effective_gross_revenue",
    "operating_expenses", "noi", "tenant_improvements", "leasing_commissions",
    "capital_reserve", "unlevered_cash_flow",
)


def _project(scenario):
    ana = scenario["analysis"]
    hold = ana["hold_years"]
    total_sf = scenario["property"]["total_sf"]
    exp = scenario["expenses"]
    gross_up = ana["expense_gross_up_pct"]
    gen_vac = ana["general_vacancy_pct"]
    reserve_psf = scenario["capital"]["reserve_psf"]
    reserve_growth = scenario["capital"]["growth_pct"]
    mkt0, mg = ana["market_rent_psf"], ana["market_rent_growth_pct"]

    start_date = _dt.date(ana["start_year"], ana["start_month"], 1)
    start_ord = start_date.toordinal()
    n_years = hold + 1
    fy_start = [_add_months(start_date, k * 12).toordinal() for k in range(n_years + 1)]
    mo_start = [_add_months(start_date, k).toordinal() for k in range(hold * 12 + 1)]
    days_in_fy = [fy_start[k + 1] - fy_start[k] for k in range(n_years)]
    horizon_ord = fy_start[n_years]
    spaces = _build_spaces(scenario, start_ord, horizon_ord)
    exp_year = [_annual_expenses(exp, total_sf, fy) for fy in range(n_years)]

    def blank():
        return {f: 0.0 for f in _SUM_FIELDS} | {"occ_days": 0.0, "days": 0}
    annual = [blank() for _ in range(n_years)]
    monthly = [blank() for _ in range(hold * 12)]

    fy = mo = 0
    for cur_ord in range(start_ord, horizon_ord):
        while fy + 1 < n_years and cur_ord >= fy_start[fy + 1]:
            fy += 1
        while mo + 1 < len(mo_start) and cur_ord >= mo_start[mo + 1]:
            mo += 1
        ey = exp_year[fy]
        dfy = days_in_fy[fy]
        day_opex = ey["total"] / dfy
        mkt_psf_day = mkt0 * (1 + mg) ** ((cur_ord - start_ord) / DPY)

        potential = turnover = abate = ti = lc = pct_rent = reimb = 0.0
        occ_sf = 0.0
        active = []
        for sp in spaces:
            seg = next((s for s in sp["segments"] if s["start_ord"] <= cur_ord < s["end_ord"]), None)
            if seg is not None:
                occ_sf += sp["suite_sf"]
                active.append((sp, seg))
        occupancy = min(occ_sf / total_sf, 1.0) if total_sf else 0.0
        gu = (gross_up / occupancy) if (gross_up > 0 and 0 < occupancy < gross_up) else 1.0
        rec_pool_day = (ey["rec_fixed"] + ey["rec_variable"] * gu) / dfy

        for sp, seg in active:
            suite = sp["suite_sf"]
            rent_psf = _seg_rent_psf(seg, cur_ord, ana)
            day_rent = suite * rent_psf / dfy
            potential += day_rent
            if seg["start_ord"] <= cur_ord < seg["start_ord"] + seg["free_d"]:
                abate += day_rent

            pr = seg["percentage_rent"]
            if pr:
                yrs = int((cur_ord - seg["start_ord"]) / DPY)
                sales = pr["sales_psf"] * (1 + pr["sales_growth_pct"]) ** yrs
                bp = pr["breakpoint_psf"] or (rent_psf / pr["percent"] if pr["percent"] else 0.0)
                pct_rent += suite * max(sales - bp, 0.0) * pr["percent"] / dfy

            method = seg["reimb"]
            if method != "gross":
                share = suite / total_sf if total_sf else 0.0
                rec = seg["recovery"]
                base_fy = min(max(int((seg["start_ord"] - start_ord) / DPY), 0), n_years - 1)
                if method == "base_stop":
                    base_pool = (exp_year[base_fy]["rec_fixed"]
                                 + exp_year[base_fy]["rec_variable"] * gu) / days_in_fy[base_fy]
                    recoverable = max(rec_pool_day - base_pool, 0.0)
                else:
                    recoverable = rec_pool_day
                if rec["cap_pct"] > 0:
                    base_full = (exp_year[base_fy]["rec_fixed"]
                                 + exp_year[base_fy]["rec_variable"]) / days_in_fy[base_fy]
                    recoverable = min(recoverable, max(base_full * (1 + rec["cap_pct"]) ** (fy - base_fy), 0.0))
                tenant_reimb = share * recoverable
                if rec["stop_psf"] > 0:
                    tenant_reimb = max(tenant_reimb - rec["stop_psf"] * suite / dfy, 0.0)
                reimb += tenant_reimb * (1 + rec["admin_fee_pct"])

        if occ_sf < total_sf - 0.5:
            for sp in spaces:
                for seg in sp["segments"]:
                    if seg["start_ord"] - seg["down_before_d"] <= cur_ord < seg["start_ord"]:
                        lost = sp["suite_sf"] * mkt_psf_day / dfy
                        potential += lost
                        turnover += lost

        for sp in spaces:
            for seg in sp["segments"]:
                if seg["start_ord"] == cur_ord and seg["start_ord"] >= start_ord:
                    ti += sp["suite_sf"] * seg["ti_psf"]
                    lc += _seg_lc_amount(seg, sp["suite_sf"])

        scheduled = potential - turnover - abate
        ttr = scheduled + reimb + pct_rent
        general_vacancy = -max(gen_vac * potential - turnover, 0.0)
        egr = ttr + general_vacancy
        noi = egr - day_opex
        reserve = total_sf * reserve_psf * (1 + reserve_growth) ** fy / dfy
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

    return {"annual": annual, "monthly": monthly, "exp_year": exp_year, "total_sf": total_sf,
            "hold": hold, "start_year": ana["start_year"], "start_month": ana["start_month"]}


def _label_annual(annual, exp_year, start_year, hold):
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


def _label_monthly(monthly, start_year, start_month, hold):
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
# Valuation
# --------------------------------------------------------------------------- #

def _dcf(flows, forward_noi, price, discount, exit_cap, selling_cost, hold):
    terminal = forward_noi / exit_cap if exit_cap > 0 else 0.0
    net_reversion = terminal * (1 - selling_cost)
    pv_ops = sum(cf / (1 + discount) ** (i + 1) for i, cf in enumerate(flows))
    dcf_value = pv_ops + net_reversion / (1 + discount) ** hold
    rev = flows[:]
    rev[-1] += net_reversion
    return {"terminal_value": terminal, "net_reversion": net_reversion, "dcf_value": dcf_value,
            "unlevered_irr": irr([-price] + rev) if price > 0 else None}


def _traditional_valuation(scenario, projection, price):
    ana, val = scenario["analysis"], scenario["valuation"]
    total_sf = scenario["property"]["total_sf"]
    year1_noi = projection[0]["_noi"]
    e1 = _annual_expenses(scenario["expenses"], total_sf, 0)
    non_rec = e1["total"] - e1["rec_fixed"] - e1["rec_variable"]
    reversion_noi = ana["market_rent_psf"] * total_sf * (1 - ana["general_vacancy_pct"]) - non_rec

    leased = sum(l["suite_sf"] for l in scenario["leases"]) or 1.0
    walt = max(sum(l["suite_sf"] * l["term_years"] for l in scenario["leases"]) / leased, 0.5)

    term_yield = val["term_yield"] or (year1_noi / price if price > 0 else ana["discount_rate"])
    reversion_yield = val["reversion_yield"] or ana["exit_cap_rate"]
    term_value = year1_noi * annuity_pv(term_yield, walt)
    reversion_value = (reversion_noi / reversion_yield if reversion_yield > 0 else 0.0) / (1 + term_yield) ** walt

    # Equivalent yield: single yield equating the term + perpetual reversion to price.
    eq_yield = None
    if price > 0 and year1_noi > 0:
        eq_yield = solve_decreasing(
            lambda y: year1_noi * annuity_pv(y, walt) + (reversion_noi / y) / (1 + y) ** walt, price)
    hardcore_yield = val["hardcore_yield"] or eq_yield or reversion_yield
    hardcore_value = None
    if hardcore_yield and hardcore_yield > 0:
        core = year1_noi / hardcore_yield
        top = (reversion_noi - year1_noi) / hardcore_yield / (1 + hardcore_yield) ** walt
        hardcore_value = core + top

    return {
        "net_initial_yield": round(year1_noi / price, 4) if price > 0 else None,
        "reversionary_yield": round(reversion_noi / price, 4) if price > 0 else None,
        "equivalent_yield": round(eq_yield, 4) if eq_yield is not None else None,
        "passing_noi": round(year1_noi, 2), "reversion_noi": round(reversion_noi, 2),
        "term_yield": round(term_yield, 4), "reversion_yield_used": round(reversion_yield, 4),
        "hardcore_yield": round(hardcore_yield, 4) if hardcore_yield else None,
        "years_to_reversion": round(walt, 2),
        "term_value": round(term_value, 2), "reversion_value": round(reversion_value, 2),
        "term_and_reversion_value": round(term_value + reversion_value, 2),
        "hardcore_value": round(hardcore_value, 2) if hardcore_value is not None else None,
    }


def _finalize_debt(debt, projection, flows, net_reversion, price, hold, year1_noi):
    tranches_out, total_loan, total_payoff, total_part, total_cf_part = [], 0.0, 0.0, 0.0, 0.0
    annual_ds = [0.0] * hold
    monthly_pay = 0.0
    for tr in debt["tranches"]:
        loan = tr["loan_amount"] or tr["ltv_pct"] * price
        sched = _mortgage_schedule(loan, tr["interest_rate"], tr["amortization_years"], hold, tr["io"])
        total_loan += loan
        total_payoff += sched["ending_balance"]
        monthly_pay += sched["monthly_payment"]
        for i in range(hold):
            annual_ds[i] += sched["annual_debt_service"][i]
        total_part += tr["participation_pct"]
        total_cf_part += tr["participation_cf_pct"]
        tranches_out.append({"name": tr["name"], "kind": tr["kind"], "loan_amount": round(loan, 2),
                             "interest_rate": tr["interest_rate"], "io": tr["io"],
                             "amortization_years": tr["amortization_years"],
                             "monthly_payment": round(sched["monthly_payment"], 2),
                             "loan_payoff": round(sched["ending_balance"], 2),
                             "participation_pct": tr["participation_pct"],
                             "participation_cf_pct": tr["participation_cf_pct"]})

    equity = price - total_loan
    cf_part_pct = min(max(total_cf_part, 0.0), 1.0)
    equity_cf, coc, total_cf_paid = [], [], 0.0
    for i, row in enumerate(projection):
        lcf = row["_unlevered_cf"] - annual_ds[i]
        part = cf_part_pct * max(lcf, 0.0)
        total_cf_paid += part
        ecf = lcf - part
        row["debt_service"] = round(-annual_ds[i], 2)
        row["levered_cash_flow"] = round(ecf, 2)
        equity_cf.append(ecf)
        coc.append(ecf / equity if equity > 0 else 0.0)

    part_amount = min(max(total_part, 0.0), 1.0) * max(net_reversion - total_payoff, 0.0)
    net_equity_reversion = net_reversion - total_payoff - part_amount
    lev = equity_cf[:]
    lev[-1] += net_equity_reversion
    levered_irr = irr([-equity] + lev) if equity > 0 else None
    total_levered = sum(equity_cf) + net_equity_reversion
    return {"tranches": tranches_out, "loan_amount": round(total_loan, 2),
            "equity_invested": round(equity, 2),
            "ltv_pct": round(total_loan / price, 4) if price > 0 else None,
            "monthly_payment": round(monthly_pay, 2), "annual_debt_service": round(annual_ds[0], 2),
            "dscr_year1": round(year1_noi / annual_ds[0], 2) if annual_ds[0] else None,
            "loan_payoff": round(total_payoff, 2),
            "lender_participation": round(part_amount, 2),
            "lender_cashflow_participation": round(total_cf_paid, 2),
            "net_equity_reversion": round(net_equity_reversion, 2),
            "levered_irr": round(levered_irr, 4) if levered_irr is not None else None,
            "equity_multiple_levered": round(total_levered / equity, 3) if equity > 0 else None,
            "avg_cash_on_cash": round(sum(coc) / len(coc), 4) if coc else None}


def _finalize(proj, scenario):
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

    metrics = {"purchase_price": round(price, 2),
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
               "total_leasing_capital": round(sum(r["tenant_improvements"] + r["leasing_commissions"]
                                                  + r["capital_reserve"] for r in projection), 2)}
    if scenario["debt"]["enabled"]:
        metrics["debt"] = _finalize_debt(scenario["debt"], projection, flows, dcf["net_reversion"],
                                         price, hold, year1_noi)
    trad = _traditional_valuation(scenario, projection, price)
    for row in projection:
        row.pop("_noi", None)
        row.pop("_unlevered_cf", None)
    return {"property": scenario["property"], "assumptions": ana,
            "market_leasing": scenario["market_leasing"], "valuation_inputs": scenario["valuation"],
            "years": [r["year"] for r in projection], "cash_flow": projection, "metrics": metrics,
            "traditional_valuation": trad, "_flows": flows, "_forward_noi": forward_noi}


def _sensitivity(flows, forward_noi, price, scenario):
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
            r = _dcf(flows, forward_noi, price, d, c, ana["selling_cost_pct"], ana["hold_years"])
            vr.append(round(r["dcf_value"], 2))
            ir.append(round(r["unlevered_irr"], 4) if r["unlevered_irr"] is not None else None)
        vgrid.append(vr)
        igrid.append(ir)
    return {"discount_rates": d_axis, "exit_cap_rates": c_axis, "dcf_value": vgrid, "unlevered_irr": igrid}


def analyze(scenario, with_sensitivity=True, include_monthly=True):
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
# Portfolio / fund consolidation (with optional cross-collateralised debt)
# --------------------------------------------------------------------------- #

def consolidate(scenarios, fund_debt=None):
    assets, years = [], None
    agg_cf, agg_lev = [], []
    totals = {"purchase_price": 0.0, "dcf_value": 0.0, "year1_noi": 0.0, "net_reversion": 0.0,
              "equity": 0.0, "loan": 0.0, "total_sf": 0.0}
    for sc in scenarios:
        r = analyze(sc, with_sensitivity=False, include_monthly=False)
        m = r["metrics"]
        hold = len(r["cash_flow"])
        if years is None:
            years, agg_cf, agg_lev = r["years"], [0.0] * hold, [0.0] * hold
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
        assets.append({"name": r["property"]["name"], "price": m["purchase_price"],
                       "dcf_value": m["dcf_value"], "year1_noi": m["year1_noi"],
                       "going_in_cap_rate": m["going_in_cap_rate"], "unlevered_irr": m["unlevered_irr"],
                       "levered_irr": (m.get("debt") or {}).get("levered_irr")})

    unlev = agg_cf[:]
    if unlev:
        unlev[-1] += totals["net_reversion"]
    port_irr = irr([-totals["purchase_price"]] + unlev) if totals["purchase_price"] > 0 else None

    out = {"assets": assets, "years": years or [],
           "consolidated_cash_flow": [round(x, 2) for x in agg_cf],
           "consolidated_levered_cash_flow": [round(x, 2) for x in agg_lev],
           "totals": {"purchase_price": round(totals["purchase_price"], 2),
                      "dcf_value": round(totals["dcf_value"], 2),
                      "year1_noi": round(totals["year1_noi"], 2),
                      "equity_invested": round(totals["equity"], 2),
                      "loan_amount": round(totals["loan"], 2),
                      "total_sf": round(totals["total_sf"], 0),
                      "blended_going_in_cap": round(totals["year1_noi"] / totals["purchase_price"], 4)
                      if totals["purchase_price"] else None,
                      "portfolio_unlevered_irr": round(port_irr, 4) if port_irr is not None else None,
                      "price_per_sf": round(totals["purchase_price"] / totals["total_sf"], 2)
                      if totals["total_sf"] else None}}

    # Optional cross-collateralised fund-level facility on the whole portfolio.
    if fund_debt and _bool(fund_debt.get("enabled"), True) and len(agg_cf):
        price_all = totals["purchase_price"]
        loan = _num(fund_debt.get("loan_amount")) or _num(fund_debt.get("ltv_pct")) * price_all
        rate = _num(fund_debt.get("interest_rate"), 0.06)
        amort = int(_num(fund_debt.get("amortization_years"), 30))
        io = _bool(fund_debt.get("io"), False)
        sched = _mortgage_schedule(loan, rate, amort, len(agg_cf), io)
        equity = price_all - loan
        fund_lev = [agg_cf[i] - sched["annual_debt_service"][i] for i in range(len(agg_cf))]
        net_rev = totals["net_reversion"] - sched["ending_balance"]
        lev = fund_lev[:]
        lev[-1] += net_rev
        fund_irr = irr([-equity] + lev) if equity > 0 else None
        total_lev = sum(fund_lev) + net_rev
        out["fund_debt"] = {
            "loan_amount": round(loan, 2), "ltv_pct": round(loan / price_all, 4) if price_all else None,
            "interest_rate": rate, "equity_invested": round(equity, 2),
            "annual_debt_service": round(sched["annual_debt_service"][0], 2),
            "loan_payoff": round(sched["ending_balance"], 2),
            "dscr_year1": round(totals["year1_noi"] / sched["annual_debt_service"][0], 2)
            if sched["annual_debt_service"][0] else None,
            "fund_levered_cash_flow": [round(x, 2) for x in fund_lev],
            "fund_levered_irr": round(fund_irr, 4) if fund_irr is not None else None,
            "equity_multiple": round(total_lev / equity, 3) if equity > 0 else None}
    return out


# --------------------------------------------------------------------------- #
# Sample deal
# --------------------------------------------------------------------------- #

def sample_scenario():
    return {
        "property": {"name": "Harbor Point Office Tower", "property_type": "Office", "total_sf": 100000},
        "analysis": {"start_year": 2026, "start_month": 1, "hold_years": 10, "purchase_price": 28500000,
                     "discount_rate": 0.0825, "exit_cap_rate": 0.0675, "selling_cost_pct": 0.02,
                     "general_vacancy_pct": 0.05, "market_rent_psf": 34.0, "market_rent_growth_pct": 0.03,
                     "expense_gross_up_pct": 0.95, "cpi_rate": 0.025},
        "market_leasing": {"renewal_probability": 0.65, "market_term_years": 7, "renewal_term_years": 5,
                           "downtime_months": 9.0, "renewal_market_rent_psf": 0.0,
                           "new_free_rent_months": 5.0, "renewal_free_rent_months": 1.0,
                           "new_ti_psf": 45.0, "renewal_ti_psf": 15.0, "new_lc_pct": 0.06,
                           "renewal_lc_pct": 0.03, "lc_basis": "percent", "reimbursement_method": "net",
                           "recovery": {}},
        "valuation": {"term_yield": 0.0, "reversion_yield": 0.0, "hardcore_yield": 0.0},
        "leases": [
            {"tenant": "Meridian Capital (Anchor)", "suite_sf": 45000, "start_year": 1, "term_years": 10,
             "base_rent_psf": 33.0, "escalation_type": "fixed", "annual_escalation_pct": 0.03,
             "reimbursement_method": "net"},
            {"tenant": "Lumen Health Systems", "suite_sf": 28000, "start_year": 1, "term_years": 7,
             "base_rent_psf": 31.5, "escalation_type": "cpi", "cpi_rate": 0.025, "free_rent_months": 3,
             "reimbursement_method": "base_stop", "recovery": {"admin_fee_pct": 0.03}},
            {"tenant": "Northwind Advisory", "suite_sf": 15000, "start_year": 1, "term_years": 5,
             "base_rent_psf": 30.0, "escalation_type": "stepped",
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
             "amortization_years": 0, "io": True, "participation_pct": 0.10}]},
    }
