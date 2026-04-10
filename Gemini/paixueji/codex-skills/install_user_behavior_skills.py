#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


SKILL_NAMES = [
    "mapping-user-behavior",
    "discovering-user-behavior-foundation",
    "mapping-user-state-transitions",
    "cataloging-user-behavior-scenarios",
    "auditing-user-behavior-coverage",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the user-behavior workflow skills into ~/.agents/skills."
    )
    parser.add_argument(
        "--mode",
        choices=("symlink", "copy"),
        default="symlink",
        help="Install as symlinks or copy directories into the target namespace.",
    )
    parser.add_argument(
        "--target-root",
        default="~/.agents/skills",
        help="Target skill namespace root. Defaults to ~/.agents/skills.",
    )
    return parser.parse_args()


def install_skill(source_dir: Path, target_dir: Path, mode: str) -> None:
    if target_dir.exists() or target_dir.is_symlink():
        if target_dir.is_symlink() or target_dir.is_file():
            target_dir.unlink()
        else:
            shutil.rmtree(target_dir)

    if mode == "copy":
        shutil.copytree(source_dir, target_dir)
        return

    target_dir.symlink_to(source_dir, target_is_directory=True)


def main() -> int:
    args = parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    source_root = repo_root / "codex-skills" / "user-behavior-workflow" / "global"
    target_root = Path(os.path.expanduser(args.target_root)).resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    for skill_name in SKILL_NAMES:
        source_dir = source_root / skill_name
        if not source_dir.exists():
            raise FileNotFoundError(f"missing skill source: {source_dir}")
        install_skill(source_dir, target_root / skill_name, args.mode)

    print(f"Installed {len(SKILL_NAMES)} user-behavior skills to {target_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
