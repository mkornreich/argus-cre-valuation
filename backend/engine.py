"""ARGUS-style commercial real estate DCF valuation engine (v2).

This module is a self-contained, dependency-free financial model that mirrors
the core of what ARGUS Enterprise does. Compared with a naive proforma it adds
the features that actually define ARGUS:

* **Market Leasing Assumptions (MLAs).** When an in-place lease expires inside
  the hold, the space re-leases on a renewal-probability-weighted blend of
  "renew" and "new tenant" outcomes — each with its own downtime, free rent,
  tenant improvements (TI) and leasing commissions (LC). Space re-leases
  recursively for the length of the analysis.
* **Absorption & turnover vacancy.** Downtime on rollover is an explicit line,
  and general vacancy is netted against it (ARGUS convention) to avoid double
  counting.
* **Reimbursement methods.** Each lease recovers operating expenses as Net
  (pro-rata share), Base-Year Stop (share of the increase over a base year) or
  Gross (none).
* **Leasing & capital costs below NOI.** TI, LC and capital reserves reduce the
  unlevered cash flow, exactly as in an ARGUS cash flow.
* **Sensitivity analysis.** A discount-rate x exit-cap grid of value and IRR.

All money is in whole dollars; all rates are decimals (0.08 == 8%).
The scenario schema is documented in ``sample_scenario()``.
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
    """Internal rate of return via bisection.

    Returns ``None`` when there is no sign change (no conventional IRR) or the
    root cannot be bracketed in ``[lo, hi]``.
    """
    if not cash_flows or all(cf >= 0 for cf in cash_flows) or all(cf <= 0 for cf in cash_flows):
        return None

    f_lo = npv(lo, cash_flows)
    f_hi = npv(hi, cash_flows)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if (f_lo > 0) == (f_hi > 0):
        return None  # root not bracketed

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
        return {
            "annual_debt_service": [0.0] * hold_years,
            "annual_interest": [0.0] * hold_years,
            "annual_principal": [0.0] * hold_years,
            "ending_balance": 0.0,
            "monthly_payment": 0.0,
        }

    mr = annual_rate / 12.0
    balance = principal

    if interest_only or amort_years <= 0:
        monthly_payment = balance * mr
        return {
            "annual_debt_service": [monthly_payment * 12 for _ in range(hold_years)],
            "annual_interest": [balance * annual_rate for _ in range(hold_years)],
            "annual_principal": [0.0] * hold_years,
            "ending_balance": principal,
            "monthly_payment": monthly_payment,
        }

    n = amort_years * 12
    monthly_payment = principal / n if mr == 0 else principal * mr / (1 - (1 + mr) ** (-n))

    per_year_interest: list[float] = []
    per_year_principal: list[float] = []
    per_year_ds: list[float] = []
    for _ in range(hold_years):
        yr_int = yr_prin = 0.0
        for _m in range(12):
            interest = balance * mr
            principal_paid = min(monthly_payment - interest, balance)
            balance -= principal_paid
            yr_int += interest
            yr_prin += principal_paid
        per_year_interest.append(yr_int)
        per_year_principal.append(yr_prin)
        per_year_ds.append(yr_int + yr_prin)

    return {
        "annual_debt_service": per_year_ds,
        "annual_interest": per_year_interest,
        "annual_principal": per_year_principal,
        "ending_balance": max(balance, 0.0),
        "monthly_payment": monthly_payment,
    }


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


_REIMB = ("net", "base_stop", "gross")


def _reimb_method(value: Any, default: str = "net") -> str:
    v = str(value or default).lower().replace("-", "_").replace(" ", "_")
    return v if v in _REIMB else default


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
            "hold_years": max(int(_num(ana.get("hold_years"), 10)), 1),
            "purchase_price": _num(ana.get("purchase_price"), 0.0),
            "discount_rate": _num(ana.get("discount_rate"), 0.08),
            "exit_cap_rate": _num(ana.get("exit_cap_rate"), 0.065),
            "selling_cost_pct": _num(ana.get("selling_cost_pct"), 0.02),
            "general_vacancy_pct": _num(ana.get("general_vacancy_pct"), 0.05),
            "market_rent_psf": _num(ana.get("market_rent_psf"), 0.0),
            "market_rent_growth_pct": _num(ana.get("market_rent_growth_pct"), 0.03),
        },
        "market_leasing": {
            "renewal_probability": min(max(_num(mla.get("renewal_probability"), 0.65), 0.0), 1.0),
            "market_term_years": max(int(_num(mla.get("market_term_years"), 5)), 1),
            "downtime_months": max(_num(mla.get("downtime_months"), 9.0), 0.0),
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
            "enabled": bool(debt.get("enabled", False)),
            "ltv_pct": _num(debt.get("ltv_pct"), 0.0),
            "loan_amount": _num(debt.get("loan_amount"), 0.0),
            "interest_rate": _num(debt.get("interest_rate"), 0.065),
            "amortization_years": int(_num(debt.get("amortization_years"), 30)),
            "io": bool(debt.get("io", False)),
        },
    }

    for lease in scenario.get("leases", []) or []:
        lease = dict(lease)
        norm["leases"].append({
            "tenant": str(lease.get("tenant") or "Tenant"),
            "suite_sf": max(_num(lease.get("suite_sf"), 0.0), 0.0),
            "start_year": max(int(_num(lease.get("start_year"), 1)), 1),
            "term_years": max(int(_num(lease.get("term_years"), 1)), 1),
            "base_rent_psf": _num(lease.get("base_rent_psf"), 0.0),
            "annual_escalation_pct": _num(lease.get("annual_escalation_pct"), 0.0),
            "free_rent_months": max(_num(lease.get("free_rent_months"), 0.0), 0.0),
            "reimbursement_method": _reimb_method(lease.get("reimbursement_method"), "net"),
        })

    for exp in scenario.get("expenses", []) or []:
        exp = dict(exp)
        basis = str(exp.get("basis") or "psf").lower()
        norm["expenses"].append({
            "name": str(exp.get("name") or "Expense"),
            "amount": _num(exp.get("amount"), 0.0),
            "basis": basis if basis in ("psf", "total") else "psf",
            "growth_pct": _num(exp.get("growth_pct"), 0.0),
        })

    return norm


# --------------------------------------------------------------------------- #
# Lease segment model (in-place lease + recursive market re-leasing)
# --------------------------------------------------------------------------- #

def _effective_mla(mla: dict) -> dict:
    """Renewal-probability-weighted blend of renew vs. new-tenant assumptions.

    Renewing tenants carry no downtime; new tenants bring the full downtime.
    """
    p = mla["renewal_probability"]
    return {
        "downtime_months": (1 - p) * mla["downtime_months"],
        "free_rent_months": p * mla["renewal_free_rent_months"]
        + (1 - p) * mla["new_free_rent_months"],
        "ti_psf": p * mla["renewal_ti_psf"] + (1 - p) * mla["new_ti_psf"],
        "lc_pct": p * mla["renewal_lc_pct"] + (1 - p) * mla["new_lc_pct"],
        "term_years": mla["market_term_years"],
        "reimbursement_method": mla["reimbursement_method"],
    }


def _build_segments(inplace: dict | None, mla: dict, analysis: dict, n_years: int) -> list[dict]:
    """Build the chain of lease segments covering a space over the analysis.

    A segment is one lease: the in-place lease first (if any), then a chain of
    market leases, each commencing the year after the prior one expires.
    """
    eff = _effective_mla(mla)
    mkt0 = analysis["market_rent_psf"]
    mg = analysis["market_rent_growth_pct"]

    segments: list[dict] = []
    if inplace:
        s = inplace["start_year"]
        segments.append({
            "commence": s,
            "end": s + inplace["term_years"] - 1,
            "rent_psf": inplace["base_rent_psf"],
            "escalation": inplace["annual_escalation_pct"],
            "is_inplace": True,
            "free_months": inplace["free_rent_months"],
            "downtime_months": 0.0,
            "ti_psf": 0.0,          # in-place TI assumed spent pre-acquisition
            "lc_pct": 0.0,
            "term_years": inplace["term_years"],
            "reimbursement_method": inplace["reimbursement_method"],
        })
        next_commence = segments[-1]["end"] + 1
    else:
        next_commence = 1  # vacant space leases up at the start

    # Market re-leasing chain for the remainder of the analysis.
    while next_commence <= n_years:
        c = next_commence
        rent_c = mkt0 * (1 + mg) ** (c - 1)
        term = eff["term_years"]
        segments.append({
            "commence": c,
            "end": c + term - 1,
            "rent_psf": rent_c,
            "escalation": mg,
            "is_inplace": False,
            "free_months": eff["free_rent_months"],
            "downtime_months": eff["downtime_months"],
            "ti_psf": eff["ti_psf"],
            "lc_pct": eff["lc_pct"],
            "term_years": term,
            "reimbursement_method": eff["reimbursement_method"],
        })
        next_commence = c + term

    return segments


def _space_year(suite_sf: float, segments: list[dict], year_index: int) -> dict:
    """Per-space line-item contributions for one analysis year."""
    seg = next((s for s in segments if s["commence"] <= year_index <= s["end"]), None)
    blank = {
        "potential_base_rent": 0.0, "turnover_vacancy": 0.0, "abatement": 0.0,
        "ti": 0.0, "lc": 0.0, "occupied_fraction": 0.0,
        "reimb_method": "gross", "lease_commence": year_index,
    }
    if seg is None:
        return blank

    years_in = year_index - seg["commence"]
    rent_psf = seg["rent_psf"] * (1 + seg["escalation"]) ** years_in
    potential = suite_sf * rent_psf

    turnover = abate = ti = lc = 0.0
    occupied_fraction = 1.0
    if year_index == seg["commence"]:
        down_frac = min(seg["downtime_months"] / 12.0, 1.0)
        free_frac = min(seg["free_months"] / 12.0, 1.0 - down_frac)
        turnover = potential * down_frac
        abate = potential * free_frac
        occupied_fraction = 1.0 - down_frac
        ti = suite_sf * seg["ti_psf"]
        # LC as a percent of total base rent over the lease term.
        lc = seg["lc_pct"] * (suite_sf * seg["rent_psf"] * seg["term_years"])

    return {
        "potential_base_rent": potential,
        "turnover_vacancy": turnover,
        "abatement": abate,
        "ti": ti,
        "lc": lc,
        "occupied_fraction": occupied_fraction,
        "reimb_method": seg["reimbursement_method"],
        "lease_commence": seg["commence"],
    }


# --------------------------------------------------------------------------- #
# Operating projection
# --------------------------------------------------------------------------- #

def _year_expenses(expenses: list[dict], total_sf: float, year_index: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for exp in expenses:
        base = exp["amount"] * total_sf if exp["basis"] == "psf" else exp["amount"]
        out[exp["name"]] = base * (1 + exp["growth_pct"]) ** (year_index - 1)
    return out


def _total_opex(expenses: list[dict], total_sf: float, year_index: int) -> float:
    return sum(_year_expenses(expenses, total_sf, year_index).values())


def _build_spaces(scenario: dict, n_years: int) -> list[dict]:
    """Define the rentable spaces: one per in-place lease, plus initial vacancy."""
    total_sf = scenario["property"]["total_sf"]
    mla = scenario["market_leasing"]
    ana = scenario["analysis"]

    spaces = []
    for lease in scenario["leases"]:
        spaces.append({
            "suite_sf": lease["suite_sf"],
            "segments": _build_segments(lease, mla, ana, n_years),
        })

    leased_sf = sum(l["suite_sf"] for l in scenario["leases"])
    vacant_sf = max(total_sf - leased_sf, 0.0)
    if vacant_sf > 0.5 and ana["market_rent_psf"] > 0:
        # Initial vacancy leases up at market under the MLA profile.
        spaces.append({
            "suite_sf": vacant_sf,
            "segments": _build_segments(None, mla, ana, n_years),
        })
    return spaces


def _operating_year(scenario: dict, spaces: list[dict], year_index: int) -> dict[str, Any]:
    """Compute one year's full ARGUS-style cash flow statement."""
    total_sf = scenario["property"]["total_sf"]
    ana = scenario["analysis"]
    opex_year = _total_opex(scenario["expenses"], total_sf, year_index)

    potential = turnover = abatement = reimb = ti = lc = occupied_sf = 0.0
    for sp in spaces:
        c = _space_year(sp["suite_sf"], sp["segments"], year_index)
        potential += c["potential_base_rent"]
        turnover += c["turnover_vacancy"]
        abatement += c["abatement"]
        ti += c["ti"]
        lc += c["lc"]
        occupied_sf += sp["suite_sf"] * c["occupied_fraction"]

        share = sp["suite_sf"] / total_sf if total_sf else 0.0
        method = c["reimb_method"]
        if method == "net":
            reimb += share * opex_year * c["occupied_fraction"]
        elif method == "base_stop":
            base_opex = _total_opex(scenario["expenses"], total_sf, c["lease_commence"])
            reimb += share * max(opex_year - base_opex, 0.0) * c["occupied_fraction"]
        # gross -> no reimbursement

    scheduled_base_rent = potential - turnover - abatement
    total_tenant_revenue = scheduled_base_rent + reimb

    # General vacancy is netted against absorption & turnover vacancy already
    # recognized, so the two don't double-count (ARGUS convention).
    target_vacancy = ana["general_vacancy_pct"] * potential
    general_vacancy = -max(target_vacancy - turnover, 0.0)
    egr = total_tenant_revenue + general_vacancy

    expense_detail = _year_expenses(scenario["expenses"], total_sf, year_index)
    operating_expenses = -opex_year
    noi = egr + operating_expenses

    reserve = -(total_sf * scenario["capital"]["reserve_psf"]
                * (1 + scenario["capital"]["growth_pct"]) ** (year_index - 1))
    unlevered_cf = noi - ti - lc + reserve

    occupancy = min(occupied_sf / total_sf, 1.0) if total_sf else 0.0

    return {
        "year_index": year_index,
        "year": ana["start_year"] + year_index - 1,
        "potential_base_rent": round(potential, 2),
        "absorption_turnover_vacancy": round(-turnover, 2),
        "base_rent_abatements": round(-abatement, 2),
        "scheduled_base_rent": round(scheduled_base_rent, 2),
        "expense_reimbursements": round(reimb, 2),
        "total_tenant_revenue": round(total_tenant_revenue, 2),
        "general_vacancy": round(general_vacancy, 2),
        "effective_gross_revenue": round(egr, 2),
        "operating_expenses": round(operating_expenses, 2),
        "operating_expenses_detail": {k: round(v, 2) for k, v in expense_detail.items()},
        "noi": round(noi, 2),
        "tenant_improvements": round(-ti, 2),
        "leasing_commissions": round(-lc, 2),
        "capital_reserve": round(reserve, 2),
        "unlevered_cash_flow": round(unlevered_cf, 2),
        "occupancy_pct": round(occupancy, 4),
        "_noi": noi,
        "_unlevered_cf": unlevered_cf,
    }


# --------------------------------------------------------------------------- #
# Valuation
# --------------------------------------------------------------------------- #

def _project_and_value(scenario: dict) -> dict:
    """Core projection + valuation (no sensitivity grid)."""
    ana = scenario["analysis"]
    hold = ana["hold_years"]
    price = ana["purchase_price"]
    total_sf = scenario["property"]["total_sf"]

    spaces = _build_spaces(scenario, hold + 1)
    rows = [_operating_year(scenario, spaces, y) for y in range(1, hold + 2)]
    projection = rows[:hold]
    forward_noi = rows[hold]["_noi"]

    exit_cap = ana["exit_cap_rate"]
    terminal_value = forward_noi / exit_cap if exit_cap > 0 else 0.0
    net_reversion = terminal_value * (1 - ana["selling_cost_pct"])

    d = ana["discount_rate"]
    pv_operations = sum(row["_unlevered_cf"] / (1 + d) ** (i + 1)
                        for i, row in enumerate(projection))
    pv_reversion = net_reversion / (1 + d) ** hold
    dcf_value = pv_operations + pv_reversion

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
            "loan_amount": round(loan_amount, 2),
            "equity_invested": round(equity, 2),
            "ltv_pct": round(loan_amount / price, 4) if price > 0 else None,
            "interest_rate": debt["interest_rate"],
            "monthly_payment": round(sched["monthly_payment"], 2),
            "annual_debt_service": round(sched["annual_debt_service"][0], 2),
            "dscr_year1": round(year1_noi / sched["annual_debt_service"][0], 2)
            if sched["annual_debt_service"][0] else None,
            "loan_payoff": round(payoff, 2),
            "net_equity_reversion": round(net_equity_reversion, 2),
            "levered_irr": round(levered_irr, 4) if levered_irr is not None else None,
            "equity_multiple_levered": round(total_levered / equity, 3) if equity > 0 else None,
            "avg_cash_on_cash": round(sum(cash_on_cash) / len(cash_on_cash), 4)
            if cash_on_cash else None,
        }

    for row in projection:
        row.pop("_noi", None)
        row.pop("_unlevered_cf", None)

    return {
        "property": scenario["property"],
        "assumptions": ana,
        "market_leasing": scenario["market_leasing"],
        "years": [row["year"] for row in projection],
        "cash_flow": projection,
        "metrics": metrics,
    }


def _sensitivity(scenario: dict) -> dict:
    """Discount-rate x exit-cap grid of DCF value and unlevered IRR."""
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

    return {
        "discount_rates": d_axis,
        "exit_cap_rates": c_axis,
        "dcf_value": value_grid,
        "unlevered_irr": irr_grid,
    }


def analyze(scenario: dict | None, with_sensitivity: bool = True) -> dict:
    """Run a full ARGUS-style valuation and return projection + metrics."""
    scenario = normalize_scenario(scenario)
    result = _project_and_value(scenario)
    if with_sensitivity:
        result["sensitivity"] = _sensitivity(scenario)
    return result


# --------------------------------------------------------------------------- #
# Sample deal
# --------------------------------------------------------------------------- #

def sample_scenario() -> dict:
    """A representative 100,000 SF office deal used as the default scenario.

    The rent roll holds only the *in-place* leases; the engine re-leases each
    space at expiry (and the 12,000 SF of day-one vacancy) under the market
    leasing assumptions below.
    """
    return {
        "property": {
            "name": "Harbor Point Office Tower",
            "property_type": "Office",
            "total_sf": 100000,
        },
        "analysis": {
            "start_year": 2026,
            "hold_years": 10,
            "purchase_price": 28500000,
            "discount_rate": 0.0825,
            "exit_cap_rate": 0.0675,
            "selling_cost_pct": 0.02,
            "general_vacancy_pct": 0.05,
            "market_rent_psf": 34.0,
            "market_rent_growth_pct": 0.03,
        },
        "market_leasing": {
            "renewal_probability": 0.65,
            "market_term_years": 7,
            "downtime_months": 9.0,
            "new_free_rent_months": 5.0,
            "renewal_free_rent_months": 1.0,
            "new_ti_psf": 45.0,
            "renewal_ti_psf": 15.0,
            "new_lc_pct": 0.06,
            "renewal_lc_pct": 0.03,
            "reimbursement_method": "net",
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
            {"name": "Property Taxes", "amount": 5.25, "basis": "psf", "growth_pct": 0.025},
            {"name": "Insurance", "amount": 1.10, "basis": "psf", "growth_pct": 0.03},
            {"name": "Utilities", "amount": 2.40, "basis": "psf", "growth_pct": 0.03},
            {"name": "Repairs & Maintenance", "amount": 2.10, "basis": "psf", "growth_pct": 0.03},
            {"name": "Management Fee", "amount": 1.95, "basis": "psf", "growth_pct": 0.03},
            {"name": "General & Administrative", "amount": 0.85, "basis": "psf", "growth_pct": 0.025},
        ],
        "capital": {"reserve_psf": 0.25, "growth_pct": 0.025},
        "debt": {
            "enabled": True, "ltv_pct": 0.60, "loan_amount": 0,
            "interest_rate": 0.0625, "amortization_years": 30, "io": False,
        },
    }
