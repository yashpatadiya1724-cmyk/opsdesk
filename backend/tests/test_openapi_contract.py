"""
Test contract consistency: contracts/openapi.json must strictly match app.openapi().
If backend routes, schemas, or descriptions change, developers must run
`python scripts/export_openapi.py` to keep the committed OpenAPI contract in sync.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.app.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OPENAPI_CONTRACT_PATH = REPO_ROOT / "contracts" / "openapi.json"


def test_openapi_contract_matches_app_spec():
    assert OPENAPI_CONTRACT_PATH.exists(), f"Contract file not found at {OPENAPI_CONTRACT_PATH}"

    with open(OPENAPI_CONTRACT_PATH, "r", encoding="utf-8") as f:
        committed_spec = json.load(f)

    current_spec = app.openapi()

    # Verify both serialize to identical formatted JSON
    committed_str = json.dumps(committed_spec, indent=2, sort_keys=True) + "\n"
    current_str = json.dumps(current_spec, indent=2, sort_keys=True) + "\n"

    assert committed_str == current_str, (
        "OpenAPI contract in contracts/openapi.json is out of sync with app.openapi(). "
        "Run `python scripts/export_openapi.py` to update the committed specification."
    )


def test_openapi_contract_critical_routes_present():
    with open(OPENAPI_CONTRACT_PATH, "r", encoding="utf-8") as f:
        committed_spec = json.load(f)

    paths = committed_spec.get("paths", {})
    assert "/ready" in paths, "/ready probe must be present in OpenAPI contract"
    assert "/health" in paths, "/health probe must be present in OpenAPI contract"
    assert "/api/auth/login" in paths, "/api/auth/login endpoint must be present in OpenAPI contract"
    assert "/api/ai/suggest-intent" in paths, "/api/ai/suggest-intent must be in contract"
    assert "/api/ai/stats" in paths, "/api/ai/stats must be in contract"
    assert "/api/tickets" in paths, "/api/tickets must be in contract"
