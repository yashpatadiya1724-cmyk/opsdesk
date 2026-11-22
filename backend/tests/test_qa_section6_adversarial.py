"""
Adversarial QA Suite for Section 6 (Housekeeping):
1. OpenAPI spec drift sensitivity & diagnostic verification.
2. ADR numbering consistency, sequence gaps, duplicates, and README index link integrity.
3. README environment variable parity, default value matching, and dead variable detection.
"""
from __future__ import annotations

import os
import re
import json
from pathlib import Path
import pytest

from backend.app.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OPENAPI_CONTRACT_PATH = REPO_ROOT / "contracts" / "openapi.json"
ADR_DIR = REPO_ROOT / "docs" / "adr"
ADR_README_PATH = ADR_DIR / "README.md"
README_PATH = REPO_ROOT / "README.md"


# ============================================================================
# REPRODUCTION 1: OpenAPI Spec Drift Detection & Sensitivity
# ============================================================================

def test_openapi_contract_matches_app_spec():
    """Verifies that the committed OpenAPI contract is 100% in sync with the FastAPI app."""
    assert OPENAPI_CONTRACT_PATH.exists(), f"Contract file not found at {OPENAPI_CONTRACT_PATH}"

    with open(OPENAPI_CONTRACT_PATH, "r", encoding="utf-8") as f:
        committed_spec = json.load(f)

    current_spec = app.openapi()

    committed_str = json.dumps(committed_spec, indent=2, sort_keys=True) + "\n"
    current_str = json.dumps(current_spec, indent=2, sort_keys=True) + "\n"

    assert committed_str == current_str, (
        "OpenAPI contract in contracts/openapi.json is out of sync with app.openapi(). "
        "Run `python scripts/export_openapi.py` to update the committed specification."
    )


def test_adversarial_openapi_drift_causes_test_failure():
    """
    ADVERSARIAL REPRODUCTION 1:
    Altering an endpoint or schema in contracts/openapi.json MUST trigger an assertion
    failure with the exact diagnostic instruction to run `python scripts/export_openapi.py`.
    """
    with open(OPENAPI_CONTRACT_PATH, "r", encoding="utf-8") as f:
        committed_spec = json.load(f)

    current_spec = app.openapi()

    # Create mutated spec with adversarial phantom route
    mutated_spec = json.loads(json.dumps(committed_spec))
    mutated_spec["paths"]["/api/adversarial_dummy_route"] = {
        "get": {"summary": "Adversarial Route", "responses": {"200": {"description": "OK"}}}
    }

    committed_str = json.dumps(mutated_spec, indent=2, sort_keys=True) + "\n"
    current_str = json.dumps(current_spec, indent=2, sort_keys=True) + "\n"

    with pytest.raises(AssertionError) as exc_info:
        assert committed_str == current_str, (
            "OpenAPI contract in contracts/openapi.json is out of sync with app.openapi(). "
            "Run `python scripts/export_openapi.py` to update the committed specification."
        )

    assert "scripts/export_openapi.py" in str(exc_info.value)


# ============================================================================
# REPRODUCTION 2: ADR Numbering Consistency & Index Link Completeness
# ============================================================================

def test_adr_numbering_and_index_integrity():
    """
    ADVERSARIAL REPRODUCTION 2:
    Verifies ADRs 0001 through 0009:
    - All files exist on disk
    - Numbering is sequential with no missing numbers and no duplicates
    - All ADRs are hyperlinked in docs/adr/README.md
    - Standard ADR sections exist in every file
    """
    assert ADR_DIR.exists() and ADR_DIR.is_dir(), f"ADR directory not found at {ADR_DIR}"
    assert ADR_README_PATH.exists(), f"ADR README index not found at {ADR_README_PATH}"

    # 1. Collect all ADR files matching 0NNN-*.md
    adr_files = sorted([f.name for f in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")])
    assert len(adr_files) == 9, f"Expected exactly 9 ADR files (0001-0009), found {len(adr_files)}: {adr_files}"

    extracted_numbers = []
    for fname in adr_files:
        match = re.match(r"^(\d{4})-(.+)\.md$", fname)
        assert match is not None, f"ADR filename '{fname}' does not follow NNNN-slug.md convention"
        extracted_numbers.append(int(match.group(1)))

    # Verify no duplicates
    assert len(extracted_numbers) == len(set(extracted_numbers)), f"Duplicate ADR numbers found: {extracted_numbers}"

    # Verify contiguous sequence 1..9
    expected_sequence = list(range(1, 10))
    assert extracted_numbers == expected_sequence, f"ADR numbering gap detected: {extracted_numbers} != {expected_sequence}"

    # 2. Check README.md index links
    readme_content = ADR_README_PATH.read_text(encoding="utf-8")
    for fname in adr_files:
        num_str = fname.split("-")[0]
        # Must have markdown link [000X](000X-slug.md)
        expected_link_pattern = rf"\[{num_str}\]\({re.escape(fname)}\)"
        assert re.search(expected_link_pattern, readme_content), (
            f"ADR '{fname}' is not properly hyperlinked in docs/adr/README.md"
        )

    # 3. Check ADR content format
    required_sections = ["# ADR ", "## Status", "## Context", "## Decision", "## Consequences"]
    for fname in adr_files:
        content = (ADR_DIR / fname).read_text(encoding="utf-8")
        for sec in required_sections:
            assert sec in content, f"ADR {fname} missing required section header: '{sec}'"


# ============================================================================
# REPRODUCTION 3: Documentation and Environment Variable Parity
# ============================================================================

def test_readme_environment_variable_parity():
    """
    ADVERSARIAL REPRODUCTION 3:
    Ensures all environment variables documented in README.md exist, are read in
    the backend codebase, and their documented defaults match code defaults.
    """
    assert README_PATH.exists(), "README.md not found"
    readme_text = README_PATH.read_text(encoding="utf-8")

    # Extract Environment Variables table
    table_match = re.search(r"#### Environment Variables Reference.*?\n(\| :---.*?)(?=\n\n|\n###)", readme_text, re.DOTALL)
    assert table_match is not None, "Could not find Environment Variables Reference table in README.md"

    table_lines = [line.strip() for line in table_match.group(1).splitlines() if line.startswith("| `")]
    documented_vars = {}
    for line in table_lines:
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 2:
            var_name = parts[0].replace("`", "")
            default_val = parts[1].replace("`", "")
            documented_vars[var_name] = default_val

    # Expected documented variables
    expected_vars = {
        "APP_ENV", "AUTH_MODE", "ALLOW_DEMO_AUTH", "JWT_SECRET", "BCRYPT_ROUNDS",
        "RATE_LIMIT_BACKEND", "REDIS_URL", "RATE_LIMIT_FAIL_MODE",
        "RATE_LIMIT_TICKET_CREATE_USER_PER_MINUTE", "RATE_LIMIT_TICKET_CREATE_AGENCY_PER_HOUR",
        "RATE_LIMIT_AI_SUGGEST_USER_PER_MINUTE", "MAX_BODY_BYTES",
        "SCORE_REFRESHER_ENABLED", "SCORE_REFRESHER_INTERVAL",
        "GEMINI_MAX_WORKERS", "GEMINI_REDACT_PII", "GEMINI_CACHE_ENABLED"
    }

    missing_from_docs = expected_vars - set(documented_vars.keys())
    assert not missing_from_docs, f"README.md is missing documentation for: {missing_from_docs}"

    # Audit 1: Verify GEMINI_CACHE_ENABLED is actually implemented in intent_classifier.py
    intent_classifier_code = (REPO_ROOT / "backend" / "services" / "intent_classifier.py").read_text(encoding="utf-8")
    assert "GEMINI_CACHE_ENABLED" in intent_classifier_code, (
        "GEMINI_CACHE_ENABLED is documented in README.md but NEVER read or checked in backend/services/intent_classifier.py"
    )

    # Audit 2: Verify GEMINI_MAX_WORKERS default in code matches README documentation ('5')
    worker_default_match = re.search(r'os\.getenv\("GEMINI_MAX_WORKERS",\s*"(\d+)"\)', intent_classifier_code)
    assert worker_default_match is not None, "GEMINI_MAX_WORKERS fallback parsing not found in intent_classifier.py"
    code_max_workers_default = worker_default_match.group(1)
    assert code_max_workers_default == documented_vars["GEMINI_MAX_WORKERS"], (
        f"GEMINI_MAX_WORKERS default mismatch: README documents '{documented_vars['GEMINI_MAX_WORKERS']}', "
        f"but code defaults to '{code_max_workers_default}'"
    )

    # Audit 3: Verify RATE_LIMIT_BACKEND evaluates 'memory'
    rate_limiter_code = (REPO_ROOT / "backend" / "app" / "rate_limiter.py").read_text(encoding="utf-8")
    assert '"memory"' in rate_limiter_code or "'memory'" in rate_limiter_code, (
        "RATE_LIMIT_BACKEND default convention mismatch in backend/app/rate_limiter.py"
    )
