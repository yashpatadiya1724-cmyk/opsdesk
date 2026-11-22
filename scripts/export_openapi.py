#!/usr/bin/env python3
"""
Export OpenAPI specification from backend.app.main:app to contracts/openapi.json.
Ensures reproducible formatting with sorted keys and 2-space indentation.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.main import app  # noqa: E402


def export_openapi(target_path: Path | None = None) -> Path:
    if target_path is None:
        target_path = REPO_ROOT / "contracts" / "openapi.json"

    openapi_spec = app.openapi()

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(openapi_spec, f, indent=2, sort_keys=True)
        f.write("\n")

    return target_path


def main() -> None:
    output_path = export_openapi()
    paths_count = len(app.openapi().get("paths", {}))
    print(f"Exported OpenAPI spec to {output_path} ({paths_count} routes)")


if __name__ == "__main__":
    main()
