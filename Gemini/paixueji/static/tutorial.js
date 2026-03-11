/**
 * Paixueji Tutorial — Step-by-Step Spotlight Walkthrough
 *
 * Pure vanilla JS, no external dependencies.
 * Entry points:
 *   startTutorial(phase?)        — launch from a given phase (default 'setup')
 *   tutorialAdvanceToChat()      — called by app.js after startConversation() fires
 *
 * Persistence:
 *   localStorage key 'paixueji_tutorial_done' suppresses auto-launch.
 *   The '?' button always clears the flag and re-launches.
 */

'use strict';

// ---------------------------------------------------------------------------
// Step definitions
// ---------------------------------------------------------------------------
const TUTORIAL_STEPS = [
  // ── Phase A: Setup ────────────────────────────────────────────────────────
  {
    phase: 'setup',
    selector: null,
    title: 'Welcome to Paixueji!',
    body: 'This tool helps children (age 3–8) learn through AI-guided Q&amp;A. Let\'s walk you through how it works in just a few steps.',
  },
  {
    phase: 'setup',
    selector: '.object-input-row',
    title: 'Choose an Object',
    body: 'Type what your child will learn about (e.g., "apple"). When you finish entering it, Paixueji automatically looks up related concepts so you can preview the topic before starting.',
  },
  {
    phase: 'setup',
    selector: '#age',
    title: "Set the Child's Age",
    body: 'The age adjusts question difficulty. A 3-year-old gets simpler questions than a 6-year-old.',
  },
  {
    phase: 'setup',
    selector: null,
    selectorFn: function () {
      return document.querySelector('button[onclick*="startConversation"]');
    },
    title: 'Start the Session',
    body: 'Click <strong>Start Learning!</strong> when you\'re ready. The chat interface will appear below.',
  },
  // ── Phase B: Chat ─────────────────────────────────────────────────────────
  {
    phase: 'chat',
    selector: '#progressIndicator',
    title: 'Progress Bar',
    body: 'Tracks correct answers (0–4). After <strong>4 correct answers</strong>, the AI transitions into a deeper "Guide Phase" where it asks the child to reason about <em>why</em> things happen.',
  },
  {
    phase: 'chat',
    selector: '#userInput',
    title: 'Sending Answers',
    body: 'Type the child\'s answer and press <strong>Enter</strong> or click <strong>Send</strong>. The button disables during streaming — wait for the AI to finish before sending the next answer.',
  },
  {
    phase: 'chat',
    selector: '#stopBtn',
    title: 'Stop Button',
    body: 'This button appears while the AI is responding. Click it if the response runs too long or goes off-track. The message so far is preserved.',
  },
  // ── Phase C: Review ───────────────────────────────────────────────────────
  {
    phase: 'review',
    selector: '#debugPanel',
    title: 'Send for Review',
    body: 'This panel (right side of screen) shows session details. Click <strong>📝 Send Report for Review</strong> when the session is finished — this is how you give feedback as a tester.',
  },
  {
    phase: 'review',
    selector: '#manualCritiqueOverlay',
    title: 'Manual Critique Form',
    body: 'Check the exchanges you found problematic. For each one, describe what the AI should have asked or said differently. Your feedback is used to improve the model.',
  },
];

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let _step = 0;               // current step index
let _active = false;         // tutorial is running
let _spotlightEl = null;     // element currently spotlit
let _tooltipEl = null;       // tooltip DOM node
let _overlayEl = null;       // fixed overlay element for screen dimming

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Launch (or re-launch) the tutorial from the first step of `phase`.
 * Always clears the "done" flag so the '?' button always works.
 */
function startTutorial(phase) {
  phase = phase || 'setup';
  localStorage.removeItem('paixueji_tutorial_done');
  _active = true;
  var idx = _firstIndexOfPhase(phase);
  _showStep(idx >= 0 ? idx : 0);
}

/**
 * Called by app.js immediately after the chat UI becomes visible.
 * Advances the tutorial from setup steps to chat steps.
 */
function tutorialAdvanceToChat() {
  if (!_active) return;
  var idx = _firstIndexOfPhase('chat');
  if (idx >= 0) _showStep(idx);
}

/**
 * Called by app.js when debugPanel becomes visible.
 * Only advances to the review phase if we are paused exactly at the
 * chat→review boundary — early calls (mid-chat AI responses) are no-ops.
 */
function tutorialAdvanceToReport() {
  if (!_active) return;
  // Only advance if the *next* step is the first review step.
  var nextIdx = _step + 1;
  if (nextIdx < TUTORIAL_STEPS.length &&
      TUTORIAL_STEPS[nextIdx].phase === 'review') {
    _showStep(nextIdx);
  }
}

/**
 * Called by app.js when #manualCritiqueOverlay becomes visible.
 * Advances from step 11 (debugPanel) to step 12 (manualCritiqueOverlay), or
 * re-anchors spotlight if the tutorial is already showing step 12 with a
 * centered tooltip (user clicked Next before opening the overlay).
 */
function tutorialAdvanceToManualCritique() {
  if (!_active) return;
  var nextIdx = _step + 1;
  // Primary case: advance 11 → 12
  if (nextIdx < TUTORIAL_STEPS.length &&
      TUTORIAL_STEPS[nextIdx].selector === '#manualCritiqueOverlay') {
    _showStep(nextIdx);
    return;
  }
  // Re-anchor case: already at step 12 but overlay wasn't visible when Next was clicked
  if (_step < TUTORIAL_STEPS.length &&
      TUTORIAL_STEPS[_step].selector === '#manualCritiqueOverlay') {
    _showStep(_step);
  }
}

// Expose on window so app.js and HTML onclick can reach them.
window.startTutorial = startTutorial;
window.tutorialAdvanceToChat = tutorialAdvanceToChat;
window.tutorialAdvanceToReport = tutorialAdvanceToReport;
window.tutorialAdvanceToManualCritique = tutorialAdvanceToManualCritique;
window._tutorialNext = _tutorialNext;
window._tutorialPrev = _tutorialPrev;
window._tutorialSkip = _tutorialSkip;

// ---------------------------------------------------------------------------
// Core step rendering
// ---------------------------------------------------------------------------

function _showStep(index) {
  _clearSpotlight();
  _removeTooltip();

  if (index < 0 || index >= TUTORIAL_STEPS.length) {
    _endTutorial();
    return;
  }

  _step = index;
  var step = TUTORIAL_STEPS[index];

  // Resolve target element
  var target = _resolveTarget(step);

  // Only spotlight if element is visible in the DOM
  if (target && _isVisible(target)) {
    _applySpotlight(target);
    target.scrollIntoView({ behavior: 'instant', block: 'center' });
  } else {
    target = null; // fall back to centered tooltip
  }

  _renderTooltip(step, index, target);
}

function _resolveTarget(step) {
  if (step.selectorFn) return step.selectorFn();
  if (step.selector)   return document.querySelector(step.selector);
  return null;
}

function _isVisible(el) {
  if (!el) return false;
  var style = window.getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden') return false;
  var rect = el.getBoundingClientRect();
  return rect.width > 0 || rect.height > 0;
}

// ---------------------------------------------------------------------------
// Spotlight
// ---------------------------------------------------------------------------

function _applySpotlight(el) {
  // Create a fixed full-screen overlay for dimming — no overflow changes needed.
  _overlayEl = document.createElement('div');
  _overlayEl.className = 'tutorial-overlay';
  document.body.appendChild(_overlayEl);

  el.classList.add('tutorial-active-el');
  _spotlightEl = el;
}

function _clearSpotlight() {
  if (_spotlightEl) {
    _spotlightEl.classList.remove('tutorial-active-el');
    _spotlightEl = null;
  }
  if (_overlayEl) {
    _overlayEl.remove();
    _overlayEl = null;
  }
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

function _renderTooltip(step, index, target) {
  var el = document.createElement('div');
  el.id = 'tutorial-tooltip';

  var isFirst      = index === 0;
  var currentPhase = step.phase;
  var phaseStart   = _firstIndexOfPhase(currentPhase);
  var phaseTotal   = TUTORIAL_STEPS.filter(function(s) { return s.phase === currentPhase; }).length;
  var phasePos     = index - phaseStart + 1;          // 1-based position within phase
  var isLastInPhase = phasePos === phaseTotal;

  el.innerHTML =
    '<div class="tutorial-step-title">' + step.title + '</div>' +
    '<div class="tutorial-step-body">'  + step.body  + '</div>' +
    '<div class="tutorial-nav">' +
      '<button onclick="_tutorialPrev()" class="tut-btn tut-btn-back"' + (isFirst ? ' disabled' : '') + '>&#8592; Back</button>' +
      '<button onclick="_tutorialSkip()" class="tut-btn tut-btn-skip">Skip</button>' +
      '<button onclick="_tutorialNext()" class="tut-btn tut-btn-next">' + (isLastInPhase ? 'Finish ✓' : 'Next &#8594;') + '</button>' +
    '</div>' +
    '<div class="tutorial-progress">Step ' + phasePos + ' of ' + phaseTotal + '</div>';

  document.body.appendChild(el);
  _tooltipEl = el;

  // Positioning must happen after the element is in the DOM (so offsetHeight works).
  _positionTooltip(el, target);
}

function _positionTooltip(tooltip, target) {
  var MARGIN = 16;

  if (!target) {
    // No target — centre on screen (welcome card or hidden-element fallback)
    tooltip.style.top  = '50%';
    tooltip.style.left = '50%';
    tooltip.style.transform = 'translate(-50%, -50%)';
    return;
  }

  var rect = target.getBoundingClientRect();
  var tw   = tooltip.offsetWidth  || 320;
  var th   = tooltip.offsetHeight || 200;
  var vw   = window.innerWidth;
  var vh   = window.innerHeight;

  var spaceBelow = vh - rect.bottom;
  var spaceAbove = rect.top;

  var top;
  if (spaceBelow >= th + MARGIN || spaceBelow >= spaceAbove) {
    top = rect.bottom + MARGIN;
    tooltip.dataset.arrow = 'up';
  } else {
    top = rect.top - th - MARGIN;
    tooltip.dataset.arrow = 'down';
  }

  // Horizontal: left-align with target, clamped to viewport
  var left = rect.left;
  if (left + tw > vw - MARGIN) left = vw - tw - MARGIN;
  if (left < MARGIN) left = MARGIN;

  // Vertical clamp — ensures tooltip stays within viewport even when the
  // target is near an edge or the viewport is very short
  if (top + th > vh - MARGIN) top = vh - th - MARGIN;
  if (top < MARGIN) top = MARGIN;

  tooltip.style.top       = top  + 'px';
  tooltip.style.left      = left + 'px';
  tooltip.style.transform = 'none';
}

function _removeTooltip() {
  if (_tooltipEl) {
    _tooltipEl.remove();
    _tooltipEl = null;
  }
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

function _tutorialNext() {
  var nextIndex = _step + 1;

  if (nextIndex < TUTORIAL_STEPS.length) {
    var nextStep    = TUTORIAL_STEPS[nextIndex];
    var nextTarget  = _resolveTarget(nextStep);
    var nextVisible = nextTarget && _isVisible(nextTarget);

    var crossesPhase  = nextStep.phase !== TUTORIAL_STEPS[_step].phase;
    // Also pause when the next step declares a selector whose element isn't
    // visible yet — an external hook (e.g. tutorialAdvanceToManualCritique)
    // resumes the tutorial once the user triggers the relevant UI action.
    var awaitsTrigger = nextStep.selector && !nextVisible;

    if (crossesPhase || awaitsTrigger) {
      _clearSpotlight();
      _removeTooltip();
      // If the target is already visible (e.g. #debugPanel appeared before
      // the user clicked "Finish ✓"), advance immediately rather than waiting
      // for a hook that will never fire.
      if (nextVisible) {
        _showStep(nextIndex);
      }
      return;         // _active stays true; localStorage NOT marked done
    }
  }

  _showStep(nextIndex);
}

function _tutorialPrev() {
  _showStep(_step - 1);
}

function _tutorialSkip() {
  _endTutorial();
}

// ---------------------------------------------------------------------------
// End / cleanup
// ---------------------------------------------------------------------------

function _endTutorial() {
  _clearSpotlight();
  _removeTooltip();
  _active = false;
  localStorage.setItem('paixueji_tutorial_done', '1');
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _firstIndexOfPhase(phase) {
  for (var i = 0; i < TUTORIAL_STEPS.length; i++) {
    if (TUTORIAL_STEPS[i].phase === phase) return i;
  }
  return -1;
}

// ---------------------------------------------------------------------------
// Auto-start on page load
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', function () {
  if (!localStorage.getItem('paixueji_tutorial_done')) {
    startTutorial('setup');
  }
});
