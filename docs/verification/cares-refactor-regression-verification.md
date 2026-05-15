# IRL Verification Report
**Generated:** 2026-05-15T11:41:43.417735
**Model:** Gemini via Vertex AI (live calls)
**Method:** Each section shows the actual model output when the corresponding feature is triggered with a realistic input.
---
## Task 1: HANDOFF MODE ACTIVE — Activity Bridge (score=68)
**What was implemented:** Refactored: dedicated _build_handoff_guide() with [BRIDGE TO ACTIVITY] block, no competing angle instructions.
**Test scenario:** Object: apple | Attribute: color | Age: 5 | Turn 5, interest_score=68, should handoff to Color Matching Game
**Prompt excerpt:**
```
...
```
### Model Output:
```

```
### Verification:
- [ ] Contains [ACTIVITY_READY]
- [ ] Mentions activity name (Color Matching or similar)
- [ ] Ends with [ACTIVITY_READY]
- [x] No touch invitation
- [x] Does NOT ask why/how/causal question as main content
- [ ] Natural bridge language present

---
## Task 2: EXIT MODE — No Activity Push (8 turns, score=35)
**What was implemented:** Refactored: dedicated _build_exit_guide() with [WRAP-UP] block, no competing angle instructions.
**Test scenario:** Object: apple | Attribute: color | Age: 5 | 8 total turns, best score=35, should exit without pushing
**Prompt excerpt:**
```
...
```
### Model Output:
```

```
### Verification:
- [x] Does NOT contain [ACTIVITY_READY]
- [x] Does NOT mention activity or game
- [x] Does NOT mention game
- [ ] Suggests free exploration or asks what next
- [x] No touch invitation
- [x] Does NOT ask why/how/causal question
- [ ] Warm wrap-up tone

---
# Summary of Findings
## ✅ What Works Well

## ⚠️ Issues Discovered
- **HANDOFF MODE ACTIVE — Activity Bridge (score=68)**
  - Failed checks: Contains [ACTIVITY_READY], Mentions activity name (Color Matching or similar), Ends with [ACTIVITY_READY], Natural bridge language present
  - Impact: See report for model output and specific failures
- **EXIT MODE — No Activity Push (8 turns, score=35)**
  - Failed checks: Suggests free exploration or asks what next, Warm wrap-up tone
  - Impact: See report for model output and specific failures

---
