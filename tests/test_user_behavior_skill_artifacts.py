from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
GLOBAL_SKILLS_ROOT = REPO_ROOT / "codex-skills" / "user-behavior-workflow" / "global"
ADAPTER_ROOT = REPO_ROOT / "codex-skills" / "user-behavior-adapter"
INSTALLER_PATH = REPO_ROOT / "codex-skills" / "install_user_behavior_skills.py"

EXPECTED_GLOBAL_SKILLS = {
    "mapping-user-behavior",
    "discovering-user-behavior-foundation",
    "mapping-user-state-transitions",
    "cataloging-user-behavior-scenarios",
    "auditing-user-behavior-coverage",
}


def test_global_skill_sources_exist():
    for skill_name in EXPECTED_GLOBAL_SKILLS:
        skill_path = GLOBAL_SKILLS_ROOT / skill_name / "SKILL.md"
        assert skill_path.exists(), f"missing global skill source: {skill_path}"


def test_local_adapter_manifest_has_required_fields():
    manifest_path = ADAPTER_ROOT / "manifest.yaml"
    assert manifest_path.exists(), f"missing adapter manifest: {manifest_path}"

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)

    required_keys = {
        "product_name",
        "output_path",
        "primary_sources",
        "exclude_paths",
        "surface_hints",
        "state_hints",
        "analytics_sources",
        "unreleased_markers",
    }
    assert required_keys.issubset(manifest), manifest.keys()

    for list_key in (
        "primary_sources",
        "exclude_paths",
        "surface_hints",
        "state_hints",
        "analytics_sources",
        "unreleased_markers",
    ):
        assert isinstance(manifest[list_key], list), f"{list_key} must be a list"


def test_orchestrator_skill_references_child_skills_and_output_contract():
    orchestrator = (
        GLOBAL_SKILLS_ROOT / "mapping-user-behavior" / "SKILL.md"
    ).read_text(encoding="utf-8")

    for skill_name in EXPECTED_GLOBAL_SKILLS - {"mapping-user-behavior"}:
        assert skill_name in orchestrator

    assert "USER_BEHAVIOR_SPEC.md" in orchestrator
    assert "Known unknowns" in orchestrator


def test_installer_tracks_expected_skill_set():
    assert INSTALLER_PATH.exists(), f"missing installer: {INSTALLER_PATH}"

    installer = INSTALLER_PATH.read_text(encoding="utf-8")
    for skill_name in EXPECTED_GLOBAL_SKILLS:
        assert skill_name in installer
