"""Flask REST API for the ARGUS-style CRE valuation engine.

Endpoints
---------
GET  /api/health              -> liveness check
GET  /api/sample              -> the default sample scenario
POST /api/analyze             -> run a valuation on a posted scenario
GET  /api/scenarios           -> list saved scenarios
POST /api/scenarios           -> save a scenario
GET  /api/scenarios/<id>      -> fetch one saved scenario
PUT  /api/scenarios/<id>      -> update a saved scenario
DELETE /api/scenarios/<id>    -> delete a saved scenario

Saved scenarios persist to a JSON file on disk (``scenarios.json``) so they
survive restarts; set ARGUS_STORE_PATH to relocate it.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid

from flask import Flask, jsonify, request
from flask_cors import CORS

import engine

app = Flask(__name__)
CORS(app)

STORE_PATH = os.environ.get(
    "ARGUS_STORE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios.json"),
)
_lock = threading.Lock()


def _load() -> dict[str, dict]:
    try:
        with open(STORE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(store: dict[str, dict]) -> None:
    """Atomic write: dump to a temp file in the same dir, then replace."""
    directory = os.path.dirname(STORE_PATH) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2)
        os.replace(tmp, STORE_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


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
    store = _load()
    return jsonify([
        {"id": s["id"], "name": s["name"]}
        for s in sorted(store.values(), key=lambda s: s["name"].lower())
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
    item = {"id": sid, "name": name, "scenario": scenario}
    with _lock:
        store = _load()
        store[sid] = item
        _save(store)
    return jsonify(item), 201


@app.get("/api/scenarios/<sid>")
def get_scenario(sid: str):
    item = _load().get(sid)
    if not item:
        return jsonify({"error": "Scenario not found."}), 404
    return jsonify(item)


@app.put("/api/scenarios/<sid>")
def update_scenario(sid: str):
    body = request.get_json(silent=True) or {}
    with _lock:
        store = _load()
        item = store.get(sid)
        if not item:
            return jsonify({"error": "Scenario not found."}), 404
        if "scenario" in body:
            item["scenario"] = body["scenario"]
        if "name" in body:
            item["name"] = str(body["name"])
        store[sid] = item
        _save(store)
    return jsonify(item)


@app.delete("/api/scenarios/<sid>")
def delete_scenario(sid: str):
    with _lock:
        store = _load()
        if sid in store:
            del store[sid]
            _save(store)
            return "", 204
    return jsonify({"error": "Scenario not found."}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
