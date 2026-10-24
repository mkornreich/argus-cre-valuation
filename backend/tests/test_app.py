"""API tests: report pack, CSV import, portfolios, versioning."""

import io

import openpyxl
import pytest

import app as app_module
import engine


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "SCENARIO_PATH", str(tmp_path / "scenarios.json"))
    monkeypatch.setattr(app_module, "PORTFOLIO_PATH", str(tmp_path / "portfolios.json"))
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_report_pack_has_all_sheets(client):
    resp = client.post("/api/report", json=engine.sample_scenario())
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["Content-Type"]
    wb = openpyxl.load_workbook(io.BytesIO(resp.data))
    assert wb.sheetnames == ["Summary", "Cash Flow (Annual)", "Cash Flow (Monthly)",
                             "Rent Roll", "Sensitivity", "Traditional Valuation"]


def test_import_rentroll_parses_csv(client):
    csv = "tenant,sf,start_year,term,rent,escalation\nAcme,20000,1,7,29.5,3\nBeta,12000,1,5,31,2.5"
    resp = client.post("/api/import/rentroll", json={"csv": csv})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 2
    assert data["leases"][0]["suite_sf"] == 20000
    assert data["leases"][0]["annual_escalation_pct"] == pytest.approx(0.03)  # 3 -> 0.03


def test_import_rentroll_rejects_junk(client):
    assert client.post("/api/import/rentroll", json={"csv": "foo,bar\n1,2"}).status_code == 400


def test_portfolio_with_fund_debt(client):
    sc = engine.sample_scenario()
    resp = client.post("/api/portfolio",
                       json={"scenarios": [sc, sc], "fund_debt": {"ltv_pct": 0.5, "interest_rate": 0.055}})
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["assets"]) == 2
    assert data["fund_debt"]["fund_levered_irr"] is not None


def test_scenario_versioning(client):
    sc = engine.sample_scenario()
    created = client.post("/api/scenarios", json={"name": "Deal", "scenario": sc}).get_json()
    sid = created["id"]
    updated = {**sc, "analysis": {**sc["analysis"], "purchase_price": 30_000_000}}
    client.put(f"/api/scenarios/{sid}", json={"scenario": updated})
    versions = client.get(f"/api/scenarios/{sid}/versions").get_json()
    assert len(versions) == 2


def test_named_portfolio_roundtrip(client):
    sc = engine.sample_scenario()
    s1 = client.post("/api/scenarios", json={"name": "A", "scenario": sc}).get_json()
    s2 = client.post("/api/scenarios", json={"name": "B", "scenario": sc}).get_json()
    p = client.post("/api/portfolios", json={"name": "Fund", "ids": [s1["id"], s2["id"]]}).get_json()
    loaded = client.get(f"/api/portfolios/{p['id']}").get_json()
    assert loaded["portfolio"]["name"] == "Fund"
    assert loaded["totals"]["purchase_price"] == pytest.approx(57_000_000)
