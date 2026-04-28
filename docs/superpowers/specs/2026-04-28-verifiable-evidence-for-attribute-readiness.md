# Verifiable Evidence for Attribute Activity Readiness

## Problem

The attribute activity pipeline blindly trusts the LLM's `[ACTIVITY_READY]` marker. In the "orange cat" incident, the child said "it is fat" and "stripes are darker" — never engaging with `body_color` — yet the LLM emitted `[ACTIVITY_READY]` with a fabricated reason. There was no mechanism to verify the LLM's claim against the actual conversation transcript.

## Goal

Keep the LLM as the judge of readiness, but require it to provide **verifiable evidence** (direct quotes from the child's messages). Code validates those quotes against the transcript before accepting the marker.

## Design

### 1. Prompt Change: Evidence Requirement

**File:** `paixueji_prompts.py` — `ATTRIBUTE_SOFT_GUIDE`

Insert an `EVIDENCE REQUIREMENT` section before the `TRANSITION SIGNAL` section:

```
EVIDENCE REQUIREMENT: Your REASON: line MUST include at least one direct
quote from the child's actual messages in this conversation, enclosed in
double quotes ("). The quote must be something the child literally said —
do not paraphrase or invent quotes.

GOOD:
  REASON: Child described the orange color directly ("it looks orange")
  and said it reminds them of the sun.

BAD (no quote — will be rejected):
  REASON: Child explored the color.

BAD (fabricated quote — will be rejected):
  REASON: Child said "it is bright orange". (The child never said this.)
```

### 2. Code Change: Quote Extraction and Validation

**File:** `paixueji_app.py` — inside `stream_attribute_activity()` (~lines 1394-1402)

After extracting `activity_marker_reason`, add a validation step:

1. **Extract quoted substrings** from `activity_marker_reason` using regex `r'"([^"]+)"'`.
2. **Build child utterance corpus** from `assistant.conversation_history`: collect all messages where `role == "user"`.
3. **Validate each quote**: check if the quote appears as a case-insensitive substring in any child message.
4. **Gate the marker**:
   - If **no quotes found** in the reason → reject. Log: `"[ACTIVITY_READY] rejected: no evidence quotes in reason"`
   - If **quotes found but none match** any child message → reject. Log: `"[ACTIVITY_READY] rejected: evidence quotes not found in transcript — <quotes>"`
   - If **at least one quote matches** → accept as before.

When rejected, `activity_marker_detected` remains `True` in debug (the marker was present in LLM output), but `activity_ready` stays `False`.

### 3. Debug Payload Extension

Add `activity_marker_rejected_reason` to `build_attribute_debug()` in `attribute_activity.py`:

- Set to `None` when marker is accepted or not present.
- Set to `"no_evidence_quotes"` when no `"..."` found in reason.
- Set to `"evidence_not_in_transcript"` when quotes don't match child messages.

### 4. Test Coverage

**File:** `tests/test_attribute_activity_api.py`

Add two tests:

1. `test_activity_marker_rejected_without_evidence_quote`
   - Mock LLM emits `[ACTIVITY_READY]` with reason `"Child explored the color."` (no quotes).
   - Assert `activity_ready` is `False`, `activity_marker_detected` is `True`, `activity_marker_rejected_reason` is `"no_evidence_quotes"`.

2. `test_activity_marker_rejected_with_fabricated_quote`
   - Mock LLM emits `[ACTIVITY_READY]` with reason `"Child said 'it is orange'."`.
   - Child actually said `"it is fat"`.
   - Assert `activity_ready` is `False`, `activity_marker_detected` is `True`, `activity_marker_rejected_reason` is `"evidence_not_in_transcript"`.

Update prompt invariant test in `tests/test_attribute_discovery_pipeline.py`:

- `test_soft_guide_requests_reason_line`: assert `"evidence requirement"` is present in `ATTRIBUTE_SOFT_GUIDE.lower()`.

## Trade-offs

| Approach | Pros | Cons |
|----------|------|------|
| This design (verifiable quotes) | LLM stays judge; evidence is auditable; blocks hallucinated readiness | Slightly more complex REASON parsing; LLM might omit quotes initially |
| Turn-count threshold (rejected) | Simple; deterministic | Arbitrary; ignores genuine early readiness; not what user wanted |
| Prompt-only strengthening | No code changes | LLM can still ignore the prompt; no guarantee |

## Edge Cases

1. **Partial quote match**: A quote `"orange"` should match child message `"it is orange"` (substring match, case-insensitive).
2. **Multiple quotes**: If one quote matches and another doesn't, still accept (generous validation).
3. **Quote in child's message but about different topic**: Code only checks presence, not semantics. This is acceptable because the LLM is still the semantic judge — we're just preventing completely fabricated evidence.
4. **Punctuation differences**: `"it is orange!"` in reason vs `"it is orange"` in transcript — substring match handles this naturally.

## Files Modified

- `paixueji_prompts.py` — add Evidence Requirement to `ATTRIBUTE_SOFT_GUIDE`
- `paixueji_app.py` — add quote extraction and validation logic
- `attribute_activity.py` — add `activity_marker_rejected_reason` to `build_attribute_debug`
- `tests/test_attribute_activity_api.py` — add rejection tests
- `tests/test_attribute_discovery_pipeline.py` — update prompt invariant test
