"""
Architecture Manifest for the Paixueji system.

Provides the meta-agent with a structured understanding of:
- Graph topology (nodes, edges, routers)
- Node → prompt mappings
- Per-node state fields
- Dynamic context builder for LLM consumption
"""

import sys
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import paixueji_prompts


# ============================================================================
# Graph Topology (mirrors graph.py:1038-1182)
# ============================================================================

GRAPH_TOPOLOGY = {
    "nodes": [
        "start",
        "analyze_input",
        "route_logic",
        "generate_response",
        "generate_question",
        "generate_fun_fact",
        "start_guide",
        "guide_navigator",
        "guide_driver",
        "guide_success",
        "guide_hint",
        "guide_exit",
        "finalize",
    ],
    "edges": [
        # Direct edges
        {"from": "analyze_input", "to": "route_logic"},
        {"from": "route_logic", "to": "generate_response"},
        {"from": "generate_question", "to": "finalize"},
        {"from": "generate_fun_fact", "to": "generate_response"},
        {"from": "start_guide", "to": "finalize"},
        {"from": "guide_driver", "to": "finalize"},
        {"from": "guide_success", "to": "finalize"},
        {"from": "guide_hint", "to": "finalize"},
        {"from": "guide_exit", "to": "finalize"},
        {"from": "finalize", "to": "END"},
    ],
    "routers": [
        {
            "name": "route_from_start",
            "source": "START",
            "conditions": {
                "guide_phase == 'active'": "guide_navigator",
                "guide_phase == 'hint'": "guide_navigator",
                "response_type == 'introduction'": "generate_fun_fact",
                "default": "analyze_input",
            },
        },
        {
            "name": "route_after_response",
            "source": "generate_response",
            "conditions": {
                "correct_answer_count >= 3 and is_factually_correct (or count >= 4) "
                "AND has guide info (theme + concept + bridge_question)": "start_guide",
                "default": "generate_question",
            },
        },
        {
            "name": "route_after_navigator",
            "source": "guide_navigator",
            "conditions": {
                "guide_strategy == 'COMPLETE' or guide_status == 'COMPLETED'": "guide_success",
                "should_give_hint (max turns, no hint yet)": "guide_hint",
                "should_exit_guide (2x resistance or post-hint timeout)": "guide_exit",
                "default (ON_TRACK, DRIFTING, first RESISTANCE)": "guide_driver",
            },
        },
    ],
}

# ============================================================================
# Response Type → Prompt Mapping
# ============================================================================

RESPONSE_TYPE_TO_PROMPT = {
    "introduction": "introduction_prompt",
    "feedback": "feedback_response_prompt",
    "explanation": "explanation_response_prompt",
    "gentle_correction": "correction_response_prompt",
    "topic_switch": "topic_switch_response_prompt",
    "explicit_switch": None,       # inline in stream/response_generators.py
    "natural_topic_completion": None,  # no dedicated prompt
}

# Guide-phase nodes use inline prompts in stream/theme_guide.py
GUIDE_NODE_PROMPTS = {
    "guide_navigator": "inline in stream/theme_guide.py (ThemeNavigator.analyze_turn)",
    "guide_driver": "inline in stream/theme_guide.py (ThemeDriver.generate_response_stream)",
    "guide_hint": "inline in stream/theme_guide.py (ThemeDriver with scaffold_level=4)",
    "guide_success": "inline in stream/theme_guide.py (success celebration)",
    "guide_exit": "inline in stream/theme_guide.py (graceful exit)",
}

# ============================================================================
# Per-Node State Fields
# ============================================================================

NODE_STATE_FIELDS = {
    "analyze_input": [
        "is_engaged",
        "is_factually_correct",
        "correctness_reasoning",
        "detected_object_name",
        "new_object_name",
        "switch_decision_reasoning",
    ],
    "route_logic": [
        "response_type",
        "natural_topic_completion",
        "suggested_objects",
    ],
    "generate_response": [
        "full_response_text",
    ],
    "generate_question": [
        "full_question_text",
    ],
    "generate_fun_fact": [
        "fun_fact",
        "fun_fact_hook",
        "fun_fact_question",
        "real_facts",
    ],
    "start_guide": [
        "guide_phase",
        "guide_turn_count",
    ],
    "guide_navigator": [
        "guide_status",
        "guide_strategy",
        "scaffold_level",
        "last_navigation_state",
    ],
    "guide_driver": [
        "full_response_text",
    ],
    "guide_success": [
        "guide_phase",
        "guide_status",
    ],
    "guide_hint": [
        "scaffold_level",
    ],
    "guide_exit": [
        "guide_phase",
    ],
    "finalize": [
        "sequence_number",
    ],
}


# ============================================================================
# Context Builder
# ============================================================================

def build_architecture_context(
    suspected_nodes: list[dict],
    response_types: list[str] | None = None,
) -> str:
    """
    Build architecture context string for the Stage 2 LLM.

    Dynamically injects only the prompts relevant to the suspected
    failing nodes, keeping the context focused and within token limits.

    Args:
        suspected_nodes: List of SuspectedNode dicts with node_name and response_types
        response_types: Additional response types to include prompts for

    Returns:
        Formatted architecture context string for the LLM prompt
    """
    sections = []

    # 1. Graph topology
    sections.append(_build_topology_section())

    # 2. Relevant prompts (dynamic)
    sections.append(_build_prompts_section(suspected_nodes, response_types))

    # 3. Per-node state fields for suspected nodes
    sections.append(_build_state_fields_section(suspected_nodes))

    return "\n\n".join(sections)


def _build_topology_section() -> str:
    """Format the graph topology for LLM consumption."""
    lines = ["## Graph Topology\n"]

    lines.append("### Nodes")
    for node in GRAPH_TOPOLOGY["nodes"]:
        lines.append(f"- {node}")

    lines.append("\n### Direct Edges")
    for edge in GRAPH_TOPOLOGY["edges"]:
        lines.append(f"- {edge['from']} → {edge['to']}")

    lines.append("\n### Conditional Routers")
    for router in GRAPH_TOPOLOGY["routers"]:
        lines.append(f"\n**{router['name']}** (from: {router['source']})")
        for condition, target in router["conditions"].items():
            lines.append(f"  - IF {condition} → {target}")

    return "\n".join(lines)


def _build_prompts_section(
    suspected_nodes: list[dict],
    response_types: list[str] | None = None,
) -> str:
    """Inject prompts relevant to suspected failing nodes."""
    lines = ["## Relevant Prompts\n"]

    prompts = paixueji_prompts.get_prompts()

    # Always include system prompt
    lines.append(f"### system_prompt\n```\n{prompts['system_prompt']}\n```\n")

    # Always include followup question prompt
    lines.append(f"### followup_question_prompt\n```\n{prompts['followup_question_prompt']}\n```\n")

    # Collect response types from suspected nodes
    all_response_types = set(response_types or [])
    for node in suspected_nodes:
        for rt in node.get("response_types", []):
            all_response_types.add(rt)

    # Map response types to prompt keys and inject
    injected = set()
    for rt in all_response_types:
        prompt_key = RESPONSE_TYPE_TO_PROMPT.get(rt)
        if prompt_key and prompt_key not in injected:
            prompt_text = prompts.get(prompt_key)
            if prompt_text:
                lines.append(f"### {prompt_key} (used for response_type='{rt}')\n```\n{prompt_text}\n```\n")
                injected.add(prompt_key)

    # Check if any suspected nodes are guide nodes
    for node in suspected_nodes:
        node_name = node.get("node_name", "")
        if node_name in GUIDE_NODE_PROMPTS:
            lines.append(
                f"### {node_name} prompt\n"
                f"Note: {GUIDE_NODE_PROMPTS[node_name]}\n"
                f"(Guide prompts are inline in the code and cannot be monkey-patched via paixueji_prompts.)\n"
            )

    if not injected and not any(n.get("node_name", "") in GUIDE_NODE_PROMPTS for n in suspected_nodes):
        lines.append("(No specific prompts identified for suspected nodes.)\n")

    return "\n".join(lines)


def _build_state_fields_section(suspected_nodes: list[dict]) -> str:
    """Include state fields for suspected nodes."""
    lines = ["## Per-Node State Fields\n"]

    included = set()
    for node in suspected_nodes:
        node_name = node.get("node_name", "")
        if node_name in NODE_STATE_FIELDS and node_name not in included:
            fields = NODE_STATE_FIELDS[node_name]
            lines.append(f"### {node_name}")
            for field in fields:
                lines.append(f"  - {field}")
            lines.append("")
            included.add(node_name)

    if not included:
        lines.append("(No state field mappings for suspected nodes.)\n")

    return "\n".join(lines)
