from __future__ import annotations


def build_chat_kb_context(
    object_name: str,
    physical_dimensions: dict | None,
    engagement_dimensions: dict | None,
) -> str:
    physical = physical_dimensions or {}
    engagement = engagement_dimensions or {}

    if not physical and not engagement:
        return ""

    lines = [f"Current-object KB for {object_name}:"]

    for dimension, attrs in physical.items():
        if not attrs:
            continue
        lines.append(f"[physical.{dimension}]")
        for attribute, value in attrs.items():
            lines.append(f"  - {attribute.replace('_', ' ')}: {value}")

    for dimension, seeds in engagement.items():
        if not seeds:
            continue
        lines.append(f"[engagement.{dimension}]")
        for seed_text in seeds:
            lines.append(f"  - {seed_text}")

    return "\n".join(lines)


def build_intro_kb_context(
    object_name: str,
    physical_dimensions: dict | None,
) -> str:
    physical = physical_dimensions or {}
    if not physical:
        return ""

    lines = [f"Intro grounding for {object_name}:"]

    for dimension, attrs in physical.items():
        if not attrs:
            continue
        lines.append(f"[physical.{dimension}]")
        for attribute, value in attrs.items():
            lines.append(f"  - {attribute.replace('_', ' ')}: {value}")

    return "\n".join(lines)


def build_bridge_activation_grounding_context(
    object_name: str,
    physical_dimensions: dict | None,
    engagement_dimensions: dict | None,
) -> str:
    return build_chat_kb_context(
        object_name=object_name,
        physical_dimensions=physical_dimensions,
        engagement_dimensions=engagement_dimensions,
    )
