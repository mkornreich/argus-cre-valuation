"""ARGUS-style commercial real estate DCF valuation engine.

This module is a self-contained, dependency-free financial model that mirrors
the core of what ARGUS does: it takes a property, a lease-by-lease rent roll,
operating expenses, capital reserves and (optionally) debt, projects an annual
cash flow over a hold period, and values the asset with a direct-cap terminal
value and a discounted-cash-flow (DCF) analysis.

All money is in whole dollars; all rates are decimals (0.08 == 8%).

The scenario schema is documented in ``sample_scenario()`` and validated by
``normalize_scenario()``.
"""

from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
# Small financial helpers (no numpy dependency)
# --------------------------------------------------------------------------- #

def npv(rate: float, cash_flows: list[float]) -> float:
    """Net present value of ``cash_flows`` where index 0 occurs at time 0."""
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cash_flows))


def irr(cash_flows: list[float], lo: float = -0.9999, hi: float = 10.0) -> float | None:
    """Internal rate of return via bisection.

    Returns ``None`` when there is no sign change (no conventional IRR) or the
    root cannot be bracketed in ``[lo, hi]`` (e.g. returns above 1000%).
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
    """Monthly-amortizing mortgage, aggregated to annual figures.

    Returns per-year interest, principal and debt service for ``hold_years``
    plus the loan balance remaining at the end of the hold (the payoff).
    """
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
        per_year_interest = [balance * annual_rate for _ in range(hold_years)]
        per_year_principal = [0.0] * hold_years
        per_year_ds = [monthly_payment * 12 for _ in range(hold_years)]
        return {
            "annual_debt_service": per_year_ds,
            "annual_interest": per_year_interest,
            "annual_principal": per_year_principal,
            "ending_balance": principal,
            "monthly_payment": monthly_payment,
        }

    n = amort_years * 12
    if mr == 0:
        monthly_payment = principal / n
    else:
        monthly_payment = principal * mr / (1 - (1 + mr) ** (-n))

    per_year_interest: list[float] = []
    per_year_principal: list[float] = []
    per_year_ds: list[float] = []
    for _ in range(hold_years):
        yr_int = 0.0
        yr_prin = 0.0
        for _m in range(12):
            interest = balance * mr
            principal_paid = monthly_payment - interest
            if principal_paid > balance:  # final payment
                principal_paid = balance
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


def normalize_scenario(scenario: dict | None) -> dict:
    """Fill defaults and coerce types so the engine never sees bad input."""
    scenario = dict(scenario or {})
    prop = dict(scenario.get("property", {}))
    ana = dict(scenario.get("analysis", {}))
    cap = dict(scenario.get("capital", {}))
    debt = dict(scenario.get("debt", {}))

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
            "recovery_psf": _num(lease.get("recovery_psf"), 0.0),
            "free_rent_months": max(int(_num(lease.get("free_rent_months"), 0)), 0),
        })

    for exp in scenario.get("expenses", []) or []:
        exp = dict(exp)
        basis = str(exp.get("basis") or "psf").lower()
        if basis not in ("psf", "total"):
            basis = "psf"
        norm["expenses"].append({
            "name": str(exp.get("name") or "Expense"),
            "amount": _num(exp.get("amount"), 0.0),
            "basis": basis,
            "growth_pct": _num(exp.get("growth_pct"), 0.0),
        })

    return norm


# --------------------------------------------------------------------------- #
# Core projection
# --------------------------------------------------------------------------- #

def _lease_rent(lease: dict, year_index: int) -> float:
    """Contract base rent for ``lease`` in analysis ``year_index`` (1-based)."""
    start = lease["start_year"]
    end = start + lease["term_years"] - 1
    if year_index < start or year_index > end:
        return 0.0
    years_elapsed = year_index - start
    annual = (lease["suite_sf"] * lease["base_rent_psf"]
              * (1 + lease["annual_escalation_pct"]) ** years_elapsed)
    # First-year free rent reduces the opening year pro-rata.
    if years_elapsed == 0 and lease["free_rent_months"] > 0:
        annual *= max(0.0, (12 - lease["free_rent_months"]) / 12.0)
    return annual


def _lease_recovery(lease: dict, year_index: int) -> float:
    start = lease["start_year"]
    end = start + lease["term_years"] - 1
    if year_index < start or year_index > end:
        return 0.0
    years_elapsed = year_index - start
    # Recoveries grow with the same escalator as a simplification.
    return (lease["suite_sf"] * lease["recovery_psf"]
            * (1 + lease["annual_escalation_pct"]) ** years_elapsed)


def _leased_sf(leases: list[dict], year_index: int) -> float:
    total = 0.0
    for lease in leases:
        start = lease["start_year"]
        end = start + lease["term_years"] - 1
        if start <= year_index <= end:
            total += lease["suite_sf"]
    return total


def _year_expenses(expenses: list[dict], total_sf: float, year_index: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for exp in expenses:
        base = exp["amount"] * total_sf if exp["basis"] == "psf" else exp["amount"]
        out[exp["name"]] = base * (1 + exp["growth_pct"]) ** (year_index - 1)
    return out


def _operating_year(scenario: dict, year_index: int) -> dict[str, Any]:
    """Compute one year's operating statement down to NOI and unlevered CF."""
    total_sf = scenario["property"]["total_sf"]
    ana = scenario["analysis"]

    base_rent = sum(_lease_rent(l, year_index) for l in scenario["leases"])
    reimbursements = sum(_lease_recovery(l, year_index) for l in scenario["leases"])

    # Space not covered by an in-place lease is assumed to (re-)lease at market
    # rent. This is the standard going-concern assumption: without it, a deal
    # where every lease rolls before the exit would value the building at zero.
    # Turnover/downtime on that space is approximated by the general vacancy &
    # credit-loss allowance below.
    leased_sf = _leased_sf(scenario["leases"], year_index)
    vacant_sf = max(total_sf - leased_sf, 0.0)
    market_rent = (ana["market_rent_psf"]
                   * (1 + ana["market_rent_growth_pct"]) ** (year_index - 1))
    market_rent_on_vacant = vacant_sf * market_rent

    potential_gross = base_rent + market_rent_on_vacant + reimbursements

    general_vacancy = -potential_gross * ana["general_vacancy_pct"]
    egi = potential_gross + general_vacancy

    expense_detail = _year_expenses(scenario["expenses"], total_sf, year_index)
    operating_expenses = -sum(expense_detail.values())
    noi = egi + operating_expenses

    reserve = -(total_sf * scenario["capital"]["reserve_psf"]
                * (1 + scenario["capital"]["growth_pct"]) ** (year_index - 1))
    unlevered_cf = noi + reserve

    occupancy = min(leased_sf / total_sf, 1.0) if total_sf else 0.0

    return {
        "year_index": year_index,
        "year": ana["start_year"] + year_index - 1,
        "base_rental_revenue": round(base_rent, 2),
        "market_rent_on_vacant": round(market_rent_on_vacant, 2),
        "expense_reimbursements": round(reimbursements, 2),
        "potential_gross_revenue": round(potential_gross, 2),
        "general_vacancy": round(general_vacancy, 2),
        "effective_gross_revenue": round(egi, 2),
        "operating_expenses": round(operating_expenses, 2),
        "operating_expenses_detail": {k: round(v, 2) for k, v in expense_detail.items()},
        "noi": round(noi, 2),
        "capital_reserve": round(reserve, 2),
        "unlevered_cash_flow": round(unlevered_cf, 2),
        "occupancy_pct": round(occupancy, 4),
        # raw (unrounded) values for internal math
        "_noi": noi,
        "_unlevered_cf": unlevered_cf,
    }


def analyze(scenario: dict | None) -> dict:
    """Run a full ARGUS-style valuation and return projection + metrics."""
    scenario = normalize_scenario(scenario)
    ana = scenario["analysis"]
    hold = ana["hold_years"]
    price = ana["purchase_price"]
    total_sf = scenario["property"]["total_sf"]

    # Project one extra year so the terminal value can use forward NOI.
    rows = [_operating_year(scenario, y) for y in range(1, hold + 2)]
    projection = rows[:hold]
    forward_noi = rows[hold]["_noi"]  # NOI of year hold+1

    # --- Terminal value / reversion -------------------------------------- #
    exit_cap = ana["exit_cap_rate"]
    terminal_value = forward_noi / exit_cap if exit_cap > 0 else 0.0
    net_reversion = terminal_value * (1 - ana["selling_cost_pct"])

    # --- Unlevered DCF --------------------------------------------------- #
    unlevered_flows = [row["_unlevered_cf"] for row in projection]
    unlevered_flows[-1] += net_reversion

    d = ana["discount_rate"]
    pv_operations = sum(cf / (1 + d) ** (i + 1)
                        for i, cf in enumerate(row["_unlevered_cf"] for row in projection))
    pv_reversion = net_reversion / (1 + d) ** hold
    dcf_value = pv_operations + pv_reversion

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
    }

    # --- Debt / levered returns ------------------------------------------ #
    debt = scenario["debt"]
    if debt["enabled"]:
        loan_amount = debt["loan_amount"] or (debt["ltv_pct"] * price)
        sched = _mortgage_schedule(
            loan_amount, debt["interest_rate"], debt["amortization_years"],
            hold, debt["io"],
        )
        equity = price - loan_amount
        levered_flows: list[float] = []
        cash_on_cash: list[float] = []
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
        total_levered = (sum(row["levered_cash_flow"] for row in projection)
                         + net_equity_reversion)
        equity_multiple_levered = (total_levered / equity) if equity > 0 else None

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
            "equity_multiple_levered": (round(equity_multiple_levered, 3)
                                        if equity_multiple_levered is not None else None),
            "avg_cash_on_cash": round(sum(cash_on_cash) / len(cash_on_cash), 4)
            if cash_on_cash else None,
        }

    # strip internal keys before returning
    for row in projection:
        row.pop("_noi", None)
        row.pop("_unlevered_cf", None)

    return {
        "property": scenario["property"],
        "assumptions": ana,
        "years": [row["year"] for row in projection],
        "cash_flow": projection,
        "metrics": metrics,
    }


# --------------------------------------------------------------------------- #
# Sample deal
# --------------------------------------------------------------------------- #

def sample_scenario() -> dict:
    """A representative 100,000 SF office deal used as the default scenario."""
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
        "leases": [
            {"tenant": "Meridian Capital (Anchor)", "suite_sf": 45000, "start_year": 1,
             "term_years": 10, "base_rent_psf": 33.0, "annual_escalation_pct": 0.03,
             "recovery_psf": 9.5, "free_rent_months": 0},
            {"tenant": "Lumen Health Systems", "suite_sf": 28000, "start_year": 1,
             "term_years": 7, "base_rent_psf": 31.5, "annual_escalation_pct": 0.025,
             "recovery_psf": 9.0, "free_rent_months": 3},
            {"tenant": "Northwind Advisory", "suite_sf": 15000, "start_year": 1,
             "term_years": 5, "base_rent_psf": 30.0, "annual_escalation_pct": 0.03,
             "recovery_psf": 8.5, "free_rent_months": 0},
            {"tenant": "Second-Gen Suite (re-lease)", "suite_sf": 15000, "start_year": 6,
             "term_years": 5, "base_rent_psf": 36.0, "annual_escalation_pct": 0.03,
             "recovery_psf": 10.0, "free_rent_months": 6},
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
            "enabled": True,
            "ltv_pct": 0.60,
            "loan_amount": 0,
            "interest_rate": 0.0625,
            "amortization_years": 30,
            "io": False,
        },
    }
