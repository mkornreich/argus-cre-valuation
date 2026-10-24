"""ARGUS-style commercial real estate DCF valuation engine (v3 — monthly).

ARGUS Enterprise is a monthly (internally daily) cash-flow engine. This module
computes the same way: every lease, expense, reimbursement, rollover, downtime
period, free-rent abatement and capital cost is projected on a continuous month
axis with exact proration at lease boundaries, then aggregated to financial
years for reporting. There are no annual shortcuts.

Faithful mechanics implemented here:

* **Monthly cash flow.** Partial months (a lease that commences or expires
  mid-month, fractional downtime from probability weighting) are prorated, not
  rounded to whole years.
* **Market Leasing Assumptions.** On rollover (and day-one vacancy) a space
  re-leases on a renewal-probability-weighted blend of renew vs. new-tenant
  terms — each with its own market rent, lease term, downtime, free rent,
  tenant improvements (TI) and leasing commissions (LC). Re-leasing recurs for
  the whole horizon.
* **Reimbursements.** Per-lease Net / Base-Year Stop / Gross, with the base year
  measured over the lease's own first twelve months (not the calendar year),
  optional occupancy gross-up of variable recoverable expenses, and
  recoverable / non-recoverable expense flags.
* **Percentage rent** over a natural or specified breakpoint (retail).
* **Leasing & capital** (TI, LC, reserves) below NOI; TI/LC land in the month a
  lease commences. In-place leases may carry their own upfront TI/LC.
* **Mid-period timing** via an analysis start month and per-lease start month.
* **Sensitivity** across a discount-rate x exit-cap grid.

All money is in whole dollars; all rates are decimals (0.08 == 8%).
"""

from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
# Financial helpers (no numpy dependency)
# --------------------------------------------------------------------------- #

def npv(rate: float, cash_flows: list[float]) -> float:
    """Net present value of ``cash_flows`` where index 0 occurs at time 0."""
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cash_flows))


def irr(cash_flows: list[float], lo: float = -0.9999, hi: float = 10.0) -> float | None:
    """Internal rate of return via bisection; ``None`` if not bracketable."""
    if not cash_flows or all(cf >= 0 for cf in cash_flows) or all(cf <= 0 for cf in cash_flows):
        return None
    f_lo = npv(lo, cash_flows)
    f_hi = npv(hi, cash_flows)
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


def _mortgage_schedule(principal: float, annual_rate: float, amort_years: int,
                       hold_years: int, interest_only: bool) -> dict[str, Any]:
    """Monthly-amortizing mortgage, aggregated to annual figures."""
    if principal <= 0:
        return {"annual_debt_service": [0.0] * hold_years, "annual_interest": [0.0] * hold_years,
                "annual_principal": [0.0] * hold_years, "ending_balance": 0.0, "monthly_payment": 0.0}

    mr = annual_rate / 12.0
    balance = principal
    if interest_only or amort_years <= 0:
        monthly_payment = balance * mr
        return {"annual_debt_service": [monthly_payment * 12 for _ in range(hold_years)],
                "annual_interest": [balance * annual_rate for _ in range(hold_years)],
                "annual_principal": [0.0] * hold_years, "ending_balance": principal,
                "monthly_payment": monthly_payment}

    n = amort_years * 12
    monthly_payment = principal / n if mr == 0 else principal * mr / (1 - (1 + mr) ** (-n))
    per_int, per_prin, per_ds = [], [], []
    for _ in range(hold_years):
        yr_int = yr_prin = 0.0
        for _m in range(12):
            interest = balance * mr
            principal_paid = min(monthly_payment - interest, balance)
            balance -= principal_paid
            yr_int += interest
            yr_prin += principal_paid
        per_int.append(yr_int)
        per_prin.append(yr_prin)
        per_ds.append(yr_int + yr_prin)
    return {"annual_debt_service": per_ds, "annual_interest": per_int, "annual_principal": per_prin,
            "ending_balance": max(balance, 0.0), "monthly_payment": monthly_payment}


def _overlap(a: float, b: float, c: float, d: float) -> float:
    """Length of the intersection of intervals [a,b) and [c,d), >= 0."""
    return max(0.0, min(b, d) - max(a, c))


# --------------------------------------------------------------------------- #
# Scenario normalization / defaults
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


def _percentage_rent(pr: Any) -> dict | None:
    if not pr:
        return None
    pr = dict(pr)
    sales = _num(pr.get("sales_psf"), 0.0)
    pct = _num(pr.get("percent"), 0.0)
    if sales <= 0 or pct <= 0:
        return None
    return {
        "sales_psf": sales,
        "percent": pct,
        "breakpoint_psf": _num(pr.get("breakpoint_psf"), 0.0),  # 0 -> natural breakpoint
        "sales_growth_pct": _num(pr.get("sales_growth_pct"), 0.0),
    }


def normalize_scenario(scenario: dict | None) -> dict:
    """Fill defaults and coerce types so the engine never sees bad input."""
    scenario = dict(scenario or {})
    prop = dict(scenario.get("property", {}))
    ana = dict(scenario.get("analysis", {}))
    cap = dict(scenario.get("capital", {}))
    debt = dict(scenario.get("debt", {}))
    mla = dict(scenario.get("market_leasing", {}))

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
            "expense_gross_up_pct": _num(ana.get("expense_gross_up_pct"), 0.0),  # 0 -> disabled
        },
        "market_leasing": {
            "renewal_probability": min(max(_num(mla.get("renewal_probability"), 0.65), 0.0), 1.0),
            "market_term_years": max(_num(mla.get("market_term_years"), 5.0), 0.5),
            "renewal_term_years": max(_num(mla.get("renewal_term_years"),
                                            _num(mla.get("market_term_years"), 5.0)), 0.5),
            "downtime_months": max(_num(mla.get("downtime_months"), 9.0), 0.0),
            "renewal_market_rent_psf": _num(mla.get("renewal_market_rent_psf"), 0.0),  # 0 -> = market
            "new_free_rent_months": max(_num(mla.get("new_free_rent_months"), 4.0), 0.0),
            "renewal_free_rent_months": max(_num(mla.get("renewal_free_rent_months"), 1.0), 0.0),
            "new_ti_psf": max(_num(mla.get("new_ti_psf"), 35.0), 0.0),
            "renewal_ti_psf": max(_num(mla.get("renewal_ti_psf"), 12.0), 0.0),
            "new_lc_pct": max(_num(mla.get("new_lc_pct"), 0.06), 0.0),
            "renewal_lc_pct": max(_num(mla.get("renewal_lc_pct"), 0.03), 0.0),
            "reimbursement_method": _reimb_method(mla.get("reimbursement_method"), "net"),
        },
        "leases": [],
        "expenses": [],
        "capital": {
            "reserve_psf": _num(cap.get("reserve_psf"), 0.0),
            "growth_pct": _num(cap.get("growth_pct"), 0.02),
        },
        "debt": {
            "enabled": _bool(debt.get("enabled"), False),
            "ltv_pct": _num(debt.get("ltv_pct"), 0.0),
            "loan_amount": _num(debt.get("loan_amount"), 0.0),
            "interest_rate": _num(debt.get("interest_rate"), 0.065),
            "amortization_years": int(_num(debt.get("amortization_years"), 30)),
            "io": _bool(debt.get("io"), False),
        },
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
            "annual_escalation_pct": _num(lease.get("annual_escalation_pct"), 0.0),
            "free_rent_months": max(_num(lease.get("free_rent_months"), 0.0), 0.0),
            "ti_psf": max(_num(lease.get("ti_psf"), 0.0), 0.0),       # upfront, usually 0 in place
            "lc_pct": max(_num(lease.get("lc_pct"), 0.0), 0.0),
            "reimbursement_method": _reimb_method(lease.get("reimbursement_method"), "net"),
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
# Lease segment model (continuous month axis)
# --------------------------------------------------------------------------- #

def _build_segments(inplace: dict | None, mla: dict, analysis: dict, horizon_m: float) -> list[dict]:
    """Chain of lease segments over the analysis, on a continuous month axis.

    Segment times are floats measured in months from month 0 (the first month
    of the analysis). Market segments use renewal-probability-weighted terms.
    """
    p = mla["renewal_probability"]
    mkt0 = analysis["market_rent_psf"]
    renewal_mkt0 = mla["renewal_market_rent_psf"] or mkt0
    mg = analysis["market_rent_growth_pct"]

    # Weighted "market" lease (renew vs. new blended by renewal probability).
    down_eff = (1 - p) * mla["downtime_months"]                       # months, fractional
    free_eff = p * mla["renewal_free_rent_months"] + (1 - p) * mla["new_free_rent_months"]
    ti_eff = p * mla["renewal_ti_psf"] + (1 - p) * mla["new_ti_psf"]
    lc_eff = p * mla["renewal_lc_pct"] + (1 - p) * mla["new_lc_pct"]
    term_eff_m = (p * mla["renewal_term_years"] + (1 - p) * mla["market_term_years"]) * 12.0
    blended_rent0 = p * renewal_mkt0 + (1 - p) * mkt0

    segs: list[dict] = []
    if inplace:
        start_t = (inplace["start_year"] - 1) * 12.0 + (inplace["start_month"] - 1)
        term_m = inplace["term_years"] * 12.0
        segs.append({
            "start_t": start_t, "term_m": term_m, "end_t": start_t + term_m,
            "rent_psf0": inplace["base_rent_psf"], "esc": inplace["annual_escalation_pct"],
            "is_inplace": True, "free_m": inplace["free_rent_months"], "down_before": 0.0,
            "ti_psf": inplace["ti_psf"], "lc_pct": inplace["lc_pct"],
            "reimb": inplace["reimbursement_method"], "percentage_rent": inplace["percentage_rent"],
        })
        next_start = start_t + term_m + down_eff
    else:
        next_start = down_eff  # vacant space: downtime [0, down_eff) then a market lease

    while next_start < horizon_m and term_eff_m > 0:
        rent_psf0 = blended_rent0 * (1 + mg) ** (next_start / 12.0)
        segs.append({
            "start_t": next_start, "term_m": term_eff_m, "end_t": next_start + term_eff_m,
            "rent_psf0": rent_psf0, "esc": mg, "is_inplace": False,
            "free_m": free_eff, "down_before": down_eff,
            "ti_psf": ti_eff, "lc_pct": lc_eff, "reimb": mla["reimbursement_method"],
            "percentage_rent": None,
        })
        next_start = next_start + term_eff_m + down_eff
    return segs


def _space_month(suite_sf: float, segments: list[dict], m: int, analysis: dict) -> dict:
    """One space's contributions for integer month ``m`` (covering [m, m+1))."""
    lo, hi = float(m), float(m + 1)
    mkt_rate = analysis["market_rent_psf"] * (1 + analysis["market_rent_growth_pct"]) ** (m / 12.0)

    potential = turnover = abate = ti = lc = pct_rent = occ = 0.0
    reimb_terms: list[tuple[float, str, float]] = []  # (occupied_fraction, method, base_month)

    for seg in segments:
        occ_overlap = _overlap(lo, hi, seg["start_t"], seg["end_t"])
        if occ_overlap > 0:
            yrs_in = int((max(lo, seg["start_t"]) - seg["start_t"]) / 12.0 + 1e-9)
            rent_psf = seg["rent_psf0"] * (1 + seg["esc"]) ** yrs_in
            monthly_full = suite_sf * rent_psf / 12.0
            potential += monthly_full * occ_overlap
            abate += monthly_full * _overlap(lo, hi, seg["start_t"], seg["start_t"] + seg["free_m"])
            occ += occ_overlap
            reimb_terms.append((occ_overlap, seg["reimb"], seg["start_t"]))

            pr = seg["percentage_rent"]
            if pr:
                yrs = (max(lo, seg["start_t"])) / 12.0
                sales = pr["sales_psf"] * (1 + pr["sales_growth_pct"]) ** int(yrs)
                bp = pr["breakpoint_psf"] or (rent_psf / pr["percent"] if pr["percent"] else 0.0)
                overage = max(sales - bp, 0.0) * pr["percent"]
                pct_rent += suite_sf * overage / 12.0 * occ_overlap

        vac_overlap = _overlap(lo, hi, seg["start_t"] - seg["down_before"], seg["start_t"])
        if vac_overlap > 0:
            lost = suite_sf * mkt_rate / 12.0 * vac_overlap
            potential += lost
            turnover += lost

        if seg["start_t"] >= 0 and lo <= seg["start_t"] < hi:
            ti += suite_sf * seg["ti_psf"]
            lc += seg["lc_pct"] * (suite_sf * seg["rent_psf0"] * seg["term_m"] / 12.0)

    return {"potential": potential, "turnover": turnover, "abate": abate, "ti": ti, "lc": lc,
            "pct_rent": pct_rent, "occupied_sf": suite_sf * occ, "reimb_terms": reimb_terms}


# --------------------------------------------------------------------------- #
# Expenses (monthly)
# --------------------------------------------------------------------------- #

def _month_expenses(expenses: list[dict], total_sf: float, m: int) -> dict[str, Any]:
    """Monthly expense detail and recoverable pools for integer month ``m``."""
    year = m // 12
    detail: dict[str, float] = {}
    total = recoverable_fixed = recoverable_variable = 0.0
    for exp in expenses:
        annual = exp["amount"] * total_sf if exp["basis"] == "psf" else exp["amount"]
        monthly = annual * (1 + exp["growth_pct"]) ** year / 12.0
        detail[exp["name"]] = detail.get(exp["name"], 0.0) + monthly
        total += monthly
        if exp["recoverable"]:
            if exp["variable"]:
                recoverable_variable += monthly
            else:
                recoverable_fixed += monthly
    return {"detail": detail, "total": total,
            "recoverable_fixed": recoverable_fixed, "recoverable_variable": recoverable_variable}


def _recoverable_pool(expenses: list[dict], total_sf: float, m: int,
                      occupancy: float, gross_up_pct: float) -> float:
    """Recoverable expense pool for reimbursement, variable portion grossed up."""
    e = _month_expenses(expenses, total_sf, m)
    variable = e["recoverable_variable"]
    if gross_up_pct > 0 and 0 < occupancy < gross_up_pct:
        variable *= gross_up_pct / occupancy
    return e["recoverable_fixed"] + variable


# --------------------------------------------------------------------------- #
# Monthly projection
# --------------------------------------------------------------------------- #

def _build_spaces(scenario: dict, horizon_m: float) -> list[dict]:
    total_sf = scenario["property"]["total_sf"]
    mla = scenario["market_leasing"]
    ana = scenario["analysis"]
    spaces = [{"suite_sf": l["suite_sf"], "segments": _build_segments(l, mla, ana, horizon_m)}
              for l in scenario["leases"]]
    vacant_sf = max(total_sf - sum(l["suite_sf"] for l in scenario["leases"]), 0.0)
    if vacant_sf > 0.5 and ana["market_rent_psf"] > 0:
        spaces.append({"suite_sf": vacant_sf, "segments": _build_segments(None, mla, ana, horizon_m)})
    return spaces


def _month_row(scenario: dict, spaces: list[dict], m: int) -> dict[str, Any]:
    """Full ARGUS-style cash flow for a single integer month ``m``."""
    total_sf = scenario["property"]["total_sf"]
    ana = scenario["analysis"]
    exp = _month_expenses(scenario["expenses"], total_sf, m)
    opex_month = exp["total"]

    potential = turnover = abate = ti = lc = pct_rent = occupied_sf = 0.0
    contributions = []
    for sp in spaces:
        c = _space_month(sp["suite_sf"], sp["segments"], m, ana)
        potential += c["potential"]
        turnover += c["turnover"]
        abate += c["abate"]
        ti += c["ti"]
        lc += c["lc"]
        pct_rent += c["pct_rent"]
        occupied_sf += c["occupied_sf"]
        contributions.append((sp, c))

    occupancy = min(occupied_sf / total_sf, 1.0) if total_sf else 0.0

    reimb = 0.0
    for sp, c in contributions:
        share = sp["suite_sf"] / total_sf if total_sf else 0.0
        for frac, method, base_t in c["reimb_terms"]:
            if method == "gross":
                continue
            pool = _recoverable_pool(scenario["expenses"], total_sf, m,
                                     occupancy, ana["expense_gross_up_pct"])
            if method == "net":
                reimb += share * pool * frac
            elif method == "base_stop":
                base_pool = _recoverable_pool(scenario["expenses"], total_sf, int(base_t),
                                              occupancy, ana["expense_gross_up_pct"])
                reimb += share * max(pool - base_pool, 0.0) * frac

    scheduled_base_rent = potential - turnover - abate
    total_tenant_revenue = scheduled_base_rent + reimb + pct_rent
    target_vacancy = ana["general_vacancy_pct"] * potential
    general_vacancy = -max(target_vacancy - turnover, 0.0)
    egr = total_tenant_revenue + general_vacancy
    noi = egr - opex_month
    reserve = total_sf * scenario["capital"]["reserve_psf"] * (1 + scenario["capital"]["growth_pct"]) ** (m // 12) / 12.0
    unlevered_cf = noi - ti - lc - reserve

    return {
        "potential_base_rent": potential,
        "absorption_turnover_vacancy": -turnover,
        "base_rent_abatements": -abate,
        "scheduled_base_rent": scheduled_base_rent,
        "percentage_rent": pct_rent,
        "expense_reimbursements": reimb,
        "total_tenant_revenue": total_tenant_revenue,
        "general_vacancy": general_vacancy,
        "effective_gross_revenue": egr,
        "operating_expenses": -opex_month,
        "operating_expenses_detail": {k: -v for k, v in exp["detail"].items()},
        "noi": noi,
        "tenant_improvements": -ti,
        "leasing_commissions": -lc,
        "capital_reserve": -reserve,
        "unlevered_cash_flow": unlevered_cf,
        "occupancy_pct": occupancy,
    }


_SUM_FIELDS = (
    "potential_base_rent", "absorption_turnover_vacancy", "base_rent_abatements",
    "scheduled_base_rent", "percentage_rent", "expense_reimbursements",
    "total_tenant_revenue", "general_vacancy", "effective_gross_revenue",
    "operating_expenses", "noi", "tenant_improvements", "leasing_commissions",
    "capital_reserve", "unlevered_cash_flow",
)


def _aggregate(monthly: list[dict], start_year: int, year_index: int) -> dict:
    """Sum 12 monthly rows into one financial-year row."""
    agg: dict[str, Any] = {"year_index": year_index, "year": start_year + year_index - 1}
    for f in _SUM_FIELDS:
        agg[f] = round(sum(r[f] for r in monthly), 2)
    detail: dict[str, float] = {}
    for r in monthly:
        for k, v in r["operating_expenses_detail"].items():
            detail[k] = detail.get(k, 0.0) + v
    agg["operating_expenses_detail"] = {k: round(v, 2) for k, v in detail.items()}
    agg["occupancy_pct"] = round(sum(r["occupancy_pct"] for r in monthly) / len(monthly), 4)
    agg["_noi"] = sum(r["noi"] for r in monthly)
    agg["_unlevered_cf"] = sum(r["unlevered_cash_flow"] for r in monthly)
    return agg


def _monthly_label(monthly: list[dict], start_year: int, start_month: int, m: int) -> dict:
    row = dict(monthly[m])
    for f in _SUM_FIELDS + ("occupancy_pct",):
        row[f] = round(row[f], 2) if f != "occupancy_pct" else round(row[f], 4)
    row["operating_expenses_detail"] = {k: round(v, 2) for k, v in row["operating_expenses_detail"].items()}
    month0 = (start_month - 1) + m
    row["year"] = start_year + month0 // 12
    row["month"] = month0 % 12 + 1
    row["period"] = f"{row['year']}-{row['month']:02d}"
    return row


# --------------------------------------------------------------------------- #
# Valuation
# --------------------------------------------------------------------------- #

def _project_and_value(scenario: dict, include_monthly: bool = False) -> dict:
    ana = scenario["analysis"]
    hold = ana["hold_years"]
    price = ana["purchase_price"]
    total_sf = scenario["property"]["total_sf"]

    months = (hold + 1) * 12  # one extra year for forward NOI
    spaces = _build_spaces(scenario, float(months))
    monthly = [_month_row(scenario, spaces, m) for m in range(months)]

    projection = [_aggregate(monthly[y * 12:(y + 1) * 12], ana["start_year"], y + 1)
                  for y in range(hold)]
    forward_noi = sum(r["noi"] for r in monthly[hold * 12:(hold + 1) * 12])

    exit_cap = ana["exit_cap_rate"]
    terminal_value = forward_noi / exit_cap if exit_cap > 0 else 0.0
    net_reversion = terminal_value * (1 - ana["selling_cost_pct"])

    d = ana["discount_rate"]
    pv_operations = sum(row["_unlevered_cf"] / (1 + d) ** (i + 1) for i, row in enumerate(projection))
    dcf_value = pv_operations + net_reversion / (1 + d) ** hold

    unlevered_flows = [row["_unlevered_cf"] for row in projection]
    unlevered_flows[-1] += net_reversion
    unlevered_irr = irr([-price] + unlevered_flows) if price > 0 else None
    total_unlevered = sum(row["_unlevered_cf"] for row in projection) + net_reversion
    equity_multiple_unlevered = (total_unlevered / price) if price > 0 else None

    year1_noi = projection[0]["_noi"]
    going_in_cap = (year1_noi / price) if price > 0 else None

    metrics: dict[str, Any] = {
        "purchase_price": round(price, 2),
        "price_per_sf": round(price / total_sf, 2) if total_sf else None,
        "year1_noi": round(year1_noi, 2),
        "forward_noi": round(forward_noi, 2),
        "going_in_cap_rate": round(going_in_cap, 4) if going_in_cap is not None else None,
        "exit_cap_rate": exit_cap,
        "discount_rate": d,
        "terminal_value": round(terminal_value, 2),
        "net_reversion": round(net_reversion, 2),
        "dcf_value": round(dcf_value, 2),
        "dcf_value_per_sf": round(dcf_value / total_sf, 2) if total_sf else None,
        "npv": round(dcf_value - price, 2) if price > 0 else round(dcf_value, 2),
        "unlevered_irr": round(unlevered_irr, 4) if unlevered_irr is not None else None,
        "equity_multiple_unlevered": (round(equity_multiple_unlevered, 3)
                                      if equity_multiple_unlevered is not None else None),
        "total_leasing_capital": round(
            sum(row["tenant_improvements"] + row["leasing_commissions"] + row["capital_reserve"]
                for row in projection), 2),
    }

    debt = scenario["debt"]
    if debt["enabled"]:
        loan_amount = debt["loan_amount"] or (debt["ltv_pct"] * price)
        sched = _mortgage_schedule(loan_amount, debt["interest_rate"],
                                   debt["amortization_years"], hold, debt["io"])
        equity = price - loan_amount
        levered_flows, cash_on_cash = [], []
        for i, row in enumerate(projection):
            ds = sched["annual_debt_service"][i]
            lcf = row["_unlevered_cf"] - ds
            row["debt_service"] = round(-ds, 2)
            row["levered_cash_flow"] = round(lcf, 2)
            levered_flows.append(lcf)
            cash_on_cash.append((lcf / equity) if equity > 0 else 0.0)
        payoff = sched["ending_balance"]
        net_equity_reversion = net_reversion - payoff
        levered_flows[-1] += net_equity_reversion
        levered_irr = irr([-equity] + levered_flows) if equity > 0 else None
        total_levered = sum(row["levered_cash_flow"] for row in projection) + net_equity_reversion
        metrics["debt"] = {
            "loan_amount": round(loan_amount, 2), "equity_invested": round(equity, 2),
            "ltv_pct": round(loan_amount / price, 4) if price > 0 else None,
            "interest_rate": debt["interest_rate"],
            "monthly_payment": round(sched["monthly_payment"], 2),
            "annual_debt_service": round(sched["annual_debt_service"][0], 2),
            "dscr_year1": round(year1_noi / sched["annual_debt_service"][0], 2)
            if sched["annual_debt_service"][0] else None,
            "loan_payoff": round(payoff, 2), "net_equity_reversion": round(net_equity_reversion, 2),
            "levered_irr": round(levered_irr, 4) if levered_irr is not None else None,
            "equity_multiple_levered": round(total_levered / equity, 3) if equity > 0 else None,
            "avg_cash_on_cash": round(sum(cash_on_cash) / len(cash_on_cash), 4) if cash_on_cash else None,
        }
        monthly_ds = sched["monthly_payment"]
    else:
        monthly_ds = 0.0

    for row in projection:
        row.pop("_noi", None)
        row.pop("_unlevered_cf", None)

    result = {
        "property": scenario["property"],
        "assumptions": ana,
        "market_leasing": scenario["market_leasing"],
        "years": [row["year"] for row in projection],
        "cash_flow": projection,
        "metrics": metrics,
    }
    if include_monthly:
        labelled = [_monthly_label(monthly, ana["start_year"], ana["start_month"], m)
                    for m in range(hold * 12)]
        if debt["enabled"]:
            for r in labelled:
                r["debt_service"] = round(-monthly_ds, 2)
                r["levered_cash_flow"] = round(r["unlevered_cash_flow"] - monthly_ds, 2)
        result["monthly_cash_flow"] = labelled
    return result


def _sensitivity(scenario: dict) -> dict:
    ana = scenario["analysis"]
    d0, c0 = ana["discount_rate"], ana["exit_cap_rate"]
    d_axis = [round(d0 + s, 4) for s in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    c_axis = [round(c0 + s, 4) for s in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    value_grid, irr_grid = [], []
    for d in d_axis:
        v_row, i_row = [], []
        for c in c_axis:
            if c <= 0:
                v_row.append(None)
                i_row.append(None)
                continue
            s = {**scenario, "analysis": {**ana, "discount_rate": d, "exit_cap_rate": c}}
            r = _project_and_value(s)
            v_row.append(r["metrics"]["dcf_value"])
            i_row.append(r["metrics"]["unlevered_irr"])
        value_grid.append(v_row)
        irr_grid.append(i_row)
    return {"discount_rates": d_axis, "exit_cap_rates": c_axis,
            "dcf_value": value_grid, "unlevered_irr": irr_grid}


def analyze(scenario: dict | None, with_sensitivity: bool = True,
            include_monthly: bool = True) -> dict:
    """Run a full ARGUS-style valuation and return projection + metrics."""
    scenario = normalize_scenario(scenario)
    result = _project_and_value(scenario, include_monthly=include_monthly)
    if with_sensitivity:
        result["sensitivity"] = _sensitivity(scenario)
    return result


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
            "expense_gross_up_pct": 0.95,
        },
        "market_leasing": {
            "renewal_probability": 0.65, "market_term_years": 7, "renewal_term_years": 5,
            "downtime_months": 9.0, "renewal_market_rent_psf": 0.0,
            "new_free_rent_months": 5.0, "renewal_free_rent_months": 1.0,
            "new_ti_psf": 45.0, "renewal_ti_psf": 15.0,
            "new_lc_pct": 0.06, "renewal_lc_pct": 0.03, "reimbursement_method": "net",
        },
        "leases": [
            {"tenant": "Meridian Capital (Anchor)", "suite_sf": 45000, "start_year": 1,
             "term_years": 10, "base_rent_psf": 33.0, "annual_escalation_pct": 0.03,
             "free_rent_months": 0, "reimbursement_method": "net"},
            {"tenant": "Lumen Health Systems", "suite_sf": 28000, "start_year": 1,
             "term_years": 7, "base_rent_psf": 31.5, "annual_escalation_pct": 0.025,
             "free_rent_months": 3, "reimbursement_method": "base_stop"},
            {"tenant": "Northwind Advisory", "suite_sf": 15000, "start_year": 1,
             "term_years": 5, "base_rent_psf": 30.0, "annual_escalation_pct": 0.03,
             "free_rent_months": 0, "reimbursement_method": "net"},
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
        "debt": {"enabled": True, "ltv_pct": 0.60, "loan_amount": 0,
                 "interest_rate": 0.0625, "amortization_years": 30, "io": False},
    }
