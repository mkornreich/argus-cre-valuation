"""Flask REST API for the ARGUS-style CRE valuation engine.

Endpoints
---------
GET  /api/health                      liveness check
GET  /api/sample                      default sample scenario
POST /api/analyze                     run a valuation
POST /api/report                      download an .xlsx report pack
POST /api/import/rentroll             parse a CSV rent roll into leases
POST /api/portfolio                   consolidate deals (by id or inline)

Saved scenarios (versioned):
GET  /api/scenarios                   list
POST /api/scenarios                   save (creates version 1)
GET|PUT|DELETE /api/scenarios/<id>    fetch / update (new version) / delete
GET  /api/scenarios/<id>/versions     list a scenario's version history

Named portfolios:
GET  /api/portfolios                  list
POST /api/portfolios                  save {name, ids, fund_debt}
GET|DELETE /api/portfolios/<id>       consolidate / delete

Scenarios and portfolios persist to JSON files (atomic writes).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import tempfile
import threading
import uuid

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

import engine
import report

app = Flask(__name__)
CORS(app)

_DIR = os.path.dirname(os.path.abspath(__file__))
SCENARIO_PATH = os.environ.get("ARGUS_STORE_PATH", os.path.join(_DIR, "scenarios.json"))
PORTFOLIO_PATH = os.environ.get("ARGUS_PORTFOLIO_PATH", os.path.join(_DIR, "portfolios.json"))
_lock = threading.Lock()


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(path: str, store: dict) -> None:
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Core valuation
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "argus-engine"})


@app.get("/api/sample")
def sample():
    return jsonify(engine.sample_scenario())


@app.post("/api/analyze")
def analyze():
    scenario = request.get_json(silent=True)
    if scenario is None:
        return jsonify({"error": "Request body must be a JSON scenario object."}), 400
    try:
        return jsonify(engine.analyze(scenario))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Analysis failed: {exc}"}), 400


@app.post("/api/report")
def download_report():
    scenario = request.get_json(silent=True)
    if scenario is None:
        return jsonify({"error": "Request body must be a JSON scenario object."}), 400
    try:
        buf = report.build_report(scenario)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Report failed: {exc}"}), 400
    name = (scenario.get("property", {}).get("name") or "argus-report").replace(" ", "_")
    return send_file(buf, as_attachment=True, download_name=f"{name}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --------------------------------------------------------------------------- #
# Rent-roll CSV import
# --------------------------------------------------------------------------- #

_COLMAP = {
    "tenant": "tenant", "name": "tenant", "suite": "tenant",
    "sf": "suite_sf", "suite_sf": "suite_sf", "squarefeet": "suite_sf", "area": "suite_sf",
    "startyear": "start_year", "start_year": "start_year", "start": "start_year",
    "term": "term_years", "termyears": "term_years", "term_years": "term_years",
    "rent": "base_rent_psf", "rentpsf": "base_rent_psf", "baserent": "base_rent_psf",
    "base_rent_psf": "base_rent_psf", "rent_psf": "base_rent_psf",
    "escalation": "annual_escalation_pct", "esc": "annual_escalation_pct", "bumps": "annual_escalation_pct",
    "reimbursement": "reimbursement_method", "recovery": "reimbursement_method",
    "freerent": "free_rent_months", "free": "free_rent_months", "free_rent_months": "free_rent_months",
}
_NUMERIC = {"suite_sf", "start_year", "term_years", "base_rent_psf", "annual_escalation_pct",
            "free_rent_months"}


def _norm_key(k: str) -> str:
    return "".join(ch for ch in k.lower() if ch.isalnum() or ch == "_")


@app.post("/api/import/rentroll")
def import_rentroll():
    body = request.get_json(silent=True) or {}
    text = body.get("csv")
    if not text:
        return jsonify({"error": "Body must include CSV text under 'csv'."}), 400
    try:
        reader = csv.DictReader(io.StringIO(text.strip()))
        leases = []
        for raw in reader:
            lease = {}
            for key, val in raw.items():
                if key is None or val is None or val == "":
                    continue
                field = _COLMAP.get(_norm_key(key))
                if not field:
                    continue
                v = val.strip().replace("$", "").replace(",", "").replace("%", "")
                if field in _NUMERIC:
                    try:
                        num = float(v)
                    except ValueError:
                        continue
                    # Accept escalation as 3 or 0.03.
                    if field == "annual_escalation_pct" and num > 1:
                        num /= 100.0
                    lease[field] = num
                else:
                    lease[field] = val.strip()
            if lease.get("suite_sf"):
                leases.append(lease)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Could not parse CSV: {exc}"}), 400
    if not leases:
        return jsonify({"error": "No valid lease rows found. Expected headers like "
                                 "tenant, sf, start_year, term, rent."}), 400
    return jsonify({"leases": leases, "count": len(leases)})


# --------------------------------------------------------------------------- #
# Saved scenarios (versioned)
# --------------------------------------------------------------------------- #

@app.get("/api/scenarios")
def list_scenarios():
    store = _load(SCENARIO_PATH)
    return jsonify([{"id": s["id"], "name": s["name"], "versions": len(s.get("versions", []))}
                    for s in sorted(store.values(), key=lambda s: s["name"].lower())])


@app.post("/api/scenarios")
def create_scenario():
    body = request.get_json(silent=True) or {}
    scenario = body.get("scenario")
    if scenario is None:
        return jsonify({"error": "Body must include a 'scenario' object."}), 400
    sid = uuid.uuid4().hex[:12]
    name = str(body.get("name") or scenario.get("property", {}).get("name") or "Untitled Scenario")
    item = {"id": sid, "name": name, "scenario": scenario,
            "versions": [{"ts": _now(), "scenario": scenario}]}
    with _lock:
        store = _load(SCENARIO_PATH)
        store[sid] = item
        _save(SCENARIO_PATH, store)
    return jsonify(item), 201


@app.get("/api/scenarios/<sid>")
def get_scenario(sid):
    item = _load(SCENARIO_PATH).get(sid)
    return (jsonify(item), 200) if item else (jsonify({"error": "Scenario not found."}), 404)


@app.put("/api/scenarios/<sid>")
def update_scenario(sid):
    body = request.get_json(silent=True) or {}
    with _lock:
        store = _load(SCENARIO_PATH)
        item = store.get(sid)
        if not item:
            return jsonify({"error": "Scenario not found."}), 404
        if "scenario" in body:
            item["scenario"] = body["scenario"]
            item.setdefault("versions", []).append({"ts": _now(), "scenario": body["scenario"]})
        if "name" in body:
            item["name"] = str(body["name"])
        store[sid] = item
        _save(SCENARIO_PATH, store)
    return jsonify(item)


@app.get("/api/scenarios/<sid>/versions")
def scenario_versions(sid):
    item = _load(SCENARIO_PATH).get(sid)
    if not item:
        return jsonify({"error": "Scenario not found."}), 404
    versions = item.get("versions", [])
    return jsonify([{"index": i, "ts": v["ts"]} for i, v in enumerate(versions)])


@app.delete("/api/scenarios/<sid>")
def delete_scenario(sid):
    with _lock:
        store = _load(SCENARIO_PATH)
        if sid in store:
            del store[sid]
            _save(SCENARIO_PATH, store)
            return "", 204
    return jsonify({"error": "Scenario not found."}), 404


# --------------------------------------------------------------------------- #
# Portfolio consolidation + named portfolios
# --------------------------------------------------------------------------- #

def _resolve(ids, inline):
    store = _load(SCENARIO_PATH)
    scenarios = [store[sid]["scenario"] for sid in (ids or []) if sid in store]
    scenarios.extend(inline or [])
    return scenarios


@app.post("/api/portfolio")
def portfolio():
    body = request.get_json(silent=True) or {}
    scenarios = _resolve(body.get("ids"), body.get("scenarios"))
    if not scenarios:
        return jsonify({"error": "Provide at least one scenario (by id or inline)."}), 400
    try:
        return jsonify(engine.consolidate(scenarios, fund_debt=body.get("fund_debt")))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Consolidation failed: {exc}"}), 400


@app.get("/api/portfolios")
def list_portfolios():
    store = _load(PORTFOLIO_PATH)
    return jsonify([{"id": p["id"], "name": p["name"], "deals": len(p.get("ids", []))}
                    for p in sorted(store.values(), key=lambda p: p["name"].lower())])


@app.post("/api/portfolios")
def create_portfolio():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "Untitled Portfolio")
    pid = uuid.uuid4().hex[:12]
    item = {"id": pid, "name": name, "ids": body.get("ids", []),
            "fund_debt": body.get("fund_debt"), "ts": _now()}
    with _lock:
        store = _load(PORTFOLIO_PATH)
        store[pid] = item
        _save(PORTFOLIO_PATH, store)
    return jsonify(item), 201


@app.get("/api/portfolios/<pid>")
def get_portfolio(pid):
    item = _load(PORTFOLIO_PATH).get(pid)
    if not item:
        return jsonify({"error": "Portfolio not found."}), 404
    scenarios = _resolve(item.get("ids"), None)
    if not scenarios:
        return jsonify({"error": "Portfolio has no resolvable deals."}), 400
    result = engine.consolidate(scenarios, fund_debt=item.get("fund_debt"))
    result["portfolio"] = {"id": item["id"], "name": item["name"]}
    return jsonify(result)


@app.delete("/api/portfolios/<pid>")
def delete_portfolio(pid):
    with _lock:
        store = _load(PORTFOLIO_PATH)
        if pid in store:
            del store[pid]
            _save(PORTFOLIO_PATH, store)
            return "", 204
    return jsonify({"error": "Portfolio not found."}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
