"""Tests for the ARGUS-style valuation engine (v2).

Run from the backend/ directory with:  pytest
"""

import pytest

import engine


# --------------------------------------------------------------------------- #
# Financial helpers
# --------------------------------------------------------------------------- #

def test_npv_known_value():
    assert engine.npv(0.10, [0, 100]) == pytest.approx(90.909, abs=0.01)


def test_irr_simple_doubling():
    assert engine.irr([-100, 0, 121]) == pytest.approx(0.10, abs=1e-4)


def test_irr_no_sign_change_returns_none():
    assert engine.irr([100, 200, 300]) is None
    assert engine.irr([-100, -50]) is None


def test_irr_matches_npv_zero():
    flows = [-1_000_000, 80_000, 85_000, 90_000, 1_300_000]
    rate = engine.irr(flows)
    assert rate is not None
    assert engine.npv(rate, flows) == pytest.approx(0.0, abs=1.0)


def test_amortizing_schedule_pays_down_principal():
    sched = engine._mortgage_schedule(1_000_000, 0.06, 30, 10, interest_only=False)
    assert 0 < sched["ending_balance"] < 1_000_000
    assert sched["monthly_payment"] == pytest.approx(5995.51, abs=1.0)


def test_interest_only_schedule():
    sched = engine._mortgage_schedule(1_000_000, 0.06, 30, 5, interest_only=True)
    assert sched["ending_balance"] == pytest.approx(1_000_000)
    assert sched["annual_debt_service"][0] == pytest.approx(60_000, abs=1.0)


# --------------------------------------------------------------------------- #
# Market leasing assumptions (the defining ARGUS feature)
# --------------------------------------------------------------------------- #

def test_effective_mla_weights_renew_and_new():
    mla = engine.normalize_scenario({"market_leasing": {
        "renewal_probability": 0.75, "downtime_months": 12, "new_ti_psf": 40,
        "renewal_ti_psf": 10, "new_free_rent_months": 4, "renewal_free_rent_months": 0,
        "new_lc_pct": 0.06, "renewal_lc_pct": 0.02,
    }})["market_leasing"]
    eff = engine._effective_mla(mla)
    # Downtime applies to new tenants only -> (1-0.75)*12 = 3 months.
    assert eff["downtime_months"] == pytest.approx(3.0)
    # TI blended: 0.75*10 + 0.25*40 = 17.5
    assert eff["ti_psf"] == pytest.approx(17.5)
    assert eff["free_rent_months"] == pytest.approx(0.75 * 0 + 0.25 * 4)
    assert eff["lc_pct"] == pytest.approx(0.75 * 0.02 + 0.25 * 0.06)


def test_segments_chain_from_inplace_into_market():
    sc = engine.normalize_scenario({
        "analysis": {"hold_years": 10, "market_rent_psf": 30, "market_rent_growth_pct": 0},
        "market_leasing": {"market_term_years": 5, "renewal_probability": 1.0},
        "leases": [{"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 3,
                    "base_rent_psf": 20}],
    })
    segs = engine._build_segments(sc["leases"][0], sc["market_leasing"], sc["analysis"], 11)
    assert segs[0]["is_inplace"] is True
    assert segs[0]["commence"] == 1 and segs[0]["end"] == 3
    # Next lease commences the year after expiry, at market.
    assert segs[1]["commence"] == 4 and segs[1]["is_inplace"] is False
    assert segs[1]["rent_psf"] == pytest.approx(30)


def test_rollover_year_incurs_turnover_ti_and_lc():
    sc = engine.normalize_scenario({
        "analysis": {"hold_years": 10, "market_rent_psf": 30, "market_rent_growth_pct": 0},
        "market_leasing": {"market_term_years": 5, "renewal_probability": 0.0,
                           "downtime_months": 6, "new_ti_psf": 50, "new_lc_pct": 0.06,
                           "new_free_rent_months": 0},
        "leases": [{"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 3,
                    "base_rent_psf": 20}],
    })
    segs = engine._build_segments(sc["leases"][0], sc["market_leasing"], sc["analysis"], 11)
    # Year 3: last year of in-place lease -> no turnover/TI.
    y3 = engine._space_year(1000, segs, 3)
    assert y3["turnover_vacancy"] == 0 and y3["ti"] == 0
    # Year 4: new market lease commences -> downtime, TI and LC all hit.
    y4 = engine._space_year(1000, segs, 4)
    assert y4["potential_base_rent"] == pytest.approx(30_000)
    assert y4["turnover_vacancy"] == pytest.approx(30_000 * 6 / 12)   # 6 months down
    assert y4["ti"] == pytest.approx(1000 * 50)                        # $50/sf TI
    assert y4["lc"] == pytest.approx(0.06 * 1000 * 30 * 5)             # 6% of total term rent
    assert y4["occupied_fraction"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Reimbursement methods
# --------------------------------------------------------------------------- #

def _single_tenant(method):
    """One tenant filling the whole building, flat $10/sf opex, no growth."""
    return {
        "property": {"total_sf": 1000},
        "analysis": {"hold_years": 5, "purchase_price": 0, "general_vacancy_pct": 0,
                     "market_rent_psf": 0},
        "leases": [{"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 5,
                    "base_rent_psf": 20, "reimbursement_method": method}],
        "expenses": [{"name": "Opex", "amount": 10, "basis": "psf", "growth_pct": 0.10}],
        "capital": {"reserve_psf": 0},
    }


def test_reimbursement_net_recovers_full_share():
    r = engine.analyze(_single_tenant("net"), with_sensitivity=False)
    row1 = r["cash_flow"][0]
    # Net lease, 100% share -> reimburses the full $10,000 opex.
    assert row1["expense_reimbursements"] == pytest.approx(10_000, abs=1)
    assert row1["operating_expenses"] == pytest.approx(-10_000, abs=1)


def test_reimbursement_base_stop_only_recovers_increase():
    r = engine.analyze(_single_tenant("base_stop"), with_sensitivity=False)
    rows = r["cash_flow"]
    # Base year (year 1) recovers nothing; later years recover the increase.
    assert rows[0]["expense_reimbursements"] == pytest.approx(0, abs=1)
    assert rows[1]["expense_reimbursements"] == pytest.approx(10_000 * 1.1 - 10_000, abs=1)


def test_reimbursement_gross_recovers_nothing():
    r = engine.analyze(_single_tenant("gross"), with_sensitivity=False)
    assert all(row["expense_reimbursements"] == 0 for row in r["cash_flow"])


# --------------------------------------------------------------------------- #
# Full analysis: identities and sanity
# --------------------------------------------------------------------------- #

def test_proforma_identities_hold_every_year():
    result = engine.analyze(engine.sample_scenario(), with_sensitivity=False)
    for r in result["cash_flow"]:
        assert r["scheduled_base_rent"] == pytest.approx(
            r["potential_base_rent"] + r["absorption_turnover_vacancy"]
            + r["base_rent_abatements"], abs=0.5)
        assert r["total_tenant_revenue"] == pytest.approx(
            r["scheduled_base_rent"] + r["expense_reimbursements"], abs=0.5)
        assert r["effective_gross_revenue"] == pytest.approx(
            r["total_tenant_revenue"] + r["general_vacancy"], abs=0.5)
        assert r["noi"] == pytest.approx(
            r["effective_gross_revenue"] + r["operating_expenses"], abs=0.5)
        assert r["unlevered_cash_flow"] == pytest.approx(
            r["noi"] + r["tenant_improvements"] + r["leasing_commissions"]
            + r["capital_reserve"], abs=0.5)


def test_sample_analysis_is_plausible():
    result = engine.analyze(engine.sample_scenario(), with_sensitivity=False)
    assert len(result["cash_flow"]) == 10
    m = result["metrics"]
    assert 0.03 < m["going_in_cap_rate"] < 0.10
    assert m["year1_noi"] > 0
    assert m["unlevered_irr"] is not None and -0.1 < m["unlevered_irr"] < 0.40
    assert m["debt"]["levered_irr"] > m["unlevered_irr"]  # positive leverage
    # TI/LC should actually show up now (leasing capital is spent on rollover).
    assert m["total_leasing_capital"] < 0


def test_leasing_costs_appear_on_rollover_years():
    result = engine.analyze(engine.sample_scenario(), with_sensitivity=False)
    # Advisory (5yr) rolls at year 6; some year must carry TI/LC spend.
    assert any(r["tenant_improvements"] < 0 for r in result["cash_flow"])
    assert any(r["leasing_commissions"] < 0 for r in result["cash_flow"])
    assert any(r["absorption_turnover_vacancy"] < 0 for r in result["cash_flow"])


def test_terminal_value_uses_forward_noi():
    m = engine.analyze(engine.sample_scenario(), with_sensitivity=False)["metrics"]
    assert m["terminal_value"] == pytest.approx(m["forward_noi"] / m["exit_cap_rate"], rel=1e-4)
    assert m["net_reversion"] == pytest.approx(m["terminal_value"] * 0.98, rel=1e-4)


def test_higher_exit_cap_lowers_value():
    base = engine.sample_scenario()
    low = engine.analyze({**base, "analysis": {**base["analysis"], "exit_cap_rate": 0.055}},
                         with_sensitivity=False)
    high = engine.analyze({**base, "analysis": {**base["analysis"], "exit_cap_rate": 0.085}},
                          with_sensitivity=False)
    assert high["metrics"]["dcf_value"] < low["metrics"]["dcf_value"]


def test_empty_scenario_does_not_crash():
    result = engine.analyze({}, with_sensitivity=False)
    assert result["metrics"]["year1_noi"] == 0
    assert result["metrics"]["unlevered_irr"] is None


# --------------------------------------------------------------------------- #
# Sensitivity grid
# --------------------------------------------------------------------------- #

def test_sensitivity_grid_shape_and_monotonicity():
    result = engine.analyze(engine.sample_scenario())
    s = result["sensitivity"]
    assert len(s["discount_rates"]) == 5 and len(s["exit_cap_rates"]) == 5
    assert len(s["dcf_value"]) == 5 and all(len(row) == 5 for row in s["dcf_value"])
    # Across a row, value falls as the exit cap rate rises.
    for row in s["dcf_value"]:
        assert row == sorted(row, reverse=True)
    # Down a column, value falls as the discount rate rises.
    for col in range(5):
        column = [s["dcf_value"][r][col] for r in range(5)]
        assert column == sorted(column, reverse=True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
