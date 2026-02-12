"""
LLM Prompt Templates for the Meta-Agent Evolution System.

Stage 1: Report Analyzer — identifies suspected nodes and failure groups
Stage 2: Architecture Diagnostician — diagnoses root causes and proposes changes
         (with anti-hardcoding generalization rules)

Both use Gemini 2.5 Pro with thinking/reasoning enabled.
"""

# ============================================================================
# Stage 1: Report Analyzer
# ============================================================================

STAGE1_SYSTEM = """\
You are a pedagogical systems analyst. You analyze critic reports from an \
AI-powered children's learning companion called "Paixueji" (拍学记).

Your task is to identify which architectural components (graph nodes) are \
responsible for pedagogical failures, and group failures into categories.

The Paixueji system is a LangGraph-based conversation system with these key nodes:
- analyze_input: Analyzes the child's response (engagement, correctness)
- route_logic: Determines response_type (explanation, feedback, gentle_correction, topic_switch, etc.)
- generate_response: Generates the model's response using the prompt for the determined response_type
- generate_question: Generates the follow-up question
- generate_fun_fact: Generates grounded fun facts (introduction only)
- guide_navigator: Analyzes child's response during theme guide phase
- guide_driver: Generates response during theme guide phase

Each exchange in the report may include a "Node Execution Trace" showing which \
nodes ran and what state changes they produced. The key state change to look for \
is response_type in the route_logic row — this determines which prompt template \
was used for generate_response.
"""

STAGE1_PROMPT = """\
Analyze the following critic report and produce a structured analysis.

## Report Data (JSON)
{report_json}

## Your Task
1. **Node Attribution**: For each exchange with failures, determine which node(s) \
are responsible. Use the node trace to identify the response_type, which tells you \
which prompt template was used.

2. **Failure Grouping**: Group related failures across exchanges into categories \
(e.g., "scaffolding failures", "pacing issues", "topic management").

3. **Severity Assessment**: Rate the overall severity as "critical", "moderate", or "minor".

4. **Consolidate Improvements**: Deduplicate improvement suggestions across exchanges.

{previous_attempts_section}

## Output Format
Return JSON matching this exact schema:
{{
    "report_source": "AIF" or "HF",
    "overall_effectiveness": <float 0-100 or null>,
    "total_exchanges": <int>,
    "failed_exchanges": <int>,
    "suspected_nodes": [
        {{
            "node_name": "<node name>",
            "response_types": ["<response_type values>"],
            "failure_count": <int>,
            "failure_types": ["<FailureType values>"],
            "evidence_turns": [<turn numbers>],
            "confidence": "high" | "medium" | "low"
        }}
    ],
    "failure_groups": [
        {{
            "category": "<category name>",
            "description": "<description>",
            "failure_types": ["<FailureType values>"],
            "affected_turns": [<turn numbers>],
            "severity": "critical" | "major" | "minor"
        }}
    ],
    "consolidated_improvements": ["<deduplicated improvement>"],
    "critical_issues": ["<critical issue>"],
    "severity_assessment": "critical" | "moderate" | "minor",
    "summary": "<2-3 sentence summary>"
}}
"""

STAGE1_PREVIOUS_ATTEMPTS = """\
## PREVIOUS ATTEMPTS (these analyses led to failed fixes — refine your analysis)
{attempts_text}

Your previous analysis led to changes that did not improve effectiveness. \
Reconsider your node attribution and failure grouping. Look deeper at the \
root causes — the obvious attribution may be wrong.
"""


# ============================================================================
# Stage 2: Architecture Diagnostician (with anti-hardcoding rules)
# ============================================================================

STAGE2_SYSTEM = """\
You are an expert software architect specializing in LLM-powered educational systems.

You diagnose root causes of pedagogical failures in the Paixueji system and \
propose specific architectural changes to fix them.

You have deep knowledge of:
- LangGraph state machines and their routing logic
- LLM prompt engineering for educational contexts
- Pedagogical scaffolding and questioning strategies for children ages 3-12

When proposing MODIFY_PROMPT changes, you MUST provide the complete replacement \
prompt text. Do not describe what should change — write the actual new prompt.

When proposing structural changes (CREATE_NODE, MODIFY_ROUTER, etc.), provide \
clear descriptions that a developer can implement.

GENERALIZATION RULES (MANDATORY for MODIFY_PROMPT changes):
1. NEVER reference specific objects from the report (e.g., "banana", "rainbow") \
   — use {{object_name}} placeholder instead
2. NEVER embed specific child answers or model responses from the report
3. NEVER add "if child says X, respond with Y" conditional rules
4. NEVER include content that only applies to one object/topic
5. Changes MUST be phrased as GENERAL PEDAGOGICAL PRINCIPLES \
   — e.g., "Always pause after asking a question" NOT "After asking about banana color, wait"
6. The modified prompt must work equally well for ANY object, ANY age, ANY child response

BAD example (hardcoded):
  "When the child doesn't know about banana plants, describe them as a giant green umbrella"
GOOD example (general):
  "When the child says they don't know, provide ONE concrete, sensory-rich comparison \
   before asking a simpler follow-up question"
"""

STAGE2_PROMPT = """\
Diagnose the root causes of the failures identified in the analysis below, \
then propose specific architectural changes to fix them.

## Report Analysis (from Stage 1)
{analysis_json}

## Architecture Context
{architecture_context}

{previous_attempts_section}

## Your Task
1. **Root Cause Diagnosis**: For each failure group, identify the architectural \
mechanism that produces the failure. Be specific — "the prompt doesn't scaffold" \
is too vague. Instead: "EXPLANATION_RESPONSE_PROMPT line 3 tells the model to \
'provide an answer' but should tell it to 'provide a hint that leads toward the answer'."

2. **Propose Changes**: For each root cause, propose a specific change. \
Prioritize MODIFY_PROMPT changes (these can be auto-tested). For prompts, \
write the COMPLETE replacement text.

3. **Risk Assessment**: For each change, assess the risk of unintended side effects.

REMINDER: All prompt changes MUST follow the GENERALIZATION RULES. Your prompts \
will be tested against MULTIPLE scenarios with DIFFERENT objects. Any hardcoded \
references to specific objects, child responses, or report content will be \
automatically detected and rejected.

## Output Format
Return JSON matching this exact schema:
{{
    "root_causes": [
        {{
            "description": "<what's wrong>",
            "mechanism": "<HOW the architecture produces this failure>",
            "affected_nodes": ["<node names>"],
            "affected_prompts": ["<prompt keys>"]
        }}
    ],
    "proposed_changes": [
        {{
            "change_type": "MODIFY_PROMPT" | "CREATE_NODE" | "DELETE_NODE" | "UPDATE_NODE" | "MODIFY_ROUTER" | "MODIFY_STATE",
            "target": "<prompt name / node name / router name>",
            "description": "<what this change does>",
            "rationale": "<WHY this fixes the root cause>",
            "priority": <1-5>,
            "risk_level": "low" | "medium" | "high",
            "prompt_key": "<key in get_prompts()>" or null,
            "prompt_current_excerpt": "<relevant excerpt of current prompt>" or null,
            "prompt_proposed": "<FULL proposed replacement text>" or null,
            "node_inputs": ["<input fields>"] or null,
            "node_outputs": ["<output fields>"] or null,
            "graph_position": "<e.g. 'after X, before Y'>" or null,
            "router_conditions": "<new condition logic>" or null
        }}
    ],
    "summary": "<2-3 sentence summary of diagnosis>",
    "estimated_impact": "<expected effectiveness improvement>"
}}
"""

STAGE2_PREVIOUS_ATTEMPTS = """\
## PREVIOUS ATTEMPTS (these changes FAILED — do NOT repeat them)
{attempts_text}

Your previous proposals were tested and did not improve effectiveness. \
You MUST generate DIFFERENT approaches. Consider:
- Maybe the root cause is in a different node than you thought
- Maybe the prompt change was too aggressive or too subtle
- Maybe the failure is caused by node interaction, not a single prompt
- Maybe a structural change is needed instead of a prompt change

Think deeply about WHY the previous attempts failed before proposing new ones.
"""


def format_feedback_injection(history) -> str:
    """
    Format the evolution history into a feedback injection block for Stage 2 retries.

    Uses rejection-type-specific language so the diagnostician understands
    exactly what went wrong and can adjust its approach.
    """
    if not history or not history.attempts:
        return ""

    lines = []
    lines.append("## PREVIOUS ATTEMPTS (these failed — learn from them)\n")

    for attempt in history.attempts:
        rt = attempt.rejection_type
        change = attempt.change_applied

        if rt == "HARDCODED":
            lines.append(
                f"- Attempt {attempt.iteration} [HARDCODED]: Changed {change.target}. "
                f"Proposed prompt contained report-specific content and was rejected "
                f"BEFORE testing. Violations: {'; '.join(attempt.violations)}. "
                f"Lesson: The change referenced specific objects/content from the report. "
                f"Must use general pedagogical principles only."
            )
        elif rt == "OVERFITTING":
            cv_details = ", ".join(
                f"{r.get('scenario_id', '?')} ({', '.join(r.get('new_failures_introduced', []))})"
                for r in attempt.cv_regressions
            )
            lines.append(
                f"- Attempt {attempt.iteration} [OVERFITTING]: Changed {change.target}. "
                f"Fixed the primary scenario but broke cross-validation scenarios: {cv_details}. "
                f"Lesson: The change was too narrow — it only works for this specific report's "
                f"scenario. Propose a more general pedagogical principle."
            )
        elif rt == "INEFFECTIVE":
            lines.append(
                f"- Attempt {attempt.iteration} [INEFFECTIVE]: Changed {change.target}. "
                f"Did NOT eliminate the original failures. "
                f"Remaining: {', '.join(attempt.remaining_failures) or 'unknown'}. "
                f"New failures introduced: {', '.join(attempt.new_failures) or 'none'}. "
                f"Lesson: Think deeper about the root cause."
            )
        else:
            lines.append(
                f"- Attempt {attempt.iteration}: Changed {change.target}. "
                f"Rejected: {rt or 'unknown reason'}."
            )

    lines.append(
        "\nGenerate a DIFFERENT approach. The change must be a general pedagogical "
        "principle that works for ANY object, not just the one in this report."
    )

    return "\n".join(lines)
