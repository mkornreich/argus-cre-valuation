"""Tests for the ARGUS-style calendar-daily valuation engine (v5).

Run from the backend/ directory with:  pytest
"""

import datetime as dt

import pytest

import engine


# --------------------------------------------------------------------------- #
# Financial helpers
# --------------------------------------------------------------------------- #

def test_irr_simple_doubling():
    assert engine.irr([-100, 0, 121]) == pytest.approx(0.10, abs=1e-4)


def test_annuity_pv():
    assert engine.annuity_pv(0.08, 10) == pytest.approx(6.7101, abs=1e-3)


def test_solve_decreasing():
    # Solve 1000/y == 12500 -> y = 0.08
    assert engine.solve_decreasing(lambda y: 1000 / y, 12500, tol=0.01) == pytest.approx(0.08, abs=1e-3)


def test_add_months():
    assert engine._add_months(dt.date(2026, 11, 1), 3) == dt.date(2027, 2, 1)


# --------------------------------------------------------------------------- #
# Calendar-exact daily accrual
# --------------------------------------------------------------------------- #

def _full_building(**lease_over):
    lease = {"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 10,
             "base_rent_psf": 12, "reimbursement_method": "gross"}
    lease.update(lease_over)
    return {"property": {"total_sf": 1000},
            "analysis": {"hold_years": 5, "purchase_price": 0, "general_vacancy_pct": 0,
                         "market_rent_psf": 0},
            "leases": [lease], "expenses": [], "capital": {"reserve_psf": 0}}


def test_free_rent_prorated():
    r = engine.analyze(_full_building(free_rent_months=6), with_sensitivity=False, include_monthly=False)
    y1 = r["cash_flow"][0]
    assert y1["potential_base_rent"] == pytest.approx(12_000, abs=80)
    assert y1["base_rent_abatements"] == pytest.approx(-6_000, abs=80)


def test_fiscal_year_start_aligns_to_calendar():
    sc = engine.sample_scenario()
    sc["analysis"]["start_month"] = 7
    r = engine.analyze(sc, with_sensitivity=False, include_monthly=True)
    assert r["monthly_cash_flow"][0]["period"] == "2026-07"
    assert r["monthly_cash_flow"][11]["period"] == "2027-06"


def test_monthly_sums_to_annual():
    r = engine.analyze(engine.sample_scenario(), with_sensitivity=False, include_monthly=True)
    assert len(r["monthly_cash_flow"]) == 120
    y1 = sum(m["unlevered_cash_flow"] for m in r["monthly_cash_flow"][:12])
    assert y1 == pytest.approx(r["cash_flow"][0]["unlevered_cash_flow"], abs=20)


# --------------------------------------------------------------------------- #
# Rent reviews: fixed / CPI / CPI series / stepped
# --------------------------------------------------------------------------- #

def _seg(**over):
    sc = engine.normalize_scenario({
        "analysis": {"hold_years": 8, "market_rent_psf": 0, "cpi_rate": 0.025},
        "leases": [{"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 8,
                    "base_rent_psf": 30, **over}]})
    start_ord = dt.date(2026, 1, 1).toordinal()
    segs = engine._build_segments(sc["leases"][0], sc["market_leasing"], sc["analysis"],
                                  start_ord, start_ord + 4000)
    return segs[0], sc["analysis"], start_ord


def test_fixed_escalation():
    seg, ana, s = _seg(escalation_type="fixed", annual_escalation_pct=0.03)
    assert engine._seg_rent_psf(seg, s, ana) == pytest.approx(30)
    assert engine._seg_rent_psf(seg, s + int(2.5 * engine.DPY), ana) == pytest.approx(30 * 1.03 ** 2)


def test_cpi_flat_rate():
    seg, ana, s = _seg(escalation_type="cpi", cpi_rate=0.025)
    assert engine._seg_rent_psf(seg, s + int(3.5 * engine.DPY), ana) == pytest.approx(30 * 1.025 ** 3)


def test_cpi_index_series():
    seg, ana, s = _seg(escalation_type="cpi", cpi_series=[0.06, 0.05, 0.04])
    # After 3 whole years: 30 * 1.06 * 1.05 * 1.04
    assert engine._seg_rent_psf(seg, s + int(3.5 * engine.DPY), ana) == pytest.approx(
        30 * 1.06 * 1.05 * 1.04)


def test_stepped_rent():
    seg, ana, s = _seg(escalation_type="stepped",
                       rent_steps=[{"lease_year": 1, "rent_psf": 30}, {"lease_year": 3, "rent_psf": 33},
                                   {"lease_year": 5, "rent_psf": 36}])
    assert engine._seg_rent_psf(seg, s + int(0.5 * engine.DPY), ana) == pytest.approx(30)
    assert engine._seg_rent_psf(seg, s + int(3.5 * engine.DPY), ana) == pytest.approx(33)
    assert engine._seg_rent_psf(seg, s + int(5.5 * engine.DPY), ana) == pytest.approx(36)


# --------------------------------------------------------------------------- #
# Reimbursements
# --------------------------------------------------------------------------- #

def _single_tenant(method, sf=1000, recovery=None, **ana_over):
    sc = {"property": {"total_sf": 1000},
          "analysis": {"hold_years": 5, "purchase_price": 0, "general_vacancy_pct": 0,
                       "market_rent_psf": 0, "expense_gross_up_pct": 0},
          "leases": [{"tenant": "T", "suite_sf": sf, "start_year": 1, "term_years": 5,
                      "base_rent_psf": 20, "reimbursement_method": method, "recovery": recovery or {}}],
          "expenses": [{"name": "Opex", "amount": 10, "basis": "psf", "growth_pct": 0.10,
                        "recoverable": True, "variable": True}],
          "capital": {"reserve_psf": 0}}
    sc["analysis"].update(ana_over)
    return sc


def test_reimbursement_methods():
    net = engine.analyze(_single_tenant("net"), with_sensitivity=False, include_monthly=False)
    assert net["cash_flow"][0]["expense_reimbursements"] == pytest.approx(10_000, abs=60)
    gross = engine.analyze(_single_tenant("gross"), with_sensitivity=False, include_monthly=False)
    assert all(r["expense_reimbursements"] == 0 for r in gross["cash_flow"])
    stop = engine.analyze(_single_tenant("base_stop"), with_sensitivity=False, include_monthly=False)
    assert stop["cash_flow"][0]["expense_reimbursements"] == pytest.approx(0, abs=60)
    assert stop["cash_flow"][1]["expense_reimbursements"] == pytest.approx(1_000, abs=80)


def test_recovery_cap_admin_stop_and_grossup():
    uncapped = engine.analyze(_single_tenant("net"), with_sensitivity=False, include_monthly=False)
    capped = engine.analyze(_single_tenant("net", recovery={"cap_pct": 0.03}),
                            with_sensitivity=False, include_monthly=False)
    assert capped["cash_flow"][2]["expense_reimbursements"] < uncapped["cash_flow"][2]["expense_reimbursements"]
    fee = engine.analyze(_single_tenant("net", recovery={"admin_fee_pct": 0.05}),
                         with_sensitivity=False, include_monthly=False)
    assert fee["cash_flow"][0]["expense_reimbursements"] == pytest.approx(
        uncapped["cash_flow"][0]["expense_reimbursements"] * 1.05, rel=1e-3)
    stop = engine.analyze(_single_tenant("net", recovery={"stop_psf": 4}),
                          with_sensitivity=False, include_monthly=False)
    assert stop["cash_flow"][0]["expense_reimbursements"] < uncapped["cash_flow"][0]["expense_reimbursements"]
    base = _single_tenant("net", sf=500)
    gu = engine.analyze({**base, "analysis": {**base["analysis"], "expense_gross_up_pct": 0.95}},
                        with_sensitivity=False, include_monthly=False)["cash_flow"][0]["expense_reimbursements"]
    no_gu = engine.analyze(base, with_sensitivity=False, include_monthly=False)["cash_flow"][0]["expense_reimbursements"]
    assert gu > no_gu


# --------------------------------------------------------------------------- #
# Percentage rent & LC basis
# --------------------------------------------------------------------------- #

def test_percentage_rent():
    sc = {"property": {"total_sf": 1000},
          "analysis": {"hold_years": 2, "purchase_price": 0, "general_vacancy_pct": 0, "market_rent_psf": 0},
          "leases": [{"tenant": "Shop", "suite_sf": 1000, "start_year": 1, "term_years": 2,
                      "base_rent_psf": 30, "reimbursement_method": "gross",
                      "percentage_rent": {"sales_psf": 600, "percent": 0.06, "breakpoint_psf": 500}}],
          "expenses": [], "capital": {"reserve_psf": 0}}
    assert engine.analyze(sc, with_sensitivity=False, include_monthly=False)["cash_flow"][0]["percentage_rent"] == pytest.approx(6_000, abs=60)


def test_lc_basis():
    assert engine._seg_lc_amount({"lc": 10, "lc_basis": "psf", "rent_psf0": 30, "term_years": 5}, 1000) == pytest.approx(10_000)
    assert engine._seg_lc_amount({"lc": 0.06, "lc_basis": "percent", "rent_psf0": 30, "term_years": 5}, 1000) == pytest.approx(0.06 * 1000 * 30 * 5)


# --------------------------------------------------------------------------- #
# Debt: tranches, reversion & cash-flow participation
# --------------------------------------------------------------------------- #

def test_debt_tranches_and_participation():
    m = engine.analyze(engine.sample_scenario(), with_sensitivity=False, include_monthly=False)["metrics"]
    d = m["debt"]
    assert len(d["tranches"]) == 2
    assert d["loan_amount"] == pytest.approx(sum(t["loan_amount"] for t in d["tranches"]))
    assert d["lender_participation"] > 0
    assert d["levered_irr"] > m["unlevered_irr"]


def test_cashflow_participation_reduces_equity_return():
    base = engine.sample_scenario()
    part = engine.sample_scenario()
    part["debt"]["tranches"][1]["participation_cf_pct"] = 0.15
    d0 = engine.analyze(base, with_sensitivity=False, include_monthly=False)["metrics"]["debt"]
    d1 = engine.analyze(part, with_sensitivity=False, include_monthly=False)["metrics"]["debt"]
    assert d1["lender_cashflow_participation"] > 0
    assert d1["levered_irr"] < d0["levered_irr"]


# --------------------------------------------------------------------------- #
# Traditional valuation: initial / reversionary / equivalent / hardcore
# --------------------------------------------------------------------------- #

def test_traditional_valuation():
    tv = engine.analyze(engine.sample_scenario(), with_sensitivity=False, include_monthly=False)["traditional_valuation"]
    assert tv["term_and_reversion_value"] == pytest.approx(tv["term_value"] + tv["reversion_value"], abs=1)
    assert tv["reversionary_yield"] > tv["net_initial_yield"]           # under-rented
    # Equivalent yield sits between the initial and reversionary yields.
    assert tv["net_initial_yield"] < tv["equivalent_yield"] < tv["reversionary_yield"]
    # Hardcore at the equivalent yield reproduces the price (consistency check).
    assert tv["hardcore_value"] == pytest.approx(28_500_000, rel=0.02)


# --------------------------------------------------------------------------- #
# Portfolio consolidation + cross-collateralised fund debt
# --------------------------------------------------------------------------- #

def test_portfolio_and_fund_debt():
    s1, s2 = engine.sample_scenario(), engine.sample_scenario()
    s2["property"]["name"] = "Second Asset"
    port = engine.consolidate([s1, s2], fund_debt={"ltv_pct": 0.5, "interest_rate": 0.055,
                                                   "amortization_years": 30})
    assert len(port["assets"]) == 2
    assert port["totals"]["purchase_price"] == pytest.approx(57_000_000)
    single = engine.analyze(s1, with_sensitivity=False, include_monthly=False)["metrics"]
    assert port["totals"]["portfolio_unlevered_irr"] == pytest.approx(single["unlevered_irr"], abs=2e-3)
    fd = port["fund_debt"]
    assert fd["loan_amount"] == pytest.approx(0.5 * 57_000_000)
    assert fd["fund_levered_irr"] is not None and fd["fund_levered_irr"] > single["unlevered_irr"]


# --------------------------------------------------------------------------- #
# Identities, sanity, sensitivity
# --------------------------------------------------------------------------- #

def test_proforma_identities():
    for r in engine.analyze(engine.sample_scenario(), with_sensitivity=False, include_monthly=False)["cash_flow"]:
        assert r["noi"] == pytest.approx(r["effective_gross_revenue"] + r["operating_expenses"], abs=1)
        assert r["unlevered_cash_flow"] == pytest.approx(
            r["noi"] + r["tenant_improvements"] + r["leasing_commissions"] + r["capital_reserve"], abs=1)


def test_sample_plausible_and_sensitivity():
    r = engine.analyze(engine.sample_scenario())
    m = r["metrics"]
    assert 0.03 < m["going_in_cap_rate"] < 0.10
    assert -0.1 < m["unlevered_irr"] < 0.40
    for row in r["sensitivity"]["dcf_value"]:
        assert row == sorted(row, reverse=True)


def test_empty_scenario_does_not_crash():
    assert engine.analyze({}, with_sensitivity=False, include_monthly=False)["metrics"]["year1_noi"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
