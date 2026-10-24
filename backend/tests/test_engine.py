"""Tests for the ARGUS-style valuation engine.

Run from the backend/ directory with:  pytest
"""

import math

import pytest

import engine


# --------------------------------------------------------------------------- #
# Financial helpers
# --------------------------------------------------------------------------- #

def test_npv_known_value():
    # $100 one year out at 10% -> 90.909...
    assert engine.npv(0.10, [0, 100]) == pytest.approx(90.909, abs=0.01)


def test_irr_simple_doubling():
    # -100 now, +121 in two years -> 10% IRR
    assert engine.irr([-100, 0, 121]) == pytest.approx(0.10, abs=1e-4)


def test_irr_no_sign_change_returns_none():
    assert engine.irr([100, 200, 300]) is None
    assert engine.irr([-100, -50]) is None


def test_irr_matches_npv_zero():
    flows = [-1_000_000, 80_000, 85_000, 90_000, 1_300_000]
    rate = engine.irr(flows)
    assert rate is not None
    assert engine.npv(rate, flows) == pytest.approx(0.0, abs=1.0)


# --------------------------------------------------------------------------- #
# Mortgage schedule
# --------------------------------------------------------------------------- #

def test_interest_only_schedule():
    sched = engine._mortgage_schedule(1_000_000, 0.06, 30, 5, interest_only=True)
    assert sched["ending_balance"] == pytest.approx(1_000_000)
    assert sched["annual_debt_service"][0] == pytest.approx(60_000, abs=1.0)
    assert all(p == 0 for p in sched["annual_principal"])


def test_amortizing_schedule_pays_down_principal():
    sched = engine._mortgage_schedule(1_000_000, 0.06, 30, 10, interest_only=False)
    # After 10 years of a 30-year amortization, balance should be well below par.
    assert 0 < sched["ending_balance"] < 1_000_000
    # Standard 30yr/6% monthly payment on $1M is about $5,995.51.
    assert sched["monthly_payment"] == pytest.approx(5995.51, abs=1.0)


def test_zero_principal_schedule():
    sched = engine._mortgage_schedule(0, 0.06, 30, 5, interest_only=False)
    assert sched["ending_balance"] == 0
    assert sum(sched["annual_debt_service"]) == 0


# --------------------------------------------------------------------------- #
# Lease cash flow
# --------------------------------------------------------------------------- #

def test_lease_rent_escalation():
    lease = engine.normalize_scenario(
        {"leases": [{"tenant": "T", "suite_sf": 1000, "start_year": 1,
                     "term_years": 5, "base_rent_psf": 30, "annual_escalation_pct": 0.03}]}
    )["leases"][0]
    assert engine._lease_rent(lease, 1) == pytest.approx(30_000)
    assert engine._lease_rent(lease, 2) == pytest.approx(30_000 * 1.03)
    # Outside the term -> no rent
    assert engine._lease_rent(lease, 6) == 0.0
    assert engine._lease_rent(lease, 0) == 0.0


def test_free_rent_prorates_first_year():
    lease = engine.normalize_scenario(
        {"leases": [{"tenant": "T", "suite_sf": 1000, "start_year": 1, "term_years": 5,
                     "base_rent_psf": 12, "annual_escalation_pct": 0.0,
                     "free_rent_months": 3}]}
    )["leases"][0]
    # 3 months free -> 9/12 of $12,000
    assert engine._lease_rent(lease, 1) == pytest.approx(9_000)
    assert engine._lease_rent(lease, 2) == pytest.approx(12_000)


# --------------------------------------------------------------------------- #
# Full analysis
# --------------------------------------------------------------------------- #

def test_sample_analysis_shape_and_sanity():
    result = engine.analyze(engine.sample_scenario())

    assert len(result["cash_flow"]) == 10
    assert len(result["years"]) == 10
    assert result["years"][0] == 2026

    m = result["metrics"]
    # Going-in cap rate for a stabilized office deal lands in a plausible band.
    assert 0.03 < m["going_in_cap_rate"] < 0.10
    # NOI should be positive.
    assert m["year1_noi"] > 0
    # Unlevered IRR should be a real, plausible number.
    assert m["unlevered_irr"] is not None
    assert -0.1 < m["unlevered_irr"] < 0.40
    # Levered IRR should exist and exceed unlevered IRR (positive leverage here).
    assert m["debt"]["levered_irr"] is not None
    assert m["debt"]["levered_irr"] > m["unlevered_irr"]


def test_noi_identity():
    """NOI must equal EGI minus operating expenses for every year."""
    result = engine.analyze(engine.sample_scenario())
    for row in result["cash_flow"]:
        assert row["noi"] == pytest.approx(
            row["effective_gross_revenue"] + row["operating_expenses"], abs=0.5
        )
        assert row["unlevered_cash_flow"] == pytest.approx(
            row["noi"] + row["capital_reserve"], abs=0.5
        )


def test_terminal_value_uses_forward_noi():
    result = engine.analyze(engine.sample_scenario())
    m = result["metrics"]
    assert m["terminal_value"] == pytest.approx(
        m["forward_noi"] / m["exit_cap_rate"], rel=1e-4
    )
    assert m["net_reversion"] == pytest.approx(m["terminal_value"] * 0.98, rel=1e-4)


def test_higher_exit_cap_lowers_value():
    base = engine.sample_scenario()
    low = engine.analyze({**base, "analysis": {**base["analysis"], "exit_cap_rate": 0.055}})
    high = engine.analyze({**base, "analysis": {**base["analysis"], "exit_cap_rate": 0.085}})
    assert high["metrics"]["dcf_value"] < low["metrics"]["dcf_value"]


def test_empty_scenario_does_not_crash():
    result = engine.analyze({})
    assert result["metrics"]["year1_noi"] == 0
    assert result["metrics"]["unlevered_irr"] is None


def test_occupancy_reflects_lease_rollover():
    result = engine.analyze(engine.sample_scenario())
    rows = {r["year_index"]: r for r in result["cash_flow"]}
    # Year 1: anchor(45k)+health(28k)+advisory(15k) = 88k of 100k -> 88%
    assert rows[1]["occupancy_pct"] == pytest.approx(0.88, abs=1e-6)
    # Year 6: advisory(15k) rolled, second-gen(15k) comes online, health still in -> 88k
    assert rows[6]["occupancy_pct"] == pytest.approx(0.88, abs=1e-6)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
