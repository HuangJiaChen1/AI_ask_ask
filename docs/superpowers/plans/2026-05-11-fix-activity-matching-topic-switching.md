# Fix Activity Matching Topic Switching + Premature Handoff

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two IRL-verified issues in the activity matching pipeline: (1) model ignores child's interest shift to fallback topics, and (2) `[ACTIVITY_READY]` is emitted after only one shallow exchange.

**Architecture:** Convert `FOLLOWUP_QUESTION_PROMPT` from hard-coded "stay on same attribute" instructions to an injectable template with `{focus_topic}`. This eliminates prompt-level instruction conflict where strong early instructions override weak later switching rules. Add a minimum-turn guard (`turn_count >= 3`) before accepting `[ACTIVITY_READY]`. Inject the multi-topic guide into the response generator so `[SWITCH_TO]` decisions happen in the response step, with follow-up questions using the updated topic.

**Tech Stack:** Python 3.11, Flask, Gemini via Vertex AI, LangGraph, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `paixueji_prompts.py` | Prompt templates. `FOLLOWUP_QUESTION_PROMPT` gets `{focus_topic}` parameter. `ATTRIBUTE_MULTI_TOPIC_GUIDE` gets stronger switching language. |
| `stream/question_generators.py` | `ask_followup_question_stream` gets `focus_topic` parameter and passes it to prompt format. |
| `stream/response_generators.py` | `generate_attribute_activation_response_stream` gets `multi_topic_guide` parameter and appends it to prompt. |
| `paixueji_app.py` | `stream_attribute_activity` reorders soft_guide construction, passes `focus_topic` and `multi_topic_guide`, adds `turn_count` guard and `[SWITCH_TO]` detection after follow-up. |
| `graph.py` | 5 call sites for `ask_followup_question_stream` updated with `focus_topic="the same interesting detail"`. |
| `tests/test_attribute_switching.py` | New test: verify `focus_topic` propagation through `ask_followup_question_stream`. |
| `tests/test_attribute_discovery_pipeline.py` | Update mock calls to include `focus_topic`. |
| `scripts/irl_verify.py` | Update `ask_followup_question_stream` call params in scenario config. |

---

## Task 1: Make FOLLOWUP_QUESTION_PROMPT Injectable with `{focus_topic}`

**Files:**
- Modify: `paixueji_prompts.py:168-260`

**What and why:** The prompt currently hard-codes "same attribute" / "same detail or same attribute" at lines 182 and 251. This creates an instruction conflict with `ATTRIBUTE_MULTI_TOPIC_GUIDE` which is appended later. By parameterizing the focus topic, the prompt no longer contains conflicting instructions — the caller decides what the current focus is.

- [ ] **Step 1: Replace hard-coded "same attribute" references with `{focus_topic}`**

  In `paixueji_prompts.py`, make these three edits:

  ```python
  # Line ~182 — change from:
  "- Stay on the same detail, same attribute, or one-hop nearby idea from the last message"
  # To:
  "- Stay on the {focus_topic}, or one-hop nearby idea from the last message"
  ```

  ```python
  # Line ~251 — change from:
  "- Keep it to the same detail or same attribute from the last message whenever possible."
  # To:
  "- Keep it to the {focus_topic} from the last message whenever possible."
  ```

  ```python
  # Line ~169 — add focus_topic to the format string signature comment
  # (No code change needed — the .format() call already handles unknown keys gracefully
  # by leaving them as-is, but we'll pass it explicitly in Task 2)
  ```

- [ ] **Step 2: Verify the prompt still formats correctly**

  Run a quick sanity check:

  ```bash
  python -c "
  import paixueji_prompts
  prompts = paixueji_prompts.get_prompts()
  result = prompts['followup_question_prompt'].format(
      object_name='cat', age=5, age_prompt='Age 5 prompt',
      knowledge_context='kb', sensory_safety_rules='safety',
      focus_topic=\"the 'shape' attribute\"
  )
  assert \"the 'shape' attribute\" in result
  assert 'same attribute' not in result
  print('OK: focus_topic injects correctly')
  "
  ```

  Expected: `OK: focus_topic injects correctly`

---

## Task 2: Strengthen Topic Switching Language in ATTRIBUTE_MULTI_TOPIC_GUIDE

**Files:**
- Modify: `paixueji_prompts.py:560-604`

**What and why:** The current guide says "you may switch" (line 571) which is too weak. The model obeys the stronger earlier "stay on same attribute" instruction. We need stronger language and concrete examples of what counts as "clearly shifted interest".

- [ ] **Step 1: Strengthen the switching rule and add concrete examples**

  In `paixueji_prompts.py`, replace lines 569-575 (the TOPIC SWITCHING RULES section) with:

  ```python
  TOPIC SWITCHING RULES:
  - Your MAIN job is to guide the child toward {primary_attribute_label}.
  - BUT if the child clearly shows more interest in a fallback topic, you SHOULD switch.
  - "Clearly shows more interest" means ONE of these:
    * The child used 3+ words describing the fallback topic (e.g. "SO BIG! Bigger than my dog!")
    * The child compared the object to something else using the fallback topic
    * The child asked a direct question about the fallback topic
    * The child returned to the fallback topic in 2+ consecutive messages
  - To switch: at the END of your response, add [SWITCH_TO:attribute_id].
  - ONLY switch if the child has clearly shifted interest (criteria above).
  - After switching, your new primary direction becomes that fallback topic.
  - If the child mentions something outside all topics, briefly acknowledge in ONE sentence, then redirect back.
  ```

- [ ] **Step 2: Verify the prompt contains the stronger language**

  ```bash
  python -c "
  import paixueji_prompts
  prompts = paixueji_prompts.get_prompts()
  guide = prompts['attribute_multi_topic_guide']
  assert 'you SHOULD switch' in guide
  assert '3+ words describing the fallback topic' in guide
  print('OK: strengthened switching language')
  "
  ```

  Expected: `OK: strengthened switching language`

---

## Task 3: Add `focus_topic` Parameter to `ask_followup_question_stream`

**Files:**
- Modify: `stream/question_generators.py:197-234`

**What and why:** The generator needs to accept `focus_topic` and pass it to the prompt's `.format()` call. Default value preserves backward compatibility for non-attribute callers.

- [ ] **Step 1: Add parameter and pass to prompt format**

  In `stream/question_generators.py`, modify the function signature (line 197-210):

  ```python
  async def ask_followup_question_stream(
      messages: list[dict],
      object_name: str,
      age_prompt: str,
      age: int,
      config: dict,
      client: genai.Client,
      knowledge_context: str = "",
      resolution_guardrails: str = "",
      surface_only_mode: bool = False,
      surface_object_name: str = "",
      attribute_soft_guide: str = "",
      response_text: str = "",
      focus_topic: str = "same attribute or same detail",  # <-- ADD THIS
  ) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
  ```

  Then modify the prompt format call (around line 228-234):

  ```python
      prompts = paixueji_prompts.get_prompts()
      followup_prompt = prompts['followup_question_prompt'].format(
          object_name=object_name,
          age=age,
          age_prompt=age_prompt,
          knowledge_context=knowledge_context,
          sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
          focus_topic=focus_topic,  # <-- ADD THIS
      )
  ```

- [ ] **Step 2: Verify parameter flows through**

  ```bash
  python -c "
  import inspect
  from stream.question_generators import ask_followup_question_stream
  sig = inspect.signature(ask_followup_question_stream)
  assert 'focus_topic' in sig.parameters
  assert sig.parameters['focus_topic'].default == 'same attribute or same detail'
  print('OK: focus_topic parameter added')
  "
  ```

  Expected: `OK: focus_topic parameter added`

---

## Task 4: Add `multi_topic_guide` Parameter to Response Generator

**Files:**
- Modify: `stream/response_generators.py:249-298`

**What and why:** The response generator currently only appends `attribute_response_hint`. We need it to also accept and append the full multi-topic guide so `[SWITCH_TO]` can be emitted in the response step.

- [ ] **Step 1: Add parameter and append logic**

  In `stream/response_generators.py`, modify the signature (line 249-265):

  ```python
  async def generate_attribute_activation_response_stream(
      *,
      messages: list[dict],
      intent_type: str,
      object_name: str,
      attribute_label: str,
      activity_target: str,
      child_answer: str,
      reply_type: str,
      state_action: str,
      age: int,
      age_prompt: str,
      knowledge_context: str = "",
      last_model_response: str = "",
      config: dict,
      client: genai.Client,
      multi_topic_guide: str = "",  # <-- ADD THIS
  ) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
  ```

  Then after line 298 (after `full_prompt = f"{intent_prompt}\n\n{response_hint}"`), add:

  ```python
      # Append multi-topic guide if provided (enables SWITCH_TO in response step)
      if multi_topic_guide:
          full_prompt = f"{full_prompt}\n\n{multi_topic_guide}"
  ```

- [ ] **Step 2: Verify parameter flows through**

  ```bash
  python -c "
  import inspect
  from stream.response_generators import generate_attribute_activation_response_stream
  sig = inspect.signature(generate_attribute_activation_response_stream)
  assert 'multi_topic_guide' in sig.parameters
  print('OK: multi_topic_guide parameter added')
  "
  ```

  Expected: `OK: multi_topic_guide parameter added`

---

## Task 5: Update `stream_attribute_activity` in `paixueji_app.py`

**Files:**
- Modify: `paixueji_app.py:1293-1589`

**What and why:** This is the core orchestration change. We need to:
1. Move `soft_guide` construction BEFORE the response generator call
2. Pass `multi_topic_guide=soft_guide` to the response generator
3. Pass `focus_topic` to the follow-up question generator
4. Add `turn_count >= 3` guard before accepting `[ACTIVITY_READY]`
5. Add `[SWITCH_TO]` detection after follow-up question generation

- [ ] **Step 1: Move soft_guide construction before response generator**

  In `paixueji_app.py`, inside `stream_attribute_activity()`, find the current code around line 1324-1407. Move the `soft_guide` construction (currently at lines 1397-1407) to BEFORE the `response_generator = generate_attribute_activation_response_stream(...)` call (currently at line 1324).

  The new order should be:

  ```python
  async def stream_attribute_activity():
      needs_followup = intent_type_lower not in INTENTS_WITHOUT_FOLLOWUP

      messages = prepare_messages_for_streaming(
          assistant.conversation_history.copy(),
          age_prompt,
      )
      attribute_label = assistant.attribute_state.profile.label
      activity_target = assistant.attribute_state.profile.activity_target
      object_name_attr = assistant.attribute_state.object_name

      # Build soft_guide BEFORE response generator so response can use it
      fallback_block = ""
      if assistant.attribute_state.profile.fallback_attributes:
          lines = [f"- {fb.attribute_id}: {fb.label}" for fb in assistant.attribute_state.profile.fallback_attributes]
          fallback_block = "\n".join(lines)

      soft_guide = paixueji_prompts.get_prompts()["attribute_multi_topic_guide"].format(
          primary_attribute_label=attribute_label,
          primary_activity_target=activity_target,
          fallback_attribute_block=fallback_block or "(no fallback topics)",
          sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
      )

      response_generator = generate_attribute_activation_response_stream(
          messages=messages,
          intent_type=intent_type_lower,
          object_name=object_name_attr,
          attribute_label=attribute_label,
          activity_target=activity_target,
          child_answer=child_input,
          reply_type="discovery",
          state_action="continue_conversation",
          age=assistant.age or 6,
          age_prompt=age_prompt,
          knowledge_context="",
          last_model_response=extract_previous_response(assistant.conversation_history),
          config=assistant.config,
          client=assistant.client,
          multi_topic_guide=soft_guide,  # <-- ADD THIS
      )
  ```

  And remove the duplicate `fallback_block` and `soft_guide` construction that was at lines 1397-1407.

- [ ] **Step 2: Add `[SWITCH_TO]` detection after response streaming**

  Keep the existing `[SWITCH_TO]` detection after response streaming (lines 1374-1395). It should still work because `detect_switch_marker()` searches the response text for the marker.

- [ ] **Step 3: Pass `focus_topic` to follow-up question generator**

  Find the `ask_followup_question_stream` call (around line 1414-1423) and add `focus_topic`:

  ```python
      followup_generator = ask_followup_question_stream(
          messages=messages_with_response,
          object_name=object_name_attr,
          age_prompt=age_prompt,
          age=assistant.age or 6,
          config=assistant.config,
          client=assistant.client,
          attribute_soft_guide=soft_guide,
          response_text="",
          focus_topic=f"the '{attribute_label}' attribute",  # <-- ADD THIS
      )
  ```

- [ ] **Step 4: Add `turn_count` guard before accepting `[ACTIVITY_READY]`**

  Find the validation block around line 1467-1495. Add a minimum turn check BEFORE the quote validation:

  ```python
      MIN_ACTIVITY_READY_TURNS = 3
      activity_marker_rejected_reason = None

      if activity_marker_detected:
          # Guard: require minimum conversation depth before accepting handoff
          if assistant.attribute_state.turn_count < MIN_ACTIVITY_READY_TURNS:
              activity_marker_rejected_reason = "insufficient_turns"
              logger.info(
                  "[ACTIVITY_READY] rejected: turn_count=%d < MIN_TURNS=%d",
                  assistant.attribute_state.turn_count, MIN_ACTIVITY_READY_TURNS,
              )
          elif activity_marker_reason:
              # Existing quote validation
              quotes = re.findall(r'"([^"]+)"', activity_marker_reason)
              if not quotes:
                  activity_marker_rejected_reason = "no_evidence_quotes"
                  logger.info("[ACTIVITY_READY] rejected: no evidence quotes in reason")
              else:
                  child_messages = [
                      msg["content"] for msg in assistant.conversation_history
                      if msg.get("role") == "user"
                  ]
                  child_messages.append(child_input)
                  found_match = False
                  for quote in quotes:
                      quote_lower = quote.lower()
                      for child_msg in child_messages:
                          if quote_lower in child_msg.lower():
                              found_match = True
                              break
                      if found_match:
                          break
                  if not found_match:
                      activity_marker_rejected_reason = "evidence_not_in_transcript"
                      logger.info(
                          "[ACTIVITY_READY] rejected: evidence quotes not found in transcript — %s",
                          quotes,
                      )
  ```

- [ ] **Step 5: Add `[SWITCH_TO]` detection after follow-up question generation**

  After the follow-up question has been fully collected (after the `async for _text_chunk...` loop that ends around line 1458), add:

  ```python
      # Safety net: detect [SWITCH_TO] in follow-up question output
      followup_switch_target, cleaned_followup = detect_switch_marker(full_followup)
      if followup_switch_target:
          switch_success = assistant.switch_attribute_topic(
              target_attribute_id=followup_switch_target,
              reason="model_detected_switch_marker_in_followup",
          )
          if switch_success:
              full_followup = cleaned_followup
              attribute_label = assistant.attribute_state.profile.label
              activity_target = assistant.attribute_state.profile.activity_target
              logger.info(
                  "[ATTRIBUTE_SWITCH] followup switched to %s | session=%s",
                  followup_switch_target, session_id[:8],
              )
          else:
              logger.warning(
                  "[ATTRIBUTE_SWITCH] followup rejected: target %s not in fallbacks | session=%s",
                  followup_switch_target, session_id[:8],
              )
              full_followup = cleaned_followup
  ```

  Note: `detect_switch_marker` is already imported at the top of `paixueji_app.py` (it's used at line 1374).

---

## Task 6: Update `graph.py` Call Sites

**Files:**
- Modify: `graph.py:1011, 1149, 1208, 1477, 1532`

**What and why:** All 5 call sites for `ask_followup_question_stream` in `graph.py` need to pass `focus_topic="the same interesting detail"` to maintain current behavior (these are non-attribute-lane calls where we want the default "stay on topic" behavior).

- [ ] **Step 1: Update all 5 call sites**

  For each of these calls, add `focus_topic="the same interesting detail"`:

  Line ~1011 (node_give_answer_idk):
  ```python
  followup_gen = ask_followup_question_stream(
      messages=messages_with_response,
      object_name=state["object_name"],
      age_prompt=state["age_prompt"],
      age=state["age"],
      config=state["config"],
      client=state["client"],
      knowledge_context=_build_chat_kb_context(state),
      resolution_guardrails=_resolution_guardrails_for_state(state),
      focus_topic="the same interesting detail",  # <-- ADD THIS
  )
  ```

  Line ~1149 (node_correct_answer):
  ```python
  followup_gen = ask_followup_question_stream(
      messages=messages_with_response,
      object_name=state["object_name"],
      age_prompt=state["age_prompt"],
      age=state["age"],
      config=state["config"],
      client=state["client"],
      knowledge_context=_build_chat_kb_context(state),
      resolution_guardrails=_resolution_guardrails_for_state(state),
      surface_only_mode=_surface_only_mode_for_state(state),
      surface_object_name=_surface_object_name_for_state(state),
      focus_topic="the same interesting detail",  # <-- ADD THIS
  )
  ```

  Line ~1208 (node_informative):
  ```python
  followup_gen = ask_followup_question_stream(
      messages=messages_with_response,
      object_name=state["object_name"],
      age_prompt=state["age_prompt"],
      age=state["age"],
      config=state["config"],
      client=state["client"],
      knowledge_context=_build_chat_kb_context(state),
      resolution_guardrails=_resolution_guardrails_for_state(state),
      focus_topic="the same interesting detail",  # <-- ADD THIS
  )
  ```

  Line ~1477 (node_social):
  ```python
  followup_gen = ask_followup_question_stream(
      messages=messages_with_response,
      object_name=state["object_name"],
      age_prompt=state["age_prompt"],
      age=state["age"],
      config=state["config"],
      client=state["client"],
      knowledge_context=_build_chat_kb_context(state),
      resolution_guardrails=_resolution_guardrails_for_state(state),
      focus_topic="the same interesting detail",  # <-- ADD THIS
  )
  ```

  Line ~1532 (node_social_acknowledgment):
  ```python
  followup_gen = ask_followup_question_stream(
      messages=messages_with_response,
      object_name=state["object_name"],
      age_prompt=state["age_prompt"],
      age=state["age"],
      config=state["config"],
      client=state["client"],
      knowledge_context=_build_chat_kb_context(state),
      resolution_guardrails=_resolution_guardrails_for_state(state),
      focus_topic="the same interesting detail",  # <-- ADD THIS
  )
  ```

---

## Task 7: Update Tests

**Files:**
- Modify: `tests/test_attribute_switching.py`
- Modify: `tests/test_attribute_discovery_pipeline.py`

- [ ] **Step 1: Add `focus_topic` propagation test**

  Append to `tests/test_attribute_switching.py`:

  ```python
  def test_focus_topic_parameter_exists():
      """Verify ask_followup_question_stream accepts focus_topic parameter."""
      import inspect
      from stream.question_generators import ask_followup_question_stream
      sig = inspect.signature(ask_followup_question_stream)
      assert "focus_topic" in sig.parameters
      assert sig.parameters["focus_topic"].default == "same attribute or same detail"


  def test_multi_topic_guide_parameter_exists():
      """Verify generate_attribute_activation_response_stream accepts multi_topic_guide."""
      import inspect
      from stream.response_generators import generate_attribute_activation_response_stream
      sig = inspect.signature(generate_attribute_activation_response_stream)
      assert "multi_topic_guide" in sig.parameters
      assert sig.parameters["multi_topic_guide"].default == ""
  ```

- [ ] **Step 2: Update test discovery pipeline mocks**

  In `tests/test_attribute_discovery_pipeline.py`, find any `ask_followup_question_stream` mock calls and add `focus_topic` to the expected call assertions. For example, if there's:

  ```python
  mock_ask_followup.assert_called_once_with(
      messages=...,
      object_name=...,
      # ... other args
  )
  ```

  It may need updating if the test uses `assert_called_once_with` with exact matching. If tests use `assert_called_with` or `call_args`, they may pass without changes due to the default parameter value. Run the tests to check.

- [ ] **Step 3: Run tests**

  ```bash
  pytest tests/test_attribute_switching.py tests/test_attribute_discovery_pipeline.py -v
  ```

  Expected: All tests pass.

---

## Task 8: Update `scripts/irl_verify.py` Scenario Config

**Files:**
- Modify: `scripts/irl_verify_scenarios.json` (or equivalent config used for activity matching)

- [ ] **Step 1: Add focus_topic to follow-up question scenarios**

  Find the scenarios in the JSON config that use `ask_followup_question_stream`. Add `"focus_topic": "the 'shape' attribute"` (or appropriate attribute) to the params.

  For example, if there's a Task 3 or Task 4 scenario:

  ```json
  {
    "id": "task_3_followup_primary",
    "generator": "ask_followup_question_stream",
    "params": {
      "object_name": "orange cat",
      "age": 5,
      "attribute_soft_guide": "...",
      "focus_topic": "the 'shape' attribute"
    }
  }
  ```

  Note: The actual config file path may vary. Check `scripts/irl_verify_scenarios.json` or similar.

---

## Task 9: Run Full Test Suite

- [ ] **Step 1: Run all tests**

  ```bash
  pytest tests/ -v
  ```

  Expected: All tests pass. Any failures related to `focus_topic` or `multi_topic_guide` indicate a missed call site.

- [ ] **Step 2: Run specific attribute tests**

  ```bash
  pytest tests/test_attribute_switching.py tests/test_attribute_discovery_pipeline.py tests/test_attribute_activity_pipeline.py -v
  ```

  Expected: All tests pass.

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Prompt injectable with `{focus_topic}` — Task 1
- [x] Stronger switching language in multi-topic guide — Task 2
- [x] `focus_topic` parameter in question generator — Task 3
- [x] `multi_topic_guide` parameter in response generator — Task 4
- [x] Soft guide moved before response generator — Task 5, Step 1
- [x] `focus_topic` passed to follow-up generator — Task 5, Step 3
- [x] `turn_count >= 3` guard for `[ACTIVITY_READY]` — Task 5, Step 4
- [x] `[SWITCH_TO]` detection after follow-up — Task 5, Step 5
- [x] Graph call sites updated — Task 6
- [x] Tests updated — Task 7

**2. Placeholder scan:**
- [x] No "TBD", "TODO", "implement later"
- [x] All code blocks contain actual code
- [x] No "Similar to Task N" references

**3. Type consistency:**
- [x] `focus_topic: str` used consistently
- [x] `multi_topic_guide: str` used consistently
- [x] Default values match (`"same attribute or same detail"` for focus_topic, `""` for multi_topic_guide)

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-11-fix-activity-matching-topic-switching.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
