# USER_BEHAVIOR_SPEC

## 1. Scope

- Covers:
  - Browser flows served from `/`: setup form, chat, streaming/stop control, manual switch panel, completion modal/launcher, debug-driven manual critique, HF report viewer, and prompt-optimization review UI.
  - Backend routes directly backing those flows: `/api/objects`, `/api/start`, `/api/continue`, `/api/force-switch`, `/api/exchanges/<session_id>`, `/api/manual-critique`, `/api/reports/hf*`, `/api/handoff`, `/tmp/handoff/<filename>`, `/api/optimize-prompt*`.
  - Current behavior evidenced by `static/index.html`, `static/app.js`, `static/reports.js`, `paixueji_app.py`, `paixueji_assistant.py`, and tests including `tests/test_api_flow.py`, `tests/test_frontend_view_state.py`, `tests/test_unknown_object_flow.py`, `tests/test_correct_answer_tracking.py`, `tests/test_hf_report_viewer.py`, and `tests/test_all_endpoints.py`.
- Does not cover:
  - Offline scripts, generator internals, or YAML authoring workflows not surfaced in the shipped browser UI.
  - The destination app after `/api/handoff` redirects to WonderLens; only Paixueji's handoff creation is covered.
  - Deprecated or removed paths such as `/api/start-guide` and `/api/select-object`.
  - Unreleased/TODO behavior documented only in `docs/action-flow-graph/*` without matching live code.

## 2. User Surfaces

| Surface | Evidence |
|---|---|
| Setup / landing page | `static/index.html` contains `#startForm`, age selector, object input, model override radios, and the `Start Learning!` CTA; `window.paixuejiUi.showMainPage()` controls this view in `static/app.js`. |
| Chat transcript and input | `static/index.html` defines `#messages`, `#userInput`, `#sendBtn`, `#stopBtn`; `startConversation()`, `sendMessage()`, `continueConversation()`, and `handleStreamChunk()` in `static/app.js` drive the chat UI. |
| Learning progress + debug panel | `static/index.html` includes `#progressIndicator` and `#debugPanel`; `handleStreamChunk()` toggles `learning_anchor_active`, updates counts/theme/debug metadata, and `tests/test_correct_answer_tracking.py` verifies threshold-driven completion metadata. |
| Manual switch suggestion panel | `static/index.html` includes `#manualSwitchPanel`; `handleStreamChunk()` shows it when `detected_object_name` arrives, `forceSwitch()` calls `/api/force-switch`, and `dismissSwitchPanel()` hides it. |
| Completion modal + mini launcher | `static/index.html` includes `#chatPhaseCompleteModal` and `#activitiesMiniLauncher`; `showChatPhaseCompleteModal()`, `minimizeChatPhaseCompleteModal()`, and `handoff()` in `static/app.js`; covered by `tests/test_frontend_view_state.py` and `tests/test_all_endpoints.py::test_handoff_uses_tmp_handoff_route`. |
| Manual critique overlay | `static/index.html` includes `#manualCritiqueOverlay`; `showManualCritiqueForm()`, `submitManualCritiqueToDatabase()`, and `submitManualCritiqueWithEvolution()` in `static/app.js`; `/api/exchanges/<session_id>` and `/api/manual-critique` in `paixueji_app.py`. |
| HF report viewer | `#reportsBtn`, `#reportViewer`, `#rvCritiquePopup`, and `#rvRawModal` live in `static/index.html`; gallery/detail/raw flows are implemented in `static/reports.js`; covered by `tests/test_hf_report_viewer.py`. |
| Prompt optimization review modal | `#optimizationModal` is present in `static/index.html`; `runOptimization()`, `approveOptimization()`, `submitRejectionAndRetry()`, and `discardOptimization()` in `static/app.js`; `/api/optimize-prompt*` routes in `paixueji_app.py`. |

## 3. User States

| State | Entry Condition | Exit Condition | Evidence |
|---|---|---|---|
| `SETUP_READY` | Initial page load or `resetConversation()` calls `window.paixuejiUi.showMainPage()`. | User opens reports or starts a conversation with a non-empty object. | `init()` and `resetConversation()` in `static/app.js`; `static/index.html#startForm`. |
| `CHAT_SURFACE_IDLE` | Session exists, chat view is shown, streaming is off, and `learning_anchor_active` is false. This includes unresolved topics, surface-topic chat, and pre-anchor/confirmation turns. | User sends a message, opens reports, leaves chat, or the session transitions into anchor learning / completion / error. | `handleStreamChunk()` toggles progress off when `learning_anchor_active` is false; unresolved and surface-only behavior is covered by `tests/test_unknown_object_flow.py`. |
| `CHAT_ANCHOR_IDLE` | Session exists, chat view is shown, streaming is off, and `learning_anchor_active` is true. Progress/debug metadata are visible. | User sends a message, reaches chat-phase completion, opens reports, or falls into an error state. | `handleStreamChunk()` sets `learningAnchorActive`, updates progress, and `tests/test_correct_answer_tracking.py` verifies anchor-gated count behavior. |
| `CHAT_STREAMING` | `startConversation()` or `continueConversation()` sets `isStreaming = true`, creates an `AbortController`, and begins SSE parsing. | Stream completes, user stops/aborts, or an SSE error occurs. | `startConversation()`, `continueConversation()`, `handleSSEEvent()`, `stopStreaming()` in `static/app.js`; `/api/start` and `/api/continue` in `paixueji_app.py`. |
| `MANUAL_SWITCH_SUGGESTED` | A chunk carries `detected_object_name`, causing the manual switch panel to appear. | User forces the switch, dismisses the panel, or resets/leaves the chat. | `handleStreamChunk()` and `dismissSwitchPanel()` in `static/app.js`; `tests/test_unknown_object_flow.py` and docs/checklist scenario 23-25. |
| `CHAT_COMPLETE_LOCKED` | A chunk carries `chat_phase_complete`, setting `conversationComplete = true`, showing the completion modal, and eventually disabling input. | User closes/minimizes the modal, reopens the launcher, or leaves Paixueji via handoff. | `handleStreamChunk()`, `showChatPhaseCompleteModal()`, `disableCompletedChatInput()`, `handoff()` in `static/app.js`; `tests/test_correct_answer_tracking.py` and `tests/test_frontend_view_state.py`. |
| `REPORTS_BROWSING` | `openReportsViewer()` calls `window.paixuejiUi.showReportsPage()` and loads the HF report gallery/detail views. | User closes reports and returns to the stored previous view. | `openReportsViewer()`, `closeReportsViewer()`, `loadReportGallery()`, `loadReportDetail()` in `static/reports.js`; `tests/test_hf_report_viewer.py`. |
| `CRITIQUE_REVIEWING` | Manual critique overlay or optimization modal is open for an active session. | User closes the overlay/modal or submits a flow that closes it. | `showManualCritiqueForm()`, `closeManualCritique()`, `showOptimizationPrompts()`, `closeOptimizationModal()` in `static/app.js`. |
| `REQUEST_ERROR_OR_MISSING_SESSION` | A chat/report/optimization request fails, including HTTP 404 for missing sessions and SSE error payloads such as 429 rate limits. | User retries, restarts, closes the failing surface, or starts a new session. | `continueConversation()` special-cases 404; `renderRetryUI()` handles request/SSE failures; `/api/continue` returns 404 for missing sessions; `tests/test_api_flow.py` validates 404 and 429 SSE behavior. |

## 4. State Transition Map

| Current State | Action | Next State | Guard / Condition | UI Result | Backend Effect | Evidence |
|---|---|---|---|---|---|---|
| `SETUP_READY` | Click `Start Learning!` | `CHAT_STREAMING` | `objectName` is non-empty | Setup view hides, chat view shows, send disabled, stop button becomes available during stream | `POST /api/start`; new session is created and streamed over SSE | `static/app.js:startConversation()`, `paixueji_app.py:/api/start`, `tests/test_api_flow.py::test_start_conversation` |
| `SETUP_READY` | Click `Start Learning!` | `SETUP_READY` | `objectName` is empty | Alert: `Please enter an object name`; no view change | No request is sent | `static/app.js:startConversation()` |
| `CHAT_STREAMING` | Receive first/final start chunk | `CHAT_SURFACE_IDLE` | Session resolves to surface-only or unresolved learning (`learning_anchor_active = false`) | Assistant text appears, debug panel may show bridge/resolution info, progress stays hidden | Session persists in memory; introduction response appended to history | `handleStreamChunk()` in `static/app.js`; `paixueji_app.py:/api/start`; `tests/test_unknown_object_flow.py` |
| `CHAT_STREAMING` | Receive first/final start or continue chunk | `CHAT_ANCHOR_IDLE` | `learning_anchor_active = true` and no completion flag | Progress/debug metadata update; input is re-enabled after stream | Assistant/session state now target the anchor/current learning object | `handleStreamChunk()` in `static/app.js`; `paixueji_assistant.py:apply_resolution()/activate_anchor_topic()`; `tests/test_unknown_object_flow.py` |
| `CHAT_SURFACE_IDLE` | Send chat message | `CHAT_STREAMING` | `sessionId` exists and text is non-empty | User bubble is appended, send disabled, stop visible | `POST /api/continue`; backend processes the next turn | `sendMessage()` and `continueConversation()` in `static/app.js`; `paixueji_app.py:/api/continue` |
| `CHAT_ANCHOR_IDLE` | Send chat message | `CHAT_STREAMING` | `sessionId` exists and text is non-empty | Same as above | Same as above | `sendMessage()` and `continueConversation()` in `static/app.js`; `tests/test_api_flow.py::test_continue_conversation` |
| `CHAT_STREAMING` | Click `Stop` | `CHAT_SURFACE_IDLE` or `CHAT_ANCHOR_IDLE` | Stream is active | Current partial assistant bubble remains, stop hides, send re-enables, input is focused | Frontend aborts current request; backend stream may finish in background | `stopStreaming()` in `static/app.js`; checklist scenario 10 in `docs/action-flow-graph/05-completeness-checklist.md` |
| `CHAT_STREAMING` | Finish processing a turn with `detected_object_name` | `MANUAL_SWITCH_SUGGESTED` | Validator detected another object but chose `CONTINUE` | Yellow switch panel appears with detected object and force/dismiss CTAs | Stream chunk carries `detected_object_name`; session itself does not switch yet | `handleStreamChunk()` in `static/app.js`; checklist scenario 23 |
| `MANUAL_SWITCH_SUGGESTED` | Click `Switch to X` | `CHAT_SURFACE_IDLE` or `CHAT_ANCHOR_IDLE` | `detectedObject` and `sessionId` exist; `/api/force-switch` succeeds | Panel hides, system bubble announces switch, placeholder updates, debug object updates | `POST /api/force-switch`; assistant applies new resolution and may enable learning anchor | `forceSwitch()` in `static/app.js`; `paixueji_app.py:/api/force-switch`; `tests/test_unknown_object_flow.py::test_force_switch_high_confidence_enters_pre_anchor_state` |
| `MANUAL_SWITCH_SUGGESTED` | Click `Stay on current topic` | `CHAT_SURFACE_IDLE` or `CHAT_ANCHOR_IDLE` | None | Panel hides, topic remains unchanged | No backend call | `dismissSwitchPanel()` in `static/app.js` |
| `CHAT_SURFACE_IDLE` | Send a bridge/confirmation reply | `CHAT_ANCHOR_IDLE` | Backend accepts anchor activation or bridge follow | Current object changes to the anchor; progress becomes active | `/api/continue` activates anchor topic and resets progress counters | `tests/test_unknown_object_flow.py::test_medium_confidence_confirmation_accepts_anchor_and_switches`, `::test_start_with_high_confidence_anchor_stays_on_surface_object`, `::test_force_switch_high_confidence_enters_pre_anchor_state` |
| `CHAT_SURFACE_IDLE` | Send a rejection/surface-only reply | `CHAT_SURFACE_IDLE` | Backend suppresses or declines anchor activation | Conversation stays on the surface topic; progress remains hidden | `/api/continue` keeps `learning_anchor_active = false` and may suppress anchor | `tests/test_unknown_object_flow.py::test_medium_confidence_rejection_suppresses_anchor_and_stays_surface` |
| `CHAT_ANCHOR_IDLE` | Answer correctly below threshold | `CHAT_ANCHOR_IDLE` | Correct answer count after increment is below threshold 2 | Progress bar/count update; chat continues | Correct-answer counter increments in session/stream state | `CORRECT_ANSWER_THRESHOLD = 2` and `updateProgressIndicator()` in `static/app.js`; `tests/test_correct_answer_tracking.py` |
| `CHAT_ANCHOR_IDLE` | Answer correctly at threshold | `CHAT_COMPLETE_LOCKED` | Correct answer count reaches 2 and stream emits `chat_phase_complete` | Completion modal opens; input eventually stays disabled; theme/key concept may update | Theme classification/chat-complete branch runs and may later enable handoff | `handleStreamChunk()` in `static/app.js`; `tests/test_correct_answer_tracking.py::test_count_1_emits_theme_fields_in_completion_chunks` |
| `CHAT_COMPLETE_LOCKED` | Click primary CTA (`Got it!`) | `CHAT_COMPLETE_LOCKED` | Current object is not game-eligible | Modal closes, mini launcher stays hidden, input remains disabled | No backend call | `showChatPhaseCompleteModal()` and `closeChatPhaseCompleteModal()` in `static/app.js`; `tests/test_frontend_view_state.py` |
| `CHAT_COMPLETE_LOCKED` | Click primary CTA (`Let's Play!`) or mini launcher | `CHAT_COMPLETE_LOCKED` | Current object is game-eligible | Modal stays/reopens until redirect; user leaves Paixueji on success | `POST /api/handoff`; JSON context written under `/tmp/handoff/`; browser redirects to WonderLens URL | `handoff()` in `static/app.js`; `paixueji_app.py:/api/handoff`; `tests/test_all_endpoints.py::test_handoff_uses_tmp_handoff_route` |
| `SETUP_READY` | Click `Reports` | `REPORTS_BROWSING` | None | Reports gallery replaces setup form | `GET /api/reports/hf` loads metadata | `openReportsViewer()` in `static/reports.js`; `tests/test_hf_report_viewer.py` |
| `CHAT_SURFACE_IDLE` or `CHAT_ANCHOR_IDLE` | Click `Reports` | `REPORTS_BROWSING` | None | Reports page replaces chat; return target is remembered | `GET /api/reports/hf` loads metadata | `window.paixuejiUi.showReportsPage()` and `leaveReportsPage()` in `static/app.js`; `tests/test_frontend_view_state.py` |
| `REPORTS_BROWSING` | Open a report card | `REPORTS_BROWSING` | Report fetch succeeds | Detail replay replaces gallery; critique and raw popups become available | `GET /api/reports/hf/<date>/<filename>` | `loadReportDetail()` in `static/reports.js`; `tests/test_hf_report_viewer.py::test_hf_report_detail_exposes_transcript_and_critique_data` |
| `REPORTS_BROWSING` | Close reports | `SETUP_READY` or prior chat idle state | `reportsReturnView` decides where to go | Start form or chat view is restored; report overlays are cleared | No new backend effect | `closeReportsViewer()` in `static/reports.js`; `tests/test_frontend_view_state.py` |
| `CHAT_SURFACE_IDLE` or `CHAT_ANCHOR_IDLE` | Click `Send Report for Review` | `CRITIQUE_REVIEWING` | Session has an introduction or exchanges | Manual critique overlay opens with populated exchange cards and session banner | `GET /api/exchanges/<session_id>` | `showManualCritiqueForm()` in `static/app.js`; `paixueji_app.py:/api/exchanges/<session_id>` |
| `CRITIQUE_REVIEWING` | Submit `Report Database` flow | `CHAT_SURFACE_IDLE` or `CHAT_ANCHOR_IDLE` | At least one critique/global conclusion; save succeeds | Overlay closes; report button temporarily shows `Report Saved!` | `POST /api/manual-critique` with `skip_traces: true`; report markdown saved | `submitManualCritiqueToDatabase()` in `static/app.js`; `paixueji_app.py:/api/manual-critique` |
| `CRITIQUE_REVIEWING` | Submit `Evolving Agent` flow | `CRITIQUE_REVIEWING` | Save succeeds and traces are returned | Optimization suggestion buttons appear; overlay stays open | `POST /api/manual-critique` without `skip_traces`; response may include culprit traces | `submitManualCritiqueWithEvolution()` and `showOptimizationPrompts()` in `static/app.js` |
| `CRITIQUE_REVIEWING` | Run/approve/refine/reject optimization | `CRITIQUE_REVIEWING` | Optimization endpoints return success or handled error | Review modal opens, can be refined or closed, and on approval alerts that new sessions use the updated prompt | Calls `/api/optimize-prompt`, `/approve`, `/refine`, `/reject`; pending optimization files are created/merged/deleted | `runOptimization()`, `approveOptimization()`, `submitRejectionAndRetry()`, `discardOptimization()` in `static/app.js`; `/api/optimize-prompt*` in `paixueji_app.py` |
| `CHAT_SURFACE_IDLE` or `CHAT_ANCHOR_IDLE` | Send message after session expiry | `REQUEST_ERROR_OR_MISSING_SESSION` | `/api/continue` returns 404 | Retry/error bubble appears with `Session not found...start a new conversation` | Backend returns HTTP 404 because `sessions.get(session_id)` is empty | `continueConversation()` in `static/app.js`; `paixueji_app.py:/api/continue`; `tests/test_api_flow.py::test_continue_invalid_session` |
| `CHAT_STREAMING` | Backend emits SSE error (including 429) | `REQUEST_ERROR_OR_MISSING_SESSION` | SSE `error` event or request exception | Partial bubble clears; retry UI appears; no `complete` event | Start/continue stream ends with structured error payload | `handleSSEEvent()` and `renderRetryUI()` in `static/app.js`; `tests/test_api_flow.py::*rate_limit_error*` |
| `REPORTS_BROWSING` | Reports fetch/detail fetch fails | `REQUEST_ERROR_OR_MISSING_SESSION` | Any non-OK response while loading reports | Viewer shows inline `rv-error` state | Failed `GET /api/reports/hf*` | `loadReportGallery()` and `loadReportDetail()` in `static/reports.js` |

## 5. Scenario Catalog

### CHAT-START-SUPPORTED

- Trigger: User enters an object and clicks `Start Learning!`.
- Preconditions: Browser is on the setup page; object name is non-empty.
- Steps: Frontend clears prior chat state, sends `POST /api/start`, parses SSE chunks, stores the first `session_id`, and renders the streamed introduction.
- Expected UI: Chat view opens, assistant text streams in, stop button appears during streaming, debug panel appears once a session exists.
- Expected Backend Behavior: Session is created in the in-memory `sessions` dict; assistant resolution is applied; introduction response is streamed as `chunk` events followed by `complete`.
- Analytics Event: not found.
- Edge Cases: Missing object blocks the request with a frontend alert; age outside 3-8 is normalized to `None` server-side.
- Open Questions: Docs still describe older focus/tone state fields that are not visible in the current setup UI.

### CHAT-START-SURFACE-ONLY

- Trigger: User starts with an unresolved or not-yet-activated topic such as `cat food` or an unknown object.
- Preconditions: `/api/start` resolves the object with `learning_anchor_active = false`.
- Steps: Backend resolves surface and anchor metadata, streams an introduction, and keeps progress locked off.
- Expected UI: Chat opens on the surface topic; progress indicator remains hidden; debug panel may show anchor/debug data.
- Expected Backend Behavior: Session stores `surface_object_name`, `anchor_object_name`, `anchor_status`, and `learning_anchor_active = false`.
- Analytics Event: not found.
- Edge Cases: Unresolved objects can emit `bridge_not_started`; high-confidence related objects can stay on the surface while pre-anchor logic waits for later turns.
- Open Questions: Whether surface-only bridge states should be treated as a first-class product mode is only test-evidenced, not documented in the adapter hints.

### CHAT-BRIDGE-ACCEPT

- Trigger: Child reply confirms or naturally follows an anchor/bridge prompt.
- Preconditions: Active session is in surface-only/pre-anchor chat.
- Steps: Child sends a reply through `/api/continue`; backend classifies confirmation/bridge follow and switches the current object to the anchor.
- Expected UI: Subsequent chunk(s) show the new current object; progress becomes visible because learning is now anchored.
- Expected Backend Behavior: Assistant activates the anchor topic, resets bridge counters, and resumes chat on the anchor object.
- Analytics Event: not found.
- Edge Cases: High-confidence bridge follow can activate without an explicit yes/no; medium-confidence flows may ask for confirmation first.
- Open Questions: The exact copy shown for bridge confirmation is not centralized in a dedicated UI surface and is mostly inferable from tests.

### CHAT-BRIDGE-REJECT

- Trigger: Child rejects the anchor suggestion or insists on staying with the surface topic.
- Preconditions: Active surface-only/pre-anchor session.
- Steps: Child sends a reply through `/api/continue`; backend suppresses or declines anchor activation.
- Expected UI: Chat remains on the surface topic; progress stays hidden.
- Expected Backend Behavior: Session keeps `learning_anchor_active = false`; anchor metadata may remain for debugging/suppression.
- Analytics Event: not found.
- Edge Cases: Docs mention system-managed object-selection UI, but current code uses ordinary chat text instead.
- Open Questions: The long-term suppression behavior is test-evidenced but not described in current docs.

### CHAT-MANUAL-SWITCH-FORCE

- Trigger: Validator detects another object but decides `CONTINUE`, and the learner clicks `Switch to X`.
- Preconditions: Manual switch panel is visible; `sessionId` and `detectedObject` are set.
- Steps: Frontend calls `/api/force-switch`, updates `currentObject`, inserts a system bubble, then hides the panel.
- Expected UI: Yellow panel disappears; system message confirms the switch; placeholder text changes to the new object.
- Expected Backend Behavior: Assistant reapplies object resolution for the new object and may toggle `learning_anchor_active`.
- Analytics Event: not found.
- Edge Cases: Force-switch can still land in a pre-anchor surface-only state if the new object resolves that way.
- Open Questions: `switchReasoning` is rendered but currently blanked in the frontend.

### CHAT-MANUAL-SWITCH-DISMISS

- Trigger: Learner clicks `Stay on current topic`.
- Preconditions: Manual switch panel is visible.
- Steps: Frontend clears `detectedObject` and hides the panel without contacting the server.
- Expected UI: Chat remains unchanged except the panel disappears.
- Expected Backend Behavior: None.
- Analytics Event: not found.
- Edge Cases: Subsequent turns can surface another detected object again.
- Open Questions: No evidence of persistence for dismissed suggestions across turns.

### CHAT-COMPLETE-HANDOFF

- Trigger: Anchor-learning correct-answer count reaches the threshold and later the learner dismisses the completion modal or launches activities.
- Preconditions: Active anchor-learning chat; threshold branch emits `chat_phase_complete`.
- Steps: Frontend shows the modal, disables input, and either closes it locally or calls `/api/handoff` for game-eligible objects.
- Expected UI: Modal appears with `Got it!` or `Let's Play!`; game-eligible objects can minimize to a bottom-left launcher and reopen the modal.
- Expected Backend Behavior: Theme/key concept fields can be populated on completion; optional `/api/handoff` writes a JSON transcript under `/tmp/handoff/` and returns a redirect URL.
- Analytics Event: not found.
- Edge Cases: Input remains disabled even after stream-finally cleanup; non-game objects never show the mini launcher.
- Open Questions: Docs still describe "infinite mode" while current code/tests clearly preserve a threshold-gated completion prompt.

### REPORTS-BROWSE-DETAIL

- Trigger: User clicks `Reports`, searches, and opens a report card.
- Preconditions: Browser is on setup or chat view.
- Steps: Frontend loads `/api/reports/hf`, renders cards, filters by object name, then loads report detail and optional raw markdown.
- Expected UI: Gallery cards show object/date/chips; detail view replays the conversation, marks critiqued bubbles, and can open critique/raw popups.
- Expected Backend Behavior: Report metadata list comes from `reports/HF`; detail/raw endpoints parse or read markdown files.
- Analytics Event: not found.
- Edge Cases: Empty search results render `No reports match your search.`; fetch failures render inline viewer errors.
- Open Questions: Reports are globally visible in the UI with no access control; intended audience is unclear.

### CRITIQUE-SAVE-REPORT

- Trigger: Reviewer opens `Send Report for Review` and submits the report-database path.
- Preconditions: Active session exists with at least an introduction or one exchange; reviewer adds at least one critique or a global conclusion.
- Steps: Frontend loads `/api/exchanges/<session_id>`, reviewer fills fields, then posts `/api/manual-critique` with `skip_traces: true`.
- Expected UI: Overlay shows session chips plus exchange cards; successful save closes the overlay and temporarily changes the report button to `Report Saved!`.
- Expected Backend Behavior: Transcript/exchanges are extracted from in-memory session history; a markdown report is written to `reports/HF/<date>/...`.
- Analytics Event: not found.
- Edge Cases: Empty submission is rejected client-side; missing session returns 404.
- Open Questions: There is no explicit status page showing the saved report; reviewer must rely on the button toast/state or open the reports viewer.

### CRITIQUE-EVOLVE-OPTIMIZE

- Trigger: Reviewer submits the evolving-agent path and then chooses a culprit optimization.
- Preconditions: Same as critique save, plus backend returns culprit traces.
- Steps: Frontend keeps the overlay open, renders optimization buttons, opens the optimization modal, and can approve, refine, or reject the suggested patch.
- Expected UI: Modal shows failure pattern, prompt diff, preview cards, optional router-patch table, and approval/rejection controls.
- Expected Backend Behavior: `/api/manual-critique` returns traces; `/api/optimize-prompt*` creates, refines, approves, or deletes pending optimization artifacts.
- Analytics Event: not found.
- Edge Cases: `skip_traces: true` bypasses this path entirely; missing `culprit_name` or pending optimization IDs return 400/404.
- Open Questions: This is operator tooling embedded in the same page as learner chat, but the product boundary and permission model are undocumented.

### ERROR-MISSING-SESSION-OR-RATE-LIMIT

- Trigger: Continue request uses an expired/invalid session or start/continue hits an SSE error such as 429.
- Preconditions: Existing chat/report request is attempted.
- Steps: Frontend catches HTTP/SSE failure, clears any partial bubble, and renders retry/error UI.
- Expected UI: Missing session errors instruct the user to start a new conversation; rate limits surface retry actions and suppress `complete`.
- Expected Backend Behavior: `/api/continue` returns 404 when `sessions.get(session_id)` fails; SSE generators emit structured `error` events for rate-limited failures.
- Analytics Event: not found.
- Edge Cases: Server restart clears all sessions because storage is in-memory only.
- Open Questions: Whether the app should auto-reset on missing session instead of waiting for manual restart is a documented operational gap, not a resolved behavior.

## 6. Coverage Matrix

### Page x User State

| Page | State | Covered? | Evidence |
|---|---|---|---|
| Setup | `SETUP_READY` | yes | `window.paixuejiUi.showMainPage()` and `#startForm` in `static/app.js` / `static/index.html` |
| Setup | `CHAT_SURFACE_IDLE` | N/A | Setup is hidden when chat view is active |
| Setup | `CHAT_ANCHOR_IDLE` | N/A | Setup is hidden when chat view is active |
| Setup | `CHAT_STREAMING` | N/A | Setup is hidden before stream starts rendering chat |
| Setup | `MANUAL_SWITCH_SUGGESTED` | N/A | Switch panel only renders inside chat |
| Setup | `CHAT_COMPLETE_LOCKED` | N/A | Completion modal is chat-scoped |
| Setup | `REPORTS_BROWSING` | N/A | Reports replace the setup view |
| Setup | `CRITIQUE_REVIEWING` | N/A | Critique overlay depends on an active session/debug panel |
| Setup | `REQUEST_ERROR_OR_MISSING_SESSION` | partial | Start validation alert exists locally; network error handling occurs after chat has already opened |
| Chat | `SETUP_READY` | N/A | Chat view is a different primary view |
| Chat | `CHAT_SURFACE_IDLE` | yes | `learning_anchor_active = false` path in `handleStreamChunk()` and unknown-object tests |
| Chat | `CHAT_ANCHOR_IDLE` | yes | Progress and debug updates in `handleStreamChunk()`; correct-answer tests |
| Chat | `CHAT_STREAMING` | yes | `isStreaming`, stop button, SSE parser in `static/app.js` |
| Chat | `MANUAL_SWITCH_SUGGESTED` | yes | `#manualSwitchPanel` and `handleStreamChunk()` |
| Chat | `CHAT_COMPLETE_LOCKED` | yes | `chat_phase_complete`, completion modal, disabled input |
| Chat | `REPORTS_BROWSING` | N/A | Reports replace chat as the primary view |
| Chat | `CRITIQUE_REVIEWING` | partial | Critique overlay is launched from chat/debug context but visually overlays the page |
| Chat | `REQUEST_ERROR_OR_MISSING_SESSION` | yes | Retry bubble / 404 handling in `continueConversation()` and `handleSSEEvent()` |
| Reports | `SETUP_READY` | N/A | Reports is a separate primary view |
| Reports | `CHAT_SURFACE_IDLE` | N/A | Reports view replaces chat |
| Reports | `CHAT_ANCHOR_IDLE` | N/A | Reports view replaces chat |
| Reports | `CHAT_STREAMING` | N/A | No evidence of report browsing during active stream |
| Reports | `MANUAL_SWITCH_SUGGESTED` | N/A | Chat-only state |
| Reports | `CHAT_COMPLETE_LOCKED` | N/A | Chat-only state |
| Reports | `REPORTS_BROWSING` | yes | `loadReportGallery()`, `renderGallery()`, `loadReportDetail()` |
| Reports | `CRITIQUE_REVIEWING` | partial | Report detail can open critique/raw popups, but not the session-bound manual critique overlay |
| Reports | `REQUEST_ERROR_OR_MISSING_SESSION` | yes | Inline `rv-error` rendering in `static/reports.js` |
| Manual critique overlay | `SETUP_READY` | N/A | Requires active session/debug panel |
| Manual critique overlay | `CHAT_SURFACE_IDLE` | partial | Opens over the chat page after `/api/exchanges/<session_id>` succeeds |
| Manual critique overlay | `CHAT_ANCHOR_IDLE` | partial | Same as above |
| Manual critique overlay | `CHAT_STREAMING` | no | No evidence it is safe/available during active streaming |
| Manual critique overlay | `MANUAL_SWITCH_SUGGESTED` | no | No evidence of both being intentionally supported together |
| Manual critique overlay | `CHAT_COMPLETE_LOCKED` | partial | Possible after completion because debug panel remains, but not directly tested |
| Manual critique overlay | `REPORTS_BROWSING` | N/A | Separate critique surface |
| Manual critique overlay | `CRITIQUE_REVIEWING` | yes | `showManualCritiqueForm()` and overlay HTML |
| Manual critique overlay | `REQUEST_ERROR_OR_MISSING_SESSION` | partial | Alerts exist on failed exchange load or critique submit |
| Optimization modal | `SETUP_READY` | N/A | Requires critique flow |
| Optimization modal | `CHAT_SURFACE_IDLE` | N/A | Requires critique flow |
| Optimization modal | `CHAT_ANCHOR_IDLE` | N/A | Requires critique flow |
| Optimization modal | `CHAT_STREAMING` | no | No evidence of support during active streaming |
| Optimization modal | `MANUAL_SWITCH_SUGGESTED` | no | No evidence of support together |
| Optimization modal | `CHAT_COMPLETE_LOCKED` | partial | Possible only if critique flow is started after completion |
| Optimization modal | `REPORTS_BROWSING` | N/A | Not used from the reports viewer |
| Optimization modal | `CRITIQUE_REVIEWING` | yes | `runOptimization()` and modal HTML |
| Optimization modal | `REQUEST_ERROR_OR_MISSING_SESSION` | yes | Modal renders inline request/HTTP error text for optimization failures |

### User State x Core Behavior

| State | Behavior | Covered? | Evidence |
|---|---|---|---|
| `SETUP_READY` | Start session | yes | `startConversation()` |
| `SETUP_READY` | Send/stream answer | no | `sendMessage()` returns early without `sessionId` |
| `SETUP_READY` | Switch topic | no | Requires active session or switch panel |
| `SETUP_READY` | Review/report session | partial | Reports viewer is available; session-bound critique is not |
| `SETUP_READY` | Enter activities handoff | no | Requires completed chat |
| `CHAT_SURFACE_IDLE` | Start session | N/A | Session already exists |
| `CHAT_SURFACE_IDLE` | Send/stream answer | yes | `sendMessage()` + `/api/continue` |
| `CHAT_SURFACE_IDLE` | Switch topic | yes | Bridge activation and force-switch paths are both available |
| `CHAT_SURFACE_IDLE` | Review/report session | yes | Debug panel report flow and reports button |
| `CHAT_SURFACE_IDLE` | Enter activities handoff | no | Completion threshold not reached yet |
| `CHAT_ANCHOR_IDLE` | Start session | N/A | Session already exists |
| `CHAT_ANCHOR_IDLE` | Send/stream answer | yes | `sendMessage()` + `/api/continue` |
| `CHAT_ANCHOR_IDLE` | Switch topic | yes | Manual switch and validator-driven switching can occur mid-chat |
| `CHAT_ANCHOR_IDLE` | Review/report session | yes | Debug panel report flow and reports button |
| `CHAT_ANCHOR_IDLE` | Enter activities handoff | partial | Only after threshold turn emits completion |
| `CHAT_STREAMING` | Start session | partial | Start stream itself is this state; re-trigger is blocked by disabled send and current controller |
| `CHAT_STREAMING` | Send/stream answer | yes | Active SSE parsing/stream rendering |
| `CHAT_STREAMING` | Switch topic | partial | Detection/switch metadata arrive here, but user action completes later |
| `CHAT_STREAMING` | Review/report session | no | No evidence critique/report launch is supported mid-stream |
| `CHAT_STREAMING` | Enter activities handoff | partial | Completion flag is emitted in-stream before the locked state begins |
| `MANUAL_SWITCH_SUGGESTED` | Start session | N/A | Session already exists |
| `MANUAL_SWITCH_SUGGESTED` | Send/stream answer | partial | User can still type later, but the panel itself is a switch branch |
| `MANUAL_SWITCH_SUGGESTED` | Switch topic | yes | `forceSwitch()` or dismiss |
| `MANUAL_SWITCH_SUGGESTED` | Review/report session | partial | Not directly tested, but debug/reports controls remain on the page |
| `MANUAL_SWITCH_SUGGESTED` | Enter activities handoff | no | Not a completion state |
| `CHAT_COMPLETE_LOCKED` | Start session | no | Existing input is disabled until reset |
| `CHAT_COMPLETE_LOCKED` | Send/stream answer | no | `disableCompletedChatInput()` keeps input/send disabled |
| `CHAT_COMPLETE_LOCKED` | Switch topic | no | No evidence chat can continue from the locked state |
| `CHAT_COMPLETE_LOCKED` | Review/report session | partial | Debug tools may remain reachable, but not explicitly tested |
| `CHAT_COMPLETE_LOCKED` | Enter activities handoff | yes | Modal CTA and mini launcher call `handoff()` for eligible objects |
| `REPORTS_BROWSING` | Start session | no | Reports view has no start CTA |
| `REPORTS_BROWSING` | Send/stream answer | no | Reports view has no chat input |
| `REPORTS_BROWSING` | Switch topic | no | Reports view is read-only |
| `REPORTS_BROWSING` | Review/report session | yes | Gallery/detail/raw/critique popup flows in `static/reports.js` |
| `REPORTS_BROWSING` | Enter activities handoff | no | Not exposed from reports viewer |
| `CRITIQUE_REVIEWING` | Start session | no | Critique tooling assumes an existing session |
| `CRITIQUE_REVIEWING` | Send/stream answer | no | Overlay/modal flows do not stream chat |
| `CRITIQUE_REVIEWING` | Switch topic | no | Critique tooling does not mutate chat topic |
| `CRITIQUE_REVIEWING` | Review/report session | yes | `/api/exchanges`, `/api/manual-critique`, `/api/optimize-prompt*` |
| `CRITIQUE_REVIEWING` | Enter activities handoff | no | Not exposed here |
| `REQUEST_ERROR_OR_MISSING_SESSION` | Start session | partial | User can restart manually from setup/reset, but there is no automatic recovery |
| `REQUEST_ERROR_OR_MISSING_SESSION` | Send/stream answer | partial | Retry UI exists for some failures; missing session requires new conversation |
| `REQUEST_ERROR_OR_MISSING_SESSION` | Switch topic | no | Switching depends on a healthy active session |
| `REQUEST_ERROR_OR_MISSING_SESSION` | Review/report session | partial | Reports/optimization surfaces show errors, but recovery is manual |
| `REQUEST_ERROR_OR_MISSING_SESSION` | Enter activities handoff | no | Not exposed as an error recovery branch |

### Error Type x Page Response

| Error Type | Page | Response | Evidence |
|---|---|---|---|
| Missing object input | Setup | Alert `Please enter an object name`; request blocked client-side | `startConversation()` in `static/app.js` |
| HTTP 404 missing session | Chat | Retry/error bubble with restart guidance | `continueConversation()` in `static/app.js`; `/api/continue` in `paixueji_app.py`; `tests/test_api_flow.py::test_continue_invalid_session` |
| SSE 429 / rate limit | Chat | Partial bubble cleared; retry UI shown; no `complete` event | `handleSSEEvent()` in `static/app.js`; `tests/test_api_flow.py::*rate_limit_error*` |
| Stream abort | Chat | Partial response remains visible; stop hides; input re-enables | `stopStreaming()` in `static/app.js`; checklist scenario 10 |
| Report gallery/detail fetch failure | Reports | Inline `rv-error` message inside `#reportViewer` | `loadReportGallery()` and `loadReportDetail()` in `static/reports.js` |
| Empty reports search | Reports | Inline empty state `No reports match your search.` | `renderGallery()` in `static/reports.js` |
| Missing session during critique fetch | Manual critique overlay | Alert `Failed to load exchanges: ...` or 404-driven failure | `showManualCritiqueForm()` in `static/app.js`; `/api/exchanges/<session_id>` in `paixueji_app.py` |
| Empty critique submission | Manual critique overlay | Client alert asking for at least one critique/global conclusion | `validateManualCritiqueSubmission()` in `static/app.js` |
| Missing `culprit_name` / failed optimization request | Optimization modal | Inline modal error text or alert; approval button stays disabled/enabled accordingly | `/api/optimize-prompt` in `paixueji_app.py`; `runOptimization()` in `static/app.js` |
| Missing pending optimization ID | Optimization modal | 404 error surfaced in modal or alert on approve/refine | `/approve` and `/refine` routes in `paixueji_app.py` |

### Permission Level x Visible Action

| Permission Level | Visible Action | Covered? | Evidence |
|---|---|---|---|
| No active session | `Start Learning!` | yes | Setup view is default |
| No active session | `Reports` | yes | Reports button is always in the header |
| No active session | `Send` | no | Chat input is hidden until chat view; `sendBtn` disabled by default |
| No active session | `Send Report for Review` | no | Debug panel is hidden until a session starts |
| No active session | `Switch to detected object` | no | Requires manual switch panel + session |
| No active session | Completion / activities CTA | no | Requires `chat_phase_complete` |
| Active session user | `Send` | yes | `sendMessage()` in chat view |
| Active session user | `Stop` | yes | `stopBtn` is shown while streaming |
| Active session user | `Send Report for Review` | yes | Debug panel action button |
| Active session user | `Switch to detected object` | yes | Manual switch panel CTA |
| Active session user | `Reports` | yes | Header button remains available |
| Active session user | Completion / activities CTA | partial | Only visible after threshold completion |
| Reviewer/operator on same page | Submit to report DB | yes | Manual critique overlay buttons |
| Reviewer/operator on same page | Submit for evolving agent | yes | Manual critique overlay buttons |
| Reviewer/operator on same page | Approve/refine/reject optimization | yes | Optimization modal buttons |

### Auth Status x CTA Branch

| Auth Status | CTA | Branch | Evidence |
|---|---|---|---|
| Unauthenticated / open-access | `Start Learning!` | Directly starts a local session via `/api/start` | No auth checks in `static/app.js` or `paixueji_app.py` |
| Unauthenticated / open-access | `Reports` | Opens HF report viewer directly | `openReportsViewer()` and `/api/reports/hf` have no auth guards |
| Unauthenticated / open-access | `Send Report for Review` | Becomes available after session/debug panel opens; no login gate | `static/index.html#sendReportBtn`; `showManualCritiqueForm()` |
| Unauthenticated / open-access | Completion CTA | Direct local close or `/api/handoff` redirect; no login gate | `showChatPhaseCompleteModal()` and `/api/handoff` |
| Unauthenticated / open-access | Optimization approval flow | Directly calls `/api/optimize-prompt*`; no auth gate found | `runOptimization()`/`approveOptimization()` and corresponding routes |
| Authenticated user | Any CTA | not found | No authentication system or alternate CTA branch found in current sources |

### Feature Flag x UI Difference

| Feature Flag | UI Difference | Covered? | Evidence |
|---|---|---|---|
| `has_game` entity metadata | Completion CTA changes from `Got it!` to `Let's Play!`; mini launcher can appear | yes | `/api/objects` marks `has_game`; `isCurrentObjectGameEligible()` and completion modal logic in `static/app.js`; `tests/test_frontend_view_state.py` |
| `skip_traces` request flag | Manual critique save either closes immediately or continues into optimization suggestions | yes | `submitManualCritiqueToDatabase()` vs `submitManualCritiqueWithEvolution()`; `/api/manual-critique` |
| `router_patch` present in optimization result | Optimization modal shows/hides routing patch table | yes | `_renderRouterPatch()` in `static/app.js`; `/api/optimize-prompt` response contract in `paixueji_app.py` |
| Runtime feature-flag framework | Global UI gating | not found | No dedicated feature-flag service/config was found in the primary sources |

## 7. Known Unknowns

- Unknown: `docs/action-flow-graph/02-state-models.md` still describes removed object-selection UI, system/manual focus controls, and "infinite mode," but current `static/app.js` and tests show natural-language object selection plus a threshold-driven completion modal. This is a code-doc conflict.
- Unknown: `objectSelectionPanel` still exists in `static/index.html` and the UI controller, but the active selection functions are explicitly removed in `static/app.js`. It is unclear whether this is dead UI, a planned return path, or a partial rollback.
- Unknown: The adapter hints mention `system-managed focus mode` and `manual focus mode`, but the current frontend exposes neither as user controls. The behavior may still exist in backend internals/docs, but it is not clearly user-visible in the shipped browser.
- Unknown: Reports, critique, and optimization tooling are exposed in the same public UI with no authentication or role gating found. Intended user roles and access boundaries are not documented.
- Unknown: `switchReasoning` is rendered in the manual switch panel but is currently set to an empty string client-side, so the user-facing rationale for detected-object suggestions is effectively absent.
- Unknown: No analytics events were found for the covered flows, so funnel/usage instrumentation cannot be mapped from current evidence.
