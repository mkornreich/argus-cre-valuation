"""Tests for the ARGUS-style monthly valuation engine (v3).

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


def test_amortizing_schedule_pays_down_principal():
    sched = engine._mortgage_schedule(1_000_000, 0.06, 30, 10, interest_only=False)
    assert 0 < sched["ending_balance"] < 1_000_000
    assert sched["monthly_payment"] == pytest.approx(5995.51, abs=1.0)


def test_overlap():
    assert engine._overlap(0, 1, 0, 6) == 1
    assert engine._overlap(5, 6, 0, 6) == 1
    assert engine._overlap(6, 7, 0, 6) == 0
    assert engine._overlap(0.5, 1.5, 1.0, 2.0) == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Monthly proration (the point of v3 — no annual shortcuts)
# --------------------------------------------------------------------------- #

def _single_full_building(**lease_over):
    lease = {"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 10,
             "base_rent_psf": 12, "annual_escalation_pct": 0, "reimbursement_method": "gross"}
    lease.update(lease_over)
    return {
        "property": {"total_sf": 1000},
        "analysis": {"hold_years": 5, "purchase_price": 0, "general_vacancy_pct": 0,
                     "market_rent_psf": 0},
        "leases": [lease],
        "expenses": [], "capital": {"reserve_psf": 0},
    }


def test_free_rent_prorates_by_month_not_year():
    r = engine.analyze(_single_full_building(free_rent_months=6), with_sensitivity=False)
    y1 = r["cash_flow"][0]
    # Full potential is $12,000; six months free abates exactly half.
    assert y1["potential_base_rent"] == pytest.approx(12_000, abs=1)
    assert y1["base_rent_abatements"] == pytest.approx(-6_000, abs=1)
    assert y1["scheduled_base_rent"] == pytest.approx(6_000, abs=1)
    # Year 2 is unaffected.
    assert r["cash_flow"][1]["base_rent_abatements"] == pytest.approx(0, abs=1)


def test_partial_month_downtime_is_prorated():
    # Lease rolls at the end of year 2; weighted downtime = 50% of 9 months = 4.5.
    sc = engine.normalize_scenario({
        "analysis": {"hold_years": 6, "market_rent_psf": 24, "market_rent_growth_pct": 0},
        "market_leasing": {"renewal_probability": 0.5, "downtime_months": 9,
                           "market_term_years": 5, "renewal_term_years": 5,
                           "new_free_rent_months": 0, "renewal_free_rent_months": 0},
        "leases": [{"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 2,
                    "base_rent_psf": 20, "reimbursement_method": "gross"}],
        "expenses": [], "capital": {"reserve_psf": 0},
    })
    spaces = engine._build_spaces(sc, 72)
    # Sum turnover vacancy across all months -> 4.5 months of market rent.
    total_turnover = sum(engine._month_row(sc, spaces, m)["absorption_turnover_vacancy"]
                         for m in range(72))
    expected = -(1000 * 24 / 12) * 4.5
    assert total_turnover == pytest.approx(expected, abs=5)


def test_monthly_sums_to_annual():
    r = engine.analyze(engine.sample_scenario(), with_sensitivity=False, include_monthly=True)
    assert "monthly_cash_flow" in r and len(r["monthly_cash_flow"]) == 120
    y1_monthly = sum(m["unlevered_cash_flow"] for m in r["monthly_cash_flow"][:12])
    assert y1_monthly == pytest.approx(r["cash_flow"][0]["unlevered_cash_flow"], abs=2)


# --------------------------------------------------------------------------- #
# Reimbursement methods
# --------------------------------------------------------------------------- #

def _single_tenant(method, **over):
    sc = {
        "property": {"total_sf": 1000},
        "analysis": {"hold_years": 5, "purchase_price": 0, "general_vacancy_pct": 0,
                     "market_rent_psf": 0, "expense_gross_up_pct": 0},
        "leases": [{"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 5,
                    "base_rent_psf": 20, "reimbursement_method": method}],
        "expenses": [{"name": "Opex", "amount": 10, "basis": "psf", "growth_pct": 0.10,
                      "recoverable": True, "variable": True}],
        "capital": {"reserve_psf": 0},
    }
    sc["analysis"].update(over)
    return sc


def test_reimbursement_net_recovers_full_share():
    r = engine.analyze(_single_tenant("net"), with_sensitivity=False)
    assert r["cash_flow"][0]["expense_reimbursements"] == pytest.approx(10_000, abs=5)


def test_reimbursement_base_stop_recovers_increase():
    r = engine.analyze(_single_tenant("base_stop"), with_sensitivity=False)
    rows = r["cash_flow"]
    assert rows[0]["expense_reimbursements"] == pytest.approx(0, abs=5)
    assert rows[1]["expense_reimbursements"] == pytest.approx(10_000 * 1.1 - 10_000, abs=5)


def test_reimbursement_gross_recovers_nothing():
    r = engine.analyze(_single_tenant("gross"), with_sensitivity=False)
    assert all(row["expense_reimbursements"] == 0 for row in r["cash_flow"])


def test_gross_up_lifts_recovery_when_under_occupied():
    # One tenant on 50% of the building, no market rent -> 50% occupancy.
    base = {
        "property": {"total_sf": 1000},
        "analysis": {"hold_years": 3, "purchase_price": 0, "general_vacancy_pct": 0,
                     "market_rent_psf": 0},
        "leases": [{"tenant": "T", "suite_sf": 500, "start_year": 1, "term_years": 3,
                    "base_rent_psf": 20, "reimbursement_method": "net"}],
        "expenses": [{"name": "Opex", "amount": 10, "basis": "psf", "growth_pct": 0,
                      "recoverable": True, "variable": True}],
        "capital": {"reserve_psf": 0},
    }
    no_gu = engine.analyze({**base, "analysis": {**base["analysis"], "expense_gross_up_pct": 0}},
                           with_sensitivity=False)["cash_flow"][0]["expense_reimbursements"]
    gu = engine.analyze({**base, "analysis": {**base["analysis"], "expense_gross_up_pct": 0.95}},
                        with_sensitivity=False)["cash_flow"][0]["expense_reimbursements"]
    assert gu > no_gu  # grossing up variable expenses recovers more


# --------------------------------------------------------------------------- #
# Percentage rent (retail)
# --------------------------------------------------------------------------- #

def test_percentage_rent_over_breakpoint():
    sc = {
        "property": {"total_sf": 1000},
        "analysis": {"hold_years": 2, "purchase_price": 0, "general_vacancy_pct": 0,
                     "market_rent_psf": 0},
        "leases": [{"tenant": "Shop", "suite_sf": 1000, "start_year": 1, "term_years": 2,
                    "base_rent_psf": 30, "reimbursement_method": "gross",
                    "percentage_rent": {"sales_psf": 600, "percent": 0.06, "breakpoint_psf": 500}}],
        "expenses": [], "capital": {"reserve_psf": 0},
    }
    y1 = engine.analyze(sc, with_sensitivity=False)["cash_flow"][0]
    # Overage = (600-500)*6% = $6/sf * 1000 sf.
    assert y1["percentage_rent"] == pytest.approx(6_000, abs=5)


# --------------------------------------------------------------------------- #
# Full analysis: identities and sanity
# --------------------------------------------------------------------------- #

def test_proforma_identities_hold_every_year():
    result = engine.analyze(engine.sample_scenario(), with_sensitivity=False)
    for r in result["cash_flow"]:
        assert r["scheduled_base_rent"] == pytest.approx(
            r["potential_base_rent"] + r["absorption_turnover_vacancy"]
            + r["base_rent_abatements"], abs=1)
        assert r["total_tenant_revenue"] == pytest.approx(
            r["scheduled_base_rent"] + r["expense_reimbursements"] + r["percentage_rent"], abs=1)
        assert r["effective_gross_revenue"] == pytest.approx(
            r["total_tenant_revenue"] + r["general_vacancy"], abs=1)
        assert r["noi"] == pytest.approx(
            r["effective_gross_revenue"] + r["operating_expenses"], abs=1)
        assert r["unlevered_cash_flow"] == pytest.approx(
            r["noi"] + r["tenant_improvements"] + r["leasing_commissions"]
            + r["capital_reserve"], abs=1)


def test_sample_analysis_is_plausible():
    m = engine.analyze(engine.sample_scenario(), with_sensitivity=False)["metrics"]
    assert 0.03 < m["going_in_cap_rate"] < 0.10
    assert m["year1_noi"] > 0
    assert m["unlevered_irr"] is not None and -0.1 < m["unlevered_irr"] < 0.40
    assert m["debt"]["levered_irr"] > m["unlevered_irr"]
    assert m["total_leasing_capital"] < 0


def test_leasing_costs_appear_on_rollover_years():
    result = engine.analyze(engine.sample_scenario(), with_sensitivity=False)
    assert any(r["tenant_improvements"] < 0 for r in result["cash_flow"])
    assert any(r["leasing_commissions"] < 0 for r in result["cash_flow"])
    assert any(r["absorption_turnover_vacancy"] < 0 for r in result["cash_flow"])


def test_terminal_value_uses_forward_noi():
    m = engine.analyze(engine.sample_scenario(), with_sensitivity=False)["metrics"]
    assert m["terminal_value"] == pytest.approx(m["forward_noi"] / m["exit_cap_rate"], rel=1e-4)


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


# --------------------------------------------------------------------------- #
# Sensitivity grid
# --------------------------------------------------------------------------- #

def test_sensitivity_grid_shape_and_monotonicity():
    s = engine.analyze(engine.sample_scenario())["sensitivity"]
    assert len(s["dcf_value"]) == 5 and all(len(row) == 5 for row in s["dcf_value"])
    for row in s["dcf_value"]:
        assert row == sorted(row, reverse=True)
    for col in range(5):
        column = [s["dcf_value"][r][col] for r in range(5)]
        assert column == sorted(column, reverse=True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
