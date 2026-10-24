"""Flask REST API for the ARGUS-style CRE valuation engine.

Endpoints
---------
GET  /api/health              -> liveness check
GET  /api/sample              -> the default sample scenario
POST /api/analyze             -> run a valuation on a posted scenario
GET  /api/scenarios           -> list saved scenarios (in-memory)
POST /api/scenarios           -> save a scenario
GET  /api/scenarios/<id>      -> fetch one saved scenario
PUT  /api/scenarios/<id>      -> update a saved scenario
DELETE /api/scenarios/<id>    -> delete a saved scenario

The scenario store is intentionally in-memory: this is a demo/analysis tool,
not a system of record. Swap it for a database by replacing ``_STORE``.
"""

from __future__ import annotations

import uuid

from flask import Flask, jsonify, request
from flask_cors import CORS

import engine

app = Flask(__name__)
CORS(app)

# In-memory scenario store: {id: {"id", "name", "scenario"}}
_STORE: dict[str, dict] = {}


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
        result = engine.analyze(scenario)
    except Exception as exc:  # noqa: BLE001 - surface any modeling error cleanly
        return jsonify({"error": f"Analysis failed: {exc}"}), 400
    return jsonify(result)


@app.get("/api/scenarios")
def list_scenarios():
    return jsonify([
        {"id": s["id"], "name": s["name"]}
        for s in sorted(_STORE.values(), key=lambda s: s["name"].lower())
    ])


@app.post("/api/scenarios")
def create_scenario():
    body = request.get_json(silent=True) or {}
    scenario = body.get("scenario")
    if scenario is None:
        return jsonify({"error": "Body must include a 'scenario' object."}), 400
    sid = uuid.uuid4().hex[:12]
    name = str(body.get("name")
               or scenario.get("property", {}).get("name")
               or "Untitled Scenario")
    _STORE[sid] = {"id": sid, "name": name, "scenario": scenario}
    return jsonify(_STORE[sid]), 201


@app.get("/api/scenarios/<sid>")
def get_scenario(sid: str):
    item = _STORE.get(sid)
    if not item:
        return jsonify({"error": "Scenario not found."}), 404
    return jsonify(item)


@app.put("/api/scenarios/<sid>")
def update_scenario(sid: str):
    item = _STORE.get(sid)
    if not item:
        return jsonify({"error": "Scenario not found."}), 404
    body = request.get_json(silent=True) or {}
    if "scenario" in body:
        item["scenario"] = body["scenario"]
    if "name" in body:
        item["name"] = str(body["name"])
    return jsonify(item)


@app.delete("/api/scenarios/<sid>")
def delete_scenario(sid: str):
    if sid in _STORE:
        del _STORE[sid]
        return "", 204
    return jsonify({"error": "Scenario not found."}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
