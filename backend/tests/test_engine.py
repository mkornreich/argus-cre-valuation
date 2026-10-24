"""Tests for the ARGUS-style daily valuation engine (v4).

Run from the backend/ directory with:  pytest
"""

import pytest

import engine


# --------------------------------------------------------------------------- #
# Financial helpers
# --------------------------------------------------------------------------- #

def test_irr_simple_doubling():
    assert engine.irr([-100, 0, 121]) == pytest.approx(0.10, abs=1e-4)


def test_annuity_pv():
    # 10 years at 8% -> years' purchase 6.7101
    assert engine.annuity_pv(0.08, 10) == pytest.approx(6.7101, abs=1e-3)
    assert engine.annuity_pv(0.0, 10) == 10


def test_amortizing_schedule():
    s = engine._mortgage_schedule(1_000_000, 0.06, 30, 10, interest_only=False)
    assert 0 < s["ending_balance"] < 1_000_000
    assert s["monthly_payment"] == pytest.approx(5995.51, abs=1.0)


# --------------------------------------------------------------------------- #
# Daily proration
# --------------------------------------------------------------------------- #

def _full_building(**lease_over):
    lease = {"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 10,
             "base_rent_psf": 12, "reimbursement_method": "gross"}
    lease.update(lease_over)
    return {"property": {"total_sf": 1000},
            "analysis": {"hold_years": 5, "purchase_price": 0, "general_vacancy_pct": 0,
                         "market_rent_psf": 0},
            "leases": [lease], "expenses": [], "capital": {"reserve_psf": 0}}


def test_free_rent_prorated_daily():
    r = engine.analyze(_full_building(free_rent_months=6), with_sensitivity=False,
                       include_monthly=False)
    y1 = r["cash_flow"][0]
    assert y1["potential_base_rent"] == pytest.approx(12_000, abs=60)
    assert y1["base_rent_abatements"] == pytest.approx(-6_000, abs=60)
    assert r["cash_flow"][1]["base_rent_abatements"] == pytest.approx(0, abs=5)


def test_monthly_sums_to_annual():
    r = engine.analyze(engine.sample_scenario(), with_sensitivity=False, include_monthly=True)
    assert len(r["monthly_cash_flow"]) == 120
    y1 = sum(m["unlevered_cash_flow"] for m in r["monthly_cash_flow"][:12])
    assert y1 == pytest.approx(r["cash_flow"][0]["unlevered_cash_flow"], abs=15)


# --------------------------------------------------------------------------- #
# Rent reviews: fixed / CPI / stepped
# --------------------------------------------------------------------------- #

def _one_seg(**over):
    sc = engine.normalize_scenario({
        "analysis": {"hold_years": 6, "market_rent_psf": 0},
        "leases": [{"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 6,
                    "base_rent_psf": 30, **over}],
    })
    return engine._build_segments(sc["leases"][0], sc["market_leasing"], sc["analysis"], 2500)[0]


def test_fixed_escalation():
    seg = _one_seg(escalation_type="fixed", annual_escalation_pct=0.03)
    assert engine._seg_rent_psf(seg, 0) == pytest.approx(30)
    # Mid-way through the third lease year -> two anniversaries elapsed.
    assert engine._seg_rent_psf(seg, int(2.5 * engine.DPY)) == pytest.approx(30 * 1.03 ** 2)


def test_cpi_escalation():
    seg = _one_seg(escalation_type="cpi", cpi_rate=0.025)
    assert engine._seg_rent_psf(seg, int(3.5 * engine.DPY)) == pytest.approx(30 * 1.025 ** 3)


def test_stepped_rent():
    seg = _one_seg(escalation_type="stepped",
                   rent_steps=[{"lease_year": 1, "rent_psf": 30},
                               {"lease_year": 3, "rent_psf": 33},
                               {"lease_year": 5, "rent_psf": 36}])
    assert engine._seg_rent_psf(seg, int(0.5 * engine.DPY)) == pytest.approx(30)
    assert engine._seg_rent_psf(seg, int(3.5 * engine.DPY)) == pytest.approx(33)
    assert engine._seg_rent_psf(seg, int(5.5 * engine.DPY)) == pytest.approx(36)


# --------------------------------------------------------------------------- #
# Reimbursements: methods, gross-up, cap, stop, admin fee
# --------------------------------------------------------------------------- #

def _single_tenant(method, sf=1000, recovery=None, **ana_over):
    sc = {"property": {"total_sf": 1000},
          "analysis": {"hold_years": 5, "purchase_price": 0, "general_vacancy_pct": 0,
                       "market_rent_psf": 0, "expense_gross_up_pct": 0},
          "leases": [{"tenant": "T", "suite_sf": sf, "start_year": 1, "term_years": 5,
                      "base_rent_psf": 20, "reimbursement_method": method,
                      "recovery": recovery or {}}],
          "expenses": [{"name": "Opex", "amount": 10, "basis": "psf", "growth_pct": 0.10,
                        "recoverable": True, "variable": True}],
          "capital": {"reserve_psf": 0}}
    sc["analysis"].update(ana_over)
    return sc


def test_reimbursement_net_and_gross():
    net = engine.analyze(_single_tenant("net"), with_sensitivity=False, include_monthly=False)
    assert net["cash_flow"][0]["expense_reimbursements"] == pytest.approx(10_000, abs=40)
    gross = engine.analyze(_single_tenant("gross"), with_sensitivity=False, include_monthly=False)
    assert all(r["expense_reimbursements"] == 0 for r in gross["cash_flow"])


def test_reimbursement_base_stop():
    r = engine.analyze(_single_tenant("base_stop"), with_sensitivity=False, include_monthly=False)
    assert r["cash_flow"][0]["expense_reimbursements"] == pytest.approx(0, abs=40)
    assert r["cash_flow"][1]["expense_reimbursements"] == pytest.approx(1_000, abs=60)


def test_recovery_cap_limits_growth():
    capped = engine.analyze(_single_tenant("net", recovery={"cap_pct": 0.03}),
                            with_sensitivity=False, include_monthly=False)
    uncapped = engine.analyze(_single_tenant("net"), with_sensitivity=False, include_monthly=False)
    # Year 3 recoveries are capped below the uncapped (10%/yr) growth.
    assert capped["cash_flow"][2]["expense_reimbursements"] < uncapped["cash_flow"][2]["expense_reimbursements"]


def test_recovery_admin_fee():
    plain = engine.analyze(_single_tenant("net"), with_sensitivity=False, include_monthly=False)
    with_fee = engine.analyze(_single_tenant("net", recovery={"admin_fee_pct": 0.05}),
                              with_sensitivity=False, include_monthly=False)
    assert with_fee["cash_flow"][0]["expense_reimbursements"] == pytest.approx(
        plain["cash_flow"][0]["expense_reimbursements"] * 1.05, rel=1e-3)


def test_expense_stop_reduces_recovery():
    with_stop = engine.analyze(_single_tenant("net", recovery={"stop_psf": 4}),
                               with_sensitivity=False, include_monthly=False)
    plain = engine.analyze(_single_tenant("net"), with_sensitivity=False, include_monthly=False)
    assert with_stop["cash_flow"][0]["expense_reimbursements"] < plain["cash_flow"][0]["expense_reimbursements"]


def test_gross_up_lifts_recovery_when_under_occupied():
    base = _single_tenant("net", sf=500)
    no_gu = engine.analyze({**base, "analysis": {**base["analysis"], "expense_gross_up_pct": 0}},
                           with_sensitivity=False, include_monthly=False)["cash_flow"][0]["expense_reimbursements"]
    gu = engine.analyze({**base, "analysis": {**base["analysis"], "expense_gross_up_pct": 0.95}},
                        with_sensitivity=False, include_monthly=False)["cash_flow"][0]["expense_reimbursements"]
    assert gu > no_gu


# --------------------------------------------------------------------------- #
# Percentage rent & leasing commissions
# --------------------------------------------------------------------------- #

def test_percentage_rent():
    sc = {"property": {"total_sf": 1000},
          "analysis": {"hold_years": 2, "purchase_price": 0, "general_vacancy_pct": 0,
                       "market_rent_psf": 0},
          "leases": [{"tenant": "Shop", "suite_sf": 1000, "start_year": 1, "term_years": 2,
                      "base_rent_psf": 30, "reimbursement_method": "gross",
                      "percentage_rent": {"sales_psf": 600, "percent": 0.06, "breakpoint_psf": 500}}],
          "expenses": [], "capital": {"reserve_psf": 0}}
    y1 = engine.analyze(sc, with_sensitivity=False, include_monthly=False)["cash_flow"][0]
    assert y1["percentage_rent"] == pytest.approx(6_000, abs=40)


def test_lc_basis_psf_vs_percent():
    sc = engine.normalize_scenario({"analysis": {"market_rent_psf": 30},
                                    "market_leasing": {"market_term_years": 5}})
    seg = {"lc": 10, "lc_basis": "psf", "rent_psf0": 30, "term_d": 5 * engine.DPY}
    assert engine._seg_lc_amount(seg, 1000) == pytest.approx(10 * 1000)
    seg_pct = {"lc": 0.06, "lc_basis": "percent", "rent_psf0": 30, "term_d": 5 * engine.DPY}
    assert engine._seg_lc_amount(seg_pct, 1000) == pytest.approx(0.06 * 1000 * 30 * 5)


# --------------------------------------------------------------------------- #
# Debt tranches & participation
# --------------------------------------------------------------------------- #

def test_debt_tranches_combined():
    m = engine.analyze(engine.sample_scenario(), with_sensitivity=False,
                       include_monthly=False)["metrics"]
    d = m["debt"]
    assert len(d["tranches"]) == 2
    assert d["loan_amount"] == pytest.approx(sum(t["loan_amount"] for t in d["tranches"]))
    assert d["lender_participation"] > 0           # mezz participates in reversion
    assert d["levered_irr"] > m["unlevered_irr"]   # positive leverage


def test_participation_reduces_equity_reversion():
    base = engine.sample_scenario()
    no_part = {**base, "debt": {"enabled": True, "tranches": [
        {"name": "S", "ltv_pct": 0.65, "interest_rate": 0.065, "amortization_years": 30}]}}
    part = {**base, "debt": {"enabled": True, "tranches": [
        {"name": "S", "ltv_pct": 0.65, "interest_rate": 0.065, "amortization_years": 30,
         "participation_pct": 0.20}]}}
    d0 = engine.analyze(no_part, with_sensitivity=False, include_monthly=False)["metrics"]["debt"]
    d1 = engine.analyze(part, with_sensitivity=False, include_monthly=False)["metrics"]["debt"]
    assert d1["lender_participation"] > 0
    assert d1["net_equity_reversion"] < d0["net_equity_reversion"]


# --------------------------------------------------------------------------- #
# Traditional valuation
# --------------------------------------------------------------------------- #

def test_traditional_valuation():
    r = engine.analyze(engine.sample_scenario(), with_sensitivity=False, include_monthly=False)
    tv = r["traditional_valuation"]
    assert tv["net_initial_yield"] == pytest.approx(r["metrics"]["going_in_cap_rate"], abs=1e-3)
    assert tv["term_and_reversion_value"] == pytest.approx(
        tv["term_value"] + tv["reversion_value"], abs=1)
    assert tv["years_to_reversion"] > 0
    # Under-rented building: reversion (ERV) yield exceeds the initial yield.
    assert tv["reversionary_yield"] > tv["net_initial_yield"]


# --------------------------------------------------------------------------- #
# Portfolio consolidation
# --------------------------------------------------------------------------- #

def test_portfolio_consolidation():
    s1 = engine.sample_scenario()
    s2 = engine.sample_scenario()
    s2["property"]["name"] = "Second Asset"
    port = engine.consolidate([s1, s2])
    assert len(port["assets"]) == 2
    assert port["totals"]["purchase_price"] == pytest.approx(2 * 28_500_000)
    single = engine.analyze(s1, with_sensitivity=False, include_monthly=False)["metrics"]
    # Two identical assets -> same cap rate and IRR as one.
    assert port["totals"]["blended_going_in_cap"] == pytest.approx(single["going_in_cap_rate"], abs=1e-3)
    assert port["totals"]["portfolio_unlevered_irr"] == pytest.approx(single["unlevered_irr"], abs=2e-3)


# --------------------------------------------------------------------------- #
# Identities, sanity, sensitivity
# --------------------------------------------------------------------------- #

def test_proforma_identities():
    for r in engine.analyze(engine.sample_scenario(), with_sensitivity=False,
                            include_monthly=False)["cash_flow"]:
        assert r["scheduled_base_rent"] == pytest.approx(
            r["potential_base_rent"] + r["absorption_turnover_vacancy"]
            + r["base_rent_abatements"], abs=1)
        assert r["noi"] == pytest.approx(
            r["effective_gross_revenue"] + r["operating_expenses"], abs=1)
        assert r["unlevered_cash_flow"] == pytest.approx(
            r["noi"] + r["tenant_improvements"] + r["leasing_commissions"]
            + r["capital_reserve"], abs=1)


def test_sample_plausible():
    m = engine.analyze(engine.sample_scenario(), with_sensitivity=False,
                       include_monthly=False)["metrics"]
    assert 0.03 < m["going_in_cap_rate"] < 0.10
    assert -0.1 < m["unlevered_irr"] < 0.40


def test_higher_exit_cap_lowers_value():
    base = engine.sample_scenario()
    low = engine.analyze({**base, "analysis": {**base["analysis"], "exit_cap_rate": 0.055}},
                         with_sensitivity=False, include_monthly=False)
    high = engine.analyze({**base, "analysis": {**base["analysis"], "exit_cap_rate": 0.085}},
                          with_sensitivity=False, include_monthly=False)
    assert high["metrics"]["dcf_value"] < low["metrics"]["dcf_value"]


def test_sensitivity_monotonic():
    s = engine.analyze(engine.sample_scenario())["sensitivity"]
    for row in s["dcf_value"]:
        assert row == sorted(row, reverse=True)
    for col in range(5):
        column = [s["dcf_value"][r][col] for r in range(5)]
        assert column == sorted(column, reverse=True)


def test_empty_scenario_does_not_crash():
    assert engine.analyze({}, with_sensitivity=False, include_monthly=False)["metrics"]["year1_noi"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
