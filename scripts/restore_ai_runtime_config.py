"""Restore production AI runtime config from the tracked production snapshot."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "runtime" / "ai_runtime_config.production.json"
TARGET = ROOT / "data" / "runtime" / "ai_runtime_config.json"


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"Missing production config snapshot: {SOURCE}")
    shutil.copyfile(SOURCE, TARGET)
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    print(f"Restored {TARGET}")
    print(f"llmModelPath={payload.get('llmModelPath', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
