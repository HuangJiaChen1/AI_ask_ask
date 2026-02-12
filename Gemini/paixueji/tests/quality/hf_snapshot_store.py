"""
Snapshot helpers for HF replay bundles.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def compute_runtime_snapshot_version(project_root: str | Path | None = None) -> str:
    """
    Compute a fingerprint of key runtime inputs that affect model behavior.
    """
    root = Path(project_root) if project_root else Path(__file__).parent.parent.parent
    files_to_hash = [
        "config.json",
        "age_prompts.json",
        "object_prompts.json",
        "paixueji_prompts.py",
        "graph.py",
        "stream/validation.py",
        "stream/response_generators.py",
        "stream/question_generators.py",
        "stream/guide_hint.py",
        "stream/theme_guide.py",
        "stream/focus_mode.py",
    ]

    hasher = hashlib.sha256()
    for rel_path in files_to_hash:
        path = root / rel_path
        if not path.exists():
            continue
        hasher.update(rel_path.encode("utf-8"))
        hasher.update(path.read_bytes())

    return hasher.hexdigest()


def load_bundle(path: str | Path) -> dict[str, Any]:
    bundle_path = Path(path)
    with open(bundle_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_bundle(path: str | Path, bundle: dict[str, Any]) -> None:
    bundle_path = Path(path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)


def is_bundle_snapshot_compatible(
    bundle: dict[str, Any],
    project_root: str | Path | None = None,
) -> tuple[bool, str]:
    current = compute_runtime_snapshot_version(project_root)
    recorded = bundle.get("snapshot_version", "")
    return (recorded == current, current)
