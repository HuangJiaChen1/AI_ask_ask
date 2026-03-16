/**
 * Paixueji Assistant - Streaming Chat Client
 *
 * This file handles:
 * - SSE (Server-Sent Events) streaming from the backend
 * - Real-time text display using StreamChunk format
 * - Session management
 * - User input handling
 * - Category selection and progress tracking
 */

// Automatically use the same host as the frontend (works for localhost, server, and ngrok)
const API_BASE = `${window.location.protocol}//${window.location.host}/api`;

// Global state
let sessionId = null;
let currentMessageDiv = null;
let isStreaming = false;
let currentStreamController = null;
let correctAnswerCount = 0;
let conversationComplete = false;
let detectedObject = null;  // For manual topic switch override
let awaitingObjectSelection = false;  // Waiting for object choice flag

// UI state
let currentObject = null;  // Current object being discussed
let guidePhase = null;  // Guide phase (active, success, hint, exit)
let guideTurnCount = 0;  // Current turn in guide mode
let currentThemeName = null;  // IB PYP theme name
let currentKeyConcept = null;  // Key concept for theme
let currentIntentType = null;       // Last classified intent (9-node architecture)
let currentResponseType = null;     // Last response node that actually ran

// DOM elements
const messagesContainer = document.getElementById('messages');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const startForm = document.getElementById('startForm');
const progressIndicator = document.getElementById('progressIndicator');
const thinkingTimeDisplay = document.getElementById('thinking-time');

/**
 * Add a message to the chat interface
 * @param {string} role - 'assistant' or 'user'
 * @param {string} initialText - Initial text to display (optional)
 * @param {boolean|null} isCorrect - Feedback status (true=correct, false=encouraging, null=none)
 * @returns {HTMLElement} The message bubble element
 */
function addMessage(role, initialText = '', isCorrect = null) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    // Add feedback indicator for assistant messages
    if (role === 'assistant' && isCorrect !== null) {
        const feedbackBadge = document.createElement('span');
        feedbackBadge.className = `feedback-badge ${isCorrect ? 'correct' : 'encouraging'}`;
        feedbackBadge.textContent = isCorrect ? '✅ ' : '🤔 ';
        bubble.appendChild(feedbackBadge);
    }

    bubble.appendChild(document.createTextNode(initialText));

    messageDiv.appendChild(bubble);
    messagesContainer.appendChild(messageDiv);

    // Auto-scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return bubble;
}

/**
 * Display text chunk immediately (no artificial delay)
 * The streaming itself provides the real-time effect!
 * @param {HTMLElement} element - The element to add text to
 * @param {string} text - The text to display
 */
function displayChunk(element, text) {
    // Check if element has a feedback badge as first child
    const hasFeedbackBadge = element.firstChild && element.firstChild.classList &&
                             element.firstChild.classList.contains('feedback-badge');

    if (hasFeedbackBadge) {
        // Append to text node after the badge
        const textNode = element.lastChild;
        if (textNode && textNode.nodeType === Node.TEXT_NODE) {
            textNode.textContent += text;
        } else {
            element.appendChild(document.createTextNode(text));
        }
    } else {
        // No badge, just append text normally
        element.textContent += text;
    }

    // Auto-scroll as text appears
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

/**
 * Start a new conversation
 */
async function startConversation() {
    const age = parseInt(document.getElementById('age').value);
    const objectName = document.getElementById('objectName').value.trim();
    // Save state for debug panel
    currentObject = objectName;

    // Validation - only object name is required
    if (!objectName) {
        alert('Please enter an object name');
        return;
    }

    // Read backbone model overrides
    const conversationModel = document.querySelector('input[name="conversationModel"]:checked')?.value || 'gemini-3.1-flash-lite-preview';
    const groundingModel = document.querySelector('input[name="groundingModel"]:checked')?.value || 'gemini-3.1-flash-lite-preview';

    // Clear previous messages
    messagesContainer.innerHTML = '';
    sessionId = null;
    thinkingTimeDisplay.textContent = '';
    thinkingTimeDisplay.style.opacity = 0;
    currentThemeName = null;
    currentKeyConcept = null;

    // Reset progress
    correctAnswerCount = 0;
    conversationComplete = false;
    updateProgressIndicator();

    // Hide start form, show progress indicator and messages
    startForm.style.display = 'none';
    progressIndicator.style.display = 'flex';
    messagesContainer.style.display = 'flex';
    document.querySelector('.input-area').style.display = 'flex';
    document.getElementById('backBtn').style.display = 'inline-block';

    // Tutorial hook — advance from setup steps to chat steps
    if (window.tutorialAdvanceToChat) window.tutorialAdvanceToChat();

    // Disable send button during streaming
    sendBtn.disabled = true;
    isStreaming = true;
    updateStopButton();

    try {
        console.log('[INFO] Starting Paixueji conversation | age:', age, 'object:', objectName);

        // Create AbortController for this stream
        currentStreamController = new AbortController();

        const response = await fetch(`${API_BASE}/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                age: age,
                object_name: objectName,
                model_name_override: conversationModel,
                grounding_model_override: groundingModel
            }),
            signal: currentStreamController.signal
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        // Create message bubble for streaming response (will be created on first chunk)
        currentMessageDiv = null;

        // Read streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();

            if (done) {
                console.log('[INFO] Stream ended');
                break;
            }

            // Decode chunk and add to buffer
            buffer += decoder.decode(value, { stream: true });

            // Process complete SSE events (separated by \n\n)
            const lines = buffer.split('\n\n');
            buffer = lines.pop(); // Keep incomplete event in buffer

            for (const line of lines) {
                if (!line.trim()) continue;

                // Parse SSE event
                const eventMatch = line.match(/^event: (.+)$/m);
                const dataMatch = line.match(/^data: (.+)$/m);

                if (eventMatch && dataMatch) {
                    const eventType = eventMatch[1];
                    const data = JSON.parse(dataMatch[1]);

                    // Handle event
                    await handleSSEEvent(eventType, data);
                }
            }
        }

    } catch (error) {
        // Handle abort gracefully
        if (error.name === 'AbortError') {
            console.log('[INFO] Stream interrupted by user');
            return;
        }

        console.error('[ERROR] Failed to start conversation:', error);
        messagesContainer.innerHTML = '';
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = `Error: ${error.message}. Please check if the server is running.`;
        messagesContainer.appendChild(errorDiv);
    } finally {
        // Clear stream controller
        currentStreamController = null;

        // Show debug panel when session starts
        if (sessionId) {
            document.getElementById('debugPanel').style.display = 'block';
            if (window.tutorialAdvanceToReport) window.tutorialAdvanceToReport();
            updateDebugPanel();
        }

        // Re-enable send button
        isStreaming = false;
        sendBtn.disabled = false;
        updateStopButton();
        userInput.focus();
    }
}

/**
 * Stop the current streaming response
 */
function stopStreaming() {
    console.log('[INFO] Stopping stream (frontend only)...');

    // Abort frontend connection - old stream will finish in background
    if (currentStreamController) {
        currentStreamController.abort();
        currentStreamController = null;
    }

    // Reset UI state
    isStreaming = false;
    sendBtn.disabled = false;
    updateStopButton();
    userInput.focus();
}

/**
 * Update stop button visibility based on streaming state
 */
function updateStopButton() {
    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) {
        stopBtn.style.display = isStreaming ? 'inline-block' : 'none';
    }
}

/**
 * Send a user message
 */
async function sendMessage() {
    const text = userInput.value.trim();

    // Validate input
    if (!text || !sessionId) {
        return;
    }

    // Interrupt ongoing stream if exists (abort frontend connection only)
    if (isStreaming && currentStreamController) {
        console.log('[INFO] Interrupting previous stream');
        currentStreamController.abort();
        currentStreamController = null;
    }

    // Clear thinking time display
    thinkingTimeDisplay.textContent = '';
    thinkingTimeDisplay.style.opacity = 0;

    // Add user message to chat
    addMessage('user', text);
    userInput.value = '';

    // Disable send button during streaming
    sendBtn.disabled = true;
    isStreaming = true;
    updateStopButton();

    try {
        console.log('[INFO] Sending message:', text);

        // Create AbortController for this stream
        currentStreamController = new AbortController();

        const response = await fetch(`${API_BASE}/continue`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: sessionId,
                child_input: text
            }),
            signal: currentStreamController.signal
        });

        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('Session not found. Please start a new conversation.');
            }
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        // Create message bubble for streaming response (will be created on first chunk)
        currentMessageDiv = null;

        // Read streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();

            if (done) {
                console.log('[INFO] Stream ended');
                break;
            }

            // Decode chunk and add to buffer
            buffer += decoder.decode(value, { stream: true });

            // Process complete SSE events
            const lines = buffer.split('\n\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.trim()) continue;

                // Parse SSE event
                const eventMatch = line.match(/^event: (.+)$/m);
                const dataMatch = line.match(/^data: (.+)$/m);

                if (eventMatch && dataMatch) {
                    const eventType = eventMatch[1];
                    const data = JSON.parse(dataMatch[1]);

                    // Handle event
                    await handleSSEEvent(eventType, data);
                }
            }
        }

    } catch (error) {
        // Handle abort gracefully
        if (error.name === 'AbortError') {
            console.log('[INFO] Stream interrupted by user');
            return;
        }

        console.error('[ERROR] Failed to send message:', error);
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = `Error: ${error.message}`;
        messagesContainer.appendChild(errorDiv);
    } finally {
        // Clear stream controller
        currentStreamController = null;

        // Re-enable send button
        isStreaming = false;
        sendBtn.disabled = false;
        updateStopButton();
        userInput.focus();
    }
}

/**
 * Handle SSE events from the server
 * @param {string} eventType - The type of event
 * @param {object} data - The event data (StreamChunk object for 'chunk' events)
 */
async function handleSSEEvent(eventType, data) {
    console.log(`[${eventType}]`, data);

    switch (eventType) {
        case 'chunk':
            // Handle StreamChunk object
            handleStreamChunk(data);
            break;

        case 'complete':
            // Stream completed successfully
            console.log('[INFO] Stream complete:', data);
            break;

        case 'interrupted':
            // Stream was interrupted
            console.log('[INFO] Stream interrupted:', data);
            // Could add visual indicator here if needed
            break;

        case 'error':
            // Error occurred during streaming
            console.error('[ERROR] Stream error:', data);
            if (currentMessageDiv) {
                currentMessageDiv.textContent = '⚠ Error: ' + (data.message || 'An error occurred');
                currentMessageDiv.style.color = '#d32f2f';
            }
            break;

        default:
            console.warn('[WARNING] Unknown event type:', eventType);
    }
}

/**
 * Handle a StreamChunk object
 * @param {object} chunk - The StreamChunk object
 */
function handleStreamChunk(chunk) {
    // Store session ID from first chunk
    if (chunk.session_id && !sessionId) {
        sessionId = chunk.session_id;
        console.log('[INFO] Session ID:', sessionId);
    }

    // Update progress tracking
    if (chunk.correct_answer_count !== undefined) {
        correctAnswerCount = chunk.correct_answer_count;
        updateProgressIndicator();
    }

    // INFINITE MODE: No conversation completion logic
    // Conversation continues indefinitely

    // Display TTFT as soon as any chunk carries a duration (first content chunk)
    if (chunk.duration > 0) {
        thinkingTimeDisplay.textContent = `${chunk.duration.toFixed(1)}s`;
        thinkingTimeDisplay.style.opacity = 1;
    }

    // Handle text chunks (non-finish chunks with response text)
    if (!chunk.finish && chunk.response) {
        if (!currentMessageDiv) {
            // Create message with feedback indicator on first chunk
            const isCorrect = chunk.is_correct !== undefined ? chunk.is_correct : null;
            currentMessageDiv = addMessage('assistant', '', isCorrect);
        }
        displayChunk(currentMessageDiv, chunk.response);
    }

    // Handle final chunk (finish=true)
    if (chunk.finish) {
        // Only update if final response is longer (prevents cutoffs from incomplete final chunks)
        if (currentMessageDiv && chunk.response) {
            // Get current text (accounting for feedback badge)
            const hasFeedbackBadge = currentMessageDiv.firstChild &&
                                    currentMessageDiv.firstChild.classList &&
                                    currentMessageDiv.firstChild.classList.contains('feedback-badge');

            const currentText = hasFeedbackBadge ?
                                (currentMessageDiv.lastChild ? currentMessageDiv.lastChild.textContent : '') :
                                currentMessageDiv.textContent;

            if (chunk.response.length > currentText.length) {
                // Final chunk has more text, use it (preserve badge)
                if (hasFeedbackBadge) {
                    const textNode = currentMessageDiv.lastChild;
                    if (textNode && textNode.nodeType === Node.TEXT_NODE) {
                        textNode.textContent = chunk.response;
                    }
                } else {
                    currentMessageDiv.textContent = chunk.response;
                }
            } else if (chunk.response.length < currentText.length) {
                // Final chunk is shorter - log warning but keep current text
                console.warn('[WARNING] Final chunk shorter than streamed text. Keeping streamed version.', {
                    streamedLength: currentText.length,
                    finalLength: chunk.response.length
                });
            }
            // If equal length, keep what we have (no action needed)
        }
    }

    // Object selection uses natural language instead of UI buttons
    // User reads suggested objects in AI response text and types their choice as next message
    // (Removed showObjectSelection call - no longer using UI panel)

    // Handle detected object (AI decided to CONTINUE but detected a new object)
    if (chunk.detected_object_name) {
        detectedObject = chunk.detected_object_name;
        document.getElementById('detectedObjectName').textContent = detectedObject;
        document.getElementById('switchToObjectName').textContent = detectedObject;
        document.getElementById('switchReasoning').textContent = '';
        document.getElementById('manualSwitchPanel').style.display = 'block';
        console.log('[INFO] Object detected but not switching:', detectedObject);
    }

    // Update current object if it changed (from switching)
    if (chunk.current_object_name && chunk.current_object_name !== currentObject) {
        currentObject = chunk.current_object_name;
        updateDebugPanel();
        console.log('[INFO] Object switched to:', currentObject);
    }

    // Update theme classification if present
    if (chunk.ibpyp_theme_name) {
        currentThemeName = chunk.ibpyp_theme_name;
    }
    if (chunk.key_concept) {
        currentKeyConcept = chunk.key_concept;
    }
    if (chunk.ibpyp_theme_name || chunk.key_concept) {
        updateDebugPanel();
    }

    // Update guide mode state if present
    if (chunk.guide_phase !== undefined) {
        guidePhase = chunk.guide_phase;
    }
    if (chunk.guide_turn_count !== undefined) {
        guideTurnCount = chunk.guide_turn_count;
    }
    // Update debug panel when guide state changes
    if (chunk.guide_phase || chunk.guide_turn_count) {
        updateDebugPanel();
    }

    // Update intent type (9-node architecture)
    if (chunk.intent_type) {
        currentIntentType = chunk.intent_type;
        updateDebugPanel();
    }

    // Update response type (which node actually ran — may differ from intent_type via routing intercept)
    if (chunk.response_type) {
        currentResponseType = chunk.response_type;
        updateDebugPanel();
    }

    // Chat phase complete: show modal and disable input after close
    if (chunk.chat_phase_complete) {
        showChatPhaseCompleteModal();
    }
}

/**
 * Update progress indicator
 */
function updateProgressIndicator() {
    document.getElementById('progressText').textContent =
        `Correct answers: ${correctAnswerCount}/4`;

    const percentage = (correctAnswerCount / 4) * 100;
    document.getElementById('progressFill').style.width = percentage + '%';

    // Also update debug panel
    updateDebugPanel();
}

/**
 * Update debug panel with current session state
 */
function updateDebugPanel() {
    // Update session ID
    const sessionIdElement = document.getElementById('debugSessionId');
    if (sessionIdElement) {
        sessionIdElement.textContent = sessionId || '-';
    }

    // Update current object
    const objectElement = document.getElementById('debugCurrentObject');
    if (objectElement) {
        objectElement.textContent = currentObject || '-';
    }

    // Update correct answers count
    const correctCountElement = document.getElementById('debugCorrectCount');
    if (correctCountElement) {
        correctCountElement.textContent = `${correctAnswerCount}/4`;
    }

    // Update theme name
    const themeNameElement = document.getElementById('debugThemeName');
    if (themeNameElement) {
        themeNameElement.textContent = currentThemeName || '-';
    }

    // Update key concept
    const keyConceptElement = document.getElementById('debugKeyConcept');
    if (keyConceptElement) {
        keyConceptElement.textContent = currentKeyConcept || '-';
    }

    // Update guide phase
    const guidePhaseElement = document.getElementById('debugGuidePhase');
    if (guidePhaseElement) {
        guidePhaseElement.textContent = guidePhase || '-';
        // Color code the phase
        if (guidePhase === 'active') {
            guidePhaseElement.style.color = '#f59e0b';  // Amber
        } else if (guidePhase === 'success') {
            guidePhaseElement.style.color = '#10b981';  // Green
        } else if (guidePhase === 'exit') {
            guidePhaseElement.style.color = '#ef4444';  // Red
        }
    }

    // Update guide turn count
    const guideTurnElement = document.getElementById('debugGuideTurn');
    if (guideTurnElement) {
        guideTurnElement.textContent = guideTurnCount > 0 ? `${guideTurnCount}/6` : '-';
    }

    // Update last intent type
    const intentElement = document.getElementById('debugIntentType');
    if (intentElement) {
        intentElement.textContent = currentIntentType || '-';
        const intentColors = {
            'curiosity':   '#8b5cf6',   // Purple  — exploratory question
            'clarifying':  '#f59e0b',   // Amber   — uncertain/wrong guess
            'informative': '#3b82f6',   // Blue    — sharing knowledge
            'play':        '#ec4899',   // Pink    — silly/imaginative
            'emotional':   '#14b8a6',   // Teal    — expressing feeling
            'avoidance':   '#6b7280',   // Gray    — refusing/exiting
            'boundary':    '#ef4444',   // Red     — risky action
            'action':      '#10b981',   // Green   — issuing command
            'social':      '#f97316',   // Orange  — asking about AI
        };
        intentElement.style.color = currentIntentType
            ? (intentColors[currentIntentType.toLowerCase()] || '#374151')
            : '#6b7280';
    }

    // Update response type display
    const responseTypeEl = document.getElementById('debugResponseType');
    if (responseTypeEl) {
        responseTypeEl.textContent = currentResponseType || '-';
    }
}

/**
 * Show the "chat phase complete" modal (4th correct answer reached)
 */
function showChatPhaseCompleteModal() {
    const modal = document.getElementById('chatPhaseCompleteModal');
    modal.style.display = 'flex';
}

function closeChatPhaseCompleteModal() {
    document.getElementById('chatPhaseCompleteModal').style.display = 'none';
    document.getElementById('userInput').disabled = true;
    document.getElementById('sendBtn').disabled = true;
}

/**
 * Show completion UI
 */
function showCompletionUI() {
    // Disable input
    userInput.disabled = true;
    sendBtn.disabled = true;

    // Add restart button
    const inputArea = document.querySelector('.input-area');
    const restartBtn = document.createElement('button');
    restartBtn.className = 'restart-btn';
    restartBtn.textContent = 'Start New Conversation';
    restartBtn.onclick = resetConversation;
    restartBtn.style.marginLeft = '10px';
    inputArea.appendChild(restartBtn);

    console.log('[INFO] Completion UI shown');
}

/**
 * Navigate back to setup form, with a guard if AI is mid-stream
 */
function goBack() {
    if (isStreaming) {
        if (!confirm('The AI is still responding. Go back anyway?')) return;
        currentStreamController?.abort();
    }
    resetConversation();
}

/**
 * Reset conversation
 */
function resetConversation() {
    // Clear state
    sessionId = null;
    correctAnswerCount = 0;
    conversationComplete = false;

    // Clear messages
    messagesContainer.innerHTML = '';

    // Show start form again, hide messages and progress
    startForm.style.display = 'block';
    progressIndicator.style.display = 'none';
    messagesContainer.style.display = 'none';
    document.getElementById('backBtn').style.display = 'none';

    // Re-enable input
    userInput.disabled = false;
    userInput.value = '';
    sendBtn.disabled = false;

    // Remove restart button
    const restartBtn = document.querySelector('.restart-btn');
    if (restartBtn) {
        restartBtn.remove();
    }

    console.log('[INFO] Conversation reset');
}

/**
 * Initialize the application
 */
function init() {
    console.log('[INFO] Paixueji Streaming Chat initialized');

    // Show empty state
    if (messagesContainer.children.length === 0) {
        const emptyState = document.createElement('div');
        emptyState.className = 'empty-state';
        emptyState.innerHTML = `
            <p>👋 Welcome to Paixueji!</p>
            <small>Choose an object from the dropdown, then click "Start Learning!" to begin</small>
        `;
        messagesContainer.appendChild(emptyState);
    }

    loadObjects();
}

/**
 * Fetch supported objects from the backend and populate the dropdown.
 */
async function loadObjects() {
    const select = document.getElementById('objectName');
    try {
        const res = await fetch(`${API_BASE}/objects`);
        const objects = await res.json();

        // Group by domain
        const byDomain = {};
        for (const obj of objects) {
            if (!byDomain[obj.domain]) byDomain[obj.domain] = { label: obj.domain_label, items: [] };
            byDomain[obj.domain].items.push(obj);
        }

        select.innerHTML = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.disabled = true;
        placeholder.selected = true;
        placeholder.textContent = 'Choose an object…';
        select.appendChild(placeholder);

        for (const { label, items } of Object.values(byDomain)) {
            const group = document.createElement('optgroup');
            group.label = label;
            for (const item of items) {
                const opt = document.createElement('option');
                opt.value = item.name.toLowerCase();
                opt.textContent = item.name;
                group.appendChild(opt);
            }
            select.appendChild(group);
        }
    } catch (e) {
        select.innerHTML = '<option value="" disabled selected>Failed to load objects</option>';
        console.error('[ERROR] Failed to load objects:', e);
    }
}

/**
 * Force a manual topic switch to the detected object
 */
async function forceSwitch() {
    if (!detectedObject || !sessionId) {
        console.error('[ERROR] Cannot force switch: missing detectedObject or sessionId');
        return;
    }

    try {
        console.log('[INFO] Forcing switch to:', detectedObject);

        const response = await fetch(`${API_BASE}/force-switch`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: sessionId,
                new_object: detectedObject
            })
        });

        const result = await response.json();

        if (result.success) {
            console.log('[INFO] Switch successful:', result);

            // Update current object for debug panel
            currentObject = result.new_object;
            updateDebugPanel();

            // Add system message to chat
            const systemMsg = addMessage('system', `✨ Switched to ${result.new_object}!`);
            systemMsg.style.background = '#d1fae5';
            systemMsg.style.borderLeft = '4px solid #10b981';
            systemMsg.style.padding = '10px';
            systemMsg.style.margin = '10px 0';

            // Update input placeholder
            userInput.placeholder = `Tell me about ${result.new_object}...`;
        } else {
            console.error('[ERROR] Force switch failed:', result.error);
            alert(`Failed to switch: ${result.error}`);
        }

        dismissSwitchPanel();

    } catch (error) {
        console.error('[ERROR] Force switch error:', error);
        alert('Failed to switch topics. Please try again.');
    }
}

/**
 * Dismiss the manual switch panel
 */
function dismissSwitchPanel() {
    document.getElementById('manualSwitchPanel').style.display = 'none';
    detectedObject = null;
    console.log('[INFO] Manual switch panel dismissed');
}

// ============================================================================
// REMOVED: Object Selection UI Functions (showObjectSelection, selectObject)
// ============================================================================
// Object selection now uses natural language instead of UI buttons:
// - AI suggests objects in response text (e.g., "Would you like to learn about cats, dogs, or trees?")
// - User types their choice as a regular message
// - Validation detects the SWITCH and processes it through /api/continue
// ============================================================================

// ============================================================================
// Critique Report Functions
// ============================================================================

/**
 * Show the critique choice modal (AI vs Manual).
 */
function showCritiqueChoice() {
    if (!sessionId) {
        alert('No active session');
        return;
    }
    const modal = document.getElementById('critiqueChoiceModal');
    modal.style.display = 'flex';
}

/**
 * Close the critique choice modal.
 */
function closeCritiqueChoice() {
    document.getElementById('critiqueChoiceModal').style.display = 'none';
}

/**
 * Send AI critique and poll for results.
 */
async function sendAICritique() {
    closeCritiqueChoice();

    const btn = document.getElementById('sendReportBtn');
    btn.disabled = true;
    btn.textContent = 'Analyzing...';

    // Reset status section
    const statusSection = document.getElementById('aiCritiqueStatus');
    const statusText = document.getElementById('aiCritiqueStatusText');
    document.getElementById('aiCritiqueOptimizeButtons').innerHTML = '';
    statusSection.style.background = '#f1f5f9';
    statusText.textContent = '⏳ AI critique in progress...';
    statusSection.style.display = 'block';

    try {
        const response = await fetch(`${API_BASE}/critique`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ session_id: sessionId })
        });
        const result = await response.json();

        if (result.success) {
            _pollAICritiqueStatus(result.task_id);
        } else {
            btn.disabled = false;
            btn.textContent = '📝 Send Report for Review';
            statusSection.style.background = '#fee2e2';
            statusText.textContent = '✗ Failed: ' + result.error;
        }
    } catch (e) {
        btn.disabled = false;
        btn.textContent = '📝 Send Report for Review';
        statusSection.style.background = '#fee2e2';
        statusText.textContent = '✗ Error: ' + e.message;
    }
}

/**
 * Poll /api/critique/status/<taskId> every 3s and render results when done.
 */
function _pollAICritiqueStatus(taskId) {
    const btn = document.getElementById('sendReportBtn');
    const statusSection = document.getElementById('aiCritiqueStatus');
    const statusText = document.getElementById('aiCritiqueStatusText');
    const optimizeButtons = document.getElementById('aiCritiqueOptimizeButtons');

    const interval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/critique/status/${taskId}`);
            const data = await response.json();

            if (data.status === 'completed') {
                clearInterval(interval);
                btn.disabled = false;
                btn.textContent = '📝 Send Report for Review';

                if (data.traces && data.traces.length > 0) {
                    statusSection.style.background = '#fef3c7';
                    statusText.textContent =
                        `⚠ ${data.traces.length} exchange(s) flagged — optimize their prompts:`;
                    data.traces.forEach(trace => {
                        if (!trace.culprit_name || trace.culprit_name === 'unknown') return;
                        const optBtn = document.createElement('button');
                        optBtn.textContent = 'Optimize: ' + trace.culprit_name;
                        optBtn.style.cssText =
                            'width:100%; margin-top:8px; padding:8px; background:#3b82f6; ' +
                            'color:white; border:none; border-radius:6px; cursor:pointer; ' +
                            'font-weight:bold; font-size:0.85em;';
                        optBtn.onclick = () => runOptimization(
                            trace.culprit_name,
                            trace.prompt_template_name,
                            trace.trace_id
                        );
                        optimizeButtons.appendChild(optBtn);
                    });
                } else {
                    statusSection.style.background = '#d1fae5';
                    statusText.textContent = '✓ No issues found in this session.';
                }

            } else if (data.status === 'failed') {
                clearInterval(interval);
                btn.disabled = false;
                btn.textContent = '📝 Send Report for Review';
                statusSection.style.background = '#fee2e2';
                statusText.textContent = '✗ Critique failed: ' + (data.error || 'unknown error');
            }
            // status === 'pending' | 'running' → keep polling

        } catch (e) {
            clearInterval(interval);
            btn.disabled = false;
            btn.textContent = '📝 Send Report for Review';
            statusSection.style.background = '#fee2e2';
            statusText.textContent = '✗ Polling error: ' + e.message;
        }
    }, 3000);
}

/**
 * Fetch exchanges and show the manual critique form.
 */
async function showManualCritiqueForm() {
    closeCritiqueChoice();

    try {
        const response = await fetch(`${API_BASE}/exchanges/${sessionId}`);
        const result = await response.json();

        if (!result.success) {
            alert('Failed to load exchanges: ' + result.error);
            return;
        }

        if (result.exchanges.length === 0) {
            alert('No complete exchanges found. Need at least one model→child→model triplet.');
            return;
        }

        // Populate the exchange list, grouped by phase
        const exchangeList = document.getElementById('exchangeList');
        exchangeList.innerHTML = '';

        // Session info banner
        function buildCategoryLabel(r) {
            const parts = [r.level1_category, r.level2_category, r.level3_category].filter(Boolean);
            return parts.length ? parts.join(' › ') : null;
        }

        const sessionBanner = document.createElement('div');
        sessionBanner.style.cssText = 'background:#f1f5f9; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; margin-bottom:18px; display:flex; flex-wrap:wrap; gap:10px; align-items:center;';

        const bannerFields = [
            { label: 'Object', value: result.object_name },
            { label: 'Category', value: buildCategoryLabel(result) },
            { label: 'Theme', value: result.ibpyp_theme_name },
            { label: 'Key Concept', value: result.key_concept },
            { label: 'Age', value: result.age ? `${result.age} y/o` : null },
        ];

        bannerFields.forEach(({ label, value }) => {
            if (!value) return;
            const chip = document.createElement('span');
            chip.style.cssText = 'background:#fff; border:1px solid #cbd5e1; border-radius:8px; padding:4px 10px; font-size:0.8em; color:#334155; white-space:nowrap;';
            chip.innerHTML = `<span style="color:#94a3b8; font-weight:600; margin-right:4px;">${label}:</span>${escapeHtml(value)}`;
            sessionBanner.appendChild(chip);
        });

        exchangeList.appendChild(sessionBanner);

        // Split exchanges into chat and guide groups
        const chatExchanges = result.exchanges.filter(e => (e.mode || 'chat') !== 'guide');
        const guideExchanges = result.exchanges.filter(e => (e.mode || 'chat') === 'guide');

        // Helper: render a single exchange card
        function renderExchangeCard(exchange) {
            const wrapper = document.createElement('div');
            wrapper.style.cssText = 'margin-bottom:16px; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;';

            // Mode badge colors
            const mode = exchange.mode || 'chat';
            const badgeColor = mode === 'guide' ? '#7c3aed' : '#0891b2';
            const badgeLabel = mode.toUpperCase();

            // Intent badge color groups
            const intentColors = {
                CORRECT_ANSWER: '#16a34a',
                CURIOSITY: '#0891b2', INFORMATIVE: '#0891b2',
                CLARIFYING_IDK: '#d97706', CLARIFYING_WRONG: '#d97706', CLARIFYING_CONSTRAINT: '#d97706',
                PLAY: '#7c3aed', EMOTIONAL: '#7c3aed',
                SOCIAL: '#64748b', SOCIAL_ACKNOWLEDGMENT: '#64748b',
                AVOIDANCE: '#dc2626', BOUNDARY: '#dc2626', ACTION: '#dc2626',
            };
            const intentColor = intentColors[exchange.intent_type] || '#94a3b8';
            const intentBadge = exchange.intent_type
                ? `<span style="display:inline-block; background:${intentColor}; color:#fff; font-size:0.65em; font-weight:600; padding:1px 7px; border-radius:9px; margin-left:5px; vertical-align:middle;">${exchange.intent_type}</span>`
                : '';

            // Response time label
            const timeLabel = exchange.response_time_ms
                ? `<span style="font-size:0.75em; color:#94a3b8; margin-left:8px; vertical-align:middle;">${(exchange.response_time_ms / 1000).toFixed(1)}s</span>`
                : '';

            const header = document.createElement('div');
            header.style.cssText = 'padding:12px; background:#f8fafc; display:flex; align-items:flex-start; gap:10px; cursor:pointer;';
            header.innerHTML = `
                <input type="checkbox" id="exchange_cb_${exchange.index}" data-index="${exchange.index}" style="margin-top:3px; cursor:pointer;" onchange="toggleExchangeCritique(${exchange.index})">
                <div style="flex:1; min-width:0;">
                    <strong style="color:#1e293b;">Exchange ${exchange.index}</strong>
                    <span style="display:inline-block; background:${badgeColor}; color:#fff; font-size:0.7em; font-weight:600; padding:1px 7px; border-radius:9px; margin-left:6px; vertical-align:middle;">${badgeLabel}</span>${intentBadge}${timeLabel}
                    <div style="font-size:0.85em; color:#64748b; margin-top:4px;">
                        <div><b>Q:</b> ${escapeHtml(truncate(exchange.model_question, 80))}</div>
                        <div><b>A:</b> ${escapeHtml(truncate(exchange.child_response, 80))}</div>
                        <div><b>R:</b> ${escapeHtml(truncate(exchange.model_response, 80))}</div>
                    </div>
                </div>
            `;
            header.onclick = function(e) {
                if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
                    const cb = document.getElementById('exchange_cb_' + exchange.index);
                    cb.checked = !cb.checked;
                    toggleExchangeCritique(exchange.index);
                }
            };

            const formDiv = document.createElement('div');
            formDiv.id = `exchange_form_${exchange.index}`;
            formDiv.style.cssText = 'display:none; padding:16px; border-top:1px solid #e2e8f0;';
            formDiv.innerHTML = buildExchangeCritiqueFormHTML(exchange);

            wrapper.appendChild(header);
            wrapper.appendChild(formDiv);
            return wrapper;
        }

        // Chat Phase section
        if (chatExchanges.length > 0) {
            const chatHeader = document.createElement('div');
            chatHeader.style.cssText = 'background:#e0f2fe; padding:10px 14px; border-radius:8px; margin-bottom:12px; font-weight:600; color:#0c4a6e;';
            chatHeader.innerHTML = `Chat Phase <span style="font-weight:400; font-size:0.85em; color:#0369a1;">(${chatExchanges.length} exchange${chatExchanges.length !== 1 ? 's' : ''} &mdash; exploratory Q&A)</span>`;
            exchangeList.appendChild(chatHeader);
            chatExchanges.forEach(ex => exchangeList.appendChild(renderExchangeCard(ex)));
        }

        // Guide Phase section
        if (guideExchanges.length > 0) {
            const guideHeader = document.createElement('div');
            guideHeader.style.cssText = 'background:#ede9fe; padding:10px 14px; border-radius:8px; margin-bottom:12px; margin-top:16px; font-weight:600; color:#4c1d95;';
            const conceptText = result.key_concept ? ` &mdash; Key Concept: <em>${escapeHtml(result.key_concept)}</em>` : '';
            guideHeader.innerHTML = `Guide Phase <span style="font-weight:400; font-size:0.85em; color:#5b21b6;">(${guideExchanges.length} exchange${guideExchanges.length !== 1 ? 's' : ''}${conceptText})</span>`;
            exchangeList.appendChild(guideHeader);
            guideExchanges.forEach(ex => exchangeList.appendChild(renderExchangeCard(ex)));
        }

        // Clear global conclusion
        document.getElementById('globalConclusion').value = '';

        // Show overlay
        document.getElementById('manualCritiqueOverlay').style.display = 'block';
        if (window.tutorialAdvanceToManualCritique) window.tutorialAdvanceToManualCritique();

    } catch (e) {
        console.error('[ERROR] Failed to load exchanges:', e);
        alert('Failed to load exchanges: ' + e.message);
    }
}

/**
 * Build HTML for a single exchange critique form.
 */
function buildExchangeCritiqueFormHTML(exchange) {
    const idx = exchange.index;
    return `
        <div style="margin-bottom:16px;">
            <div style="font-weight:bold; color:#475569; margin-bottom:6px;">Model Question</div>
            <div style="background:#f0f9ff; padding:8px; border-radius:4px; font-size:0.9em; margin-bottom:8px; white-space:pre-wrap;">${escapeHtml(exchange.model_question)}</div>
            <div style="display:flex; gap:8px;">
                <div style="flex:1;"><label style="font-size:0.8em; color:#64748b;">What is expected</label><textarea id="mq_exp_${idx}" rows="2" style="width:100%; box-sizing:border-box; padding:6px; border:1px solid #cbd5e1; border-radius:4px; font-family:inherit; resize:vertical;" placeholder="What should the model have asked?"></textarea></div>
                <div style="flex:1;"><label style="font-size:0.8em; color:#64748b;">Why is it problematic</label><textarea id="mq_prob_${idx}" rows="2" style="width:100%; box-sizing:border-box; padding:6px; border:1px solid #cbd5e1; border-radius:4px; font-family:inherit; resize:vertical;" placeholder="What's wrong with this question?"></textarea></div>
            </div>
        </div>
        <div style="margin-bottom:16px;">
            <div style="font-weight:bold; color:#475569; margin-bottom:6px;">Child Response</div>
            <div style="background:#fefce8; padding:8px; border-radius:4px; font-size:0.9em; margin-bottom:4px; white-space:pre-wrap;">${escapeHtml(exchange.child_response)}</div>
            <div style="font-size:0.78em; color:#64748b; margin-bottom:8px; display:flex; gap:12px;">
                ${exchange.intent_type ? `<span>Intent: <strong>${exchange.intent_type}</strong></span>` : ''}
                ${exchange.response_time_ms ? `<span>Response time: <strong>${(exchange.response_time_ms/1000).toFixed(1)}s</strong></span>` : ''}
            </div>
        </div>
        <div style="margin-bottom:16px;">
            <div style="font-weight:bold; color:#475569; margin-bottom:6px;">Model Response</div>
            <div style="background:#f0fdf4; padding:8px; border-radius:4px; font-size:0.9em; margin-bottom:8px; white-space:pre-wrap;">${escapeHtml(exchange.model_response)}</div>
            <div style="display:flex; gap:8px;">
                <div style="flex:1;"><label style="font-size:0.8em; color:#64748b;">What is expected</label><textarea id="mr_exp_${idx}" rows="2" style="width:100%; box-sizing:border-box; padding:6px; border:1px solid #cbd5e1; border-radius:4px; font-family:inherit; resize:vertical;" placeholder="How should the model have responded?"></textarea></div>
                <div style="flex:1;"><label style="font-size:0.8em; color:#64748b;">Why is it problematic</label><textarea id="mr_prob_${idx}" rows="2" style="width:100%; box-sizing:border-box; padding:6px; border:1px solid #cbd5e1; border-radius:4px; font-family:inherit; resize:vertical;" placeholder="What's wrong with this response?"></textarea></div>
            </div>
        </div>
        <div>
            <label style="font-weight:bold; color:#475569; font-size:0.9em;">Exchange Conclusion</label>
            <textarea id="ec_concl_${idx}" rows="2" style="width:100%; box-sizing:border-box; padding:6px; border:1px solid #cbd5e1; border-radius:4px; font-family:inherit; resize:vertical; margin-top:4px;" placeholder="Summary of issues in this exchange..."></textarea>
        </div>
    `;
}

/**
 * Toggle visibility of an exchange critique form when checkbox changes.
 */
function toggleExchangeCritique(index) {
    const cb = document.getElementById('exchange_cb_' + index);
    const form = document.getElementById('exchange_form_' + index);
    if (cb && form) {
        form.style.display = cb.checked ? 'block' : 'none';
        if (!cb.checked) {
            ['mq_exp_', 'mq_prob_', 'mr_exp_', 'mr_prob_', 'ec_concl_'].forEach(prefix => {
                const el = document.getElementById(prefix + index);
                if (el) el.value = '';
            });
        }
    }
}

/**
 * Close and reset the manual critique form.
 */
function closeManualCritique() {
    document.getElementById('manualCritiqueOverlay').style.display = 'none';
}

/**
 * Collect all checked exchanges from the critique form.
 * Returns null (and shows an alert) if none are checked.
 */
function collectExchangeCritiques() {
    const exchangeCritiques = [];
    const checkboxes = document.querySelectorAll('[id^="exchange_cb_"]');

    checkboxes.forEach(cb => {
        if (!cb.checked) return;
        const idx = parseInt(cb.dataset.index);

        exchangeCritiques.push({
            exchange_index: idx,
            model_question_expected: (document.getElementById('mq_exp_' + idx) || {}).value || '',
            model_question_problem: (document.getElementById('mq_prob_' + idx) || {}).value || '',
            model_response_expected: (document.getElementById('mr_exp_' + idx) || {}).value || '',
            model_response_problem: (document.getElementById('mr_prob_' + idx) || {}).value || '',
            conclusion: (document.getElementById('ec_concl_' + idx) || {}).value || ''
        });
    });

    if (exchangeCritiques.length === 0) {
        alert('Please select at least one exchange to critique.');
        return null;
    }
    return exchangeCritiques;
}

/**
 * Save the critique report only — returns immediately without trace/culprit analysis.
 */
async function submitManualCritiqueToDatabase() {
    const exchangeCritiques = collectExchangeCritiques();
    if (!exchangeCritiques) return;

    const globalConclusion = document.getElementById('globalConclusion').value;
    const submitBtn = document.getElementById('submitReportDbBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving...';

    try {
        const response = await fetch(`${API_BASE}/manual-critique`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: sessionId,
                exchange_critiques: exchangeCritiques,
                global_conclusion: globalConclusion,
                skip_traces: true
            })
        });

        const result = await response.json();

        if (result.success) {
            console.log('[INFO] Manual critique saved to:', result.report_path);
            console.log('[INFO] Exchanges critiqued:', result.exchanges_critiqued);
            const btn = document.getElementById('sendReportBtn');
            btn.textContent = 'Report Saved!';
            btn.style.background = '#10b981';
            setTimeout(() => {
                btn.textContent = '\uD83D\uDCDD Send Report for Review';
                btn.style.background = '#f59e0b';
            }, 4000);
            closeManualCritique();
        } else {
            alert('Failed to save critique: ' + result.error);
        }
    } catch (e) {
        console.error('[ERROR] Manual critique (DB only) failed:', e);
        alert('Failed to submit critique: ' + e.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit to Report Database';
    }
}

/**
 * Save the critique report AND run trace assembly + LLM culprit identification
 * for the evolving-agent optimization flow.
 */
async function submitManualCritiqueWithEvolution() {
    const exchangeCritiques = collectExchangeCritiques();
    if (!exchangeCritiques) return;

    const globalConclusion = document.getElementById('globalConclusion').value;
    const submitBtn = document.getElementById('submitEvolvingAgentBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting...';

    try {
        const response = await fetch(`${API_BASE}/manual-critique`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: sessionId,
                exchange_critiques: exchangeCritiques,
                global_conclusion: globalConclusion
            })
        });

        const result = await response.json();

        if (result.success) {
            const btn = document.getElementById('sendReportBtn');
            btn.textContent = 'Report Saved!';
            btn.style.background = '#10b981';
            console.log('[INFO] Manual critique saved to:', result.report_path);
            console.log('[INFO] Exchanges critiqued:', result.exchanges_critiqued);
            setTimeout(() => {
                btn.textContent = '\uD83D\uDCDD Send Report for Review';
                btn.style.background = '#f59e0b';
            }, 4000);

            // Show optimization suggestions if any culprits were identified
            if (result.traces && result.traces.length > 0) {
                showOptimizationPrompts(result.traces);
            } else {
                closeManualCritique();
            }
        } else {
            alert('Failed to save critique: ' + result.error);
        }
    } catch (e) {
        console.error('[ERROR] Manual critique failed:', e);
        alert('Failed to submit critique: ' + e.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit for Evolving Agent';
    }
}

/**
 * Truncate text to a maximum length with ellipsis.
 */
function truncate(text, maxLen) {
    if (!text) return '';
    return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
}

/**
 * Escape HTML entities to prevent XSS.
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

// ============================================================================
// Prompt Optimization Flow
// ============================================================================

/**
 * Show "Optimize prompt" buttons for each trace culprit returned by
 * /api/manual-critique. Buttons appear inside the critique overlay so the
 * engineer can immediately trigger optimization without closing the form.
 */
function showOptimizationPrompts(traces) {
    const container = document.getElementById('optimizationSuggestions');
    container.innerHTML = '';
    container.style.display = 'block';

    const heading = document.createElement('p');
    heading.style.cssText = 'font-weight:bold; color:#1e293b; margin:0 0 8px 0; font-size:0.9em;';
    heading.textContent = 'Culprits identified — optimize their prompts:';
    container.appendChild(heading);

    traces.forEach(trace => {
        if (!trace.culprit_name || trace.culprit_name === 'unknown') return;
        const btn = document.createElement('button');
        btn.textContent = 'Optimize prompt for: ' + trace.culprit_name;
        btn.style.cssText = 'width:100%; margin-top:8px; padding:10px; background:#3b82f6; ' +
            'color:white; border:none; border-radius:6px; cursor:pointer; font-weight:bold; font-size:0.9em;';
        btn.onclick = () => runOptimization(
            trace.culprit_name,
            trace.prompt_template_name,  // may be null — backend will error with helpful message
            trace.trace_id               // single-trace mode: only this evidence used
        );
        container.appendChild(btn);
    });
}

/** Tracks the optimization_id returned by /api/optimize-prompt. */
let currentOptimizationId = null;

/**
 * Compute a line-level diff between two strings.
 * Returns { beforeHtml, afterHtml } with changed lines highlighted.
 */
function computePromptDiff(oldText, newText) {
    function esc(s) {
        return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    const oldLines = oldText.split('\n');
    const newLines = newText.split('\n');

    // Build LCS table (line level)
    const m = oldLines.length, n = newLines.length;
    const dp = Array.from({length: m + 1}, () => new Array(n + 1).fill(0));
    for (let i = m - 1; i >= 0; i--) {
        for (let j = n - 1; j >= 0; j--) {
            if (oldLines[i] === newLines[j]) {
                dp[i][j] = 1 + dp[i+1][j+1];
            } else {
                dp[i][j] = Math.max(dp[i+1][j], dp[i][j+1]);
            }
        }
    }

    // Walk the LCS to build diff
    let beforeHtml = '', afterHtml = '';
    let i = 0, j = 0;
    while (i < m || j < n) {
        if (i < m && j < n && oldLines[i] === newLines[j]) {
            // Unchanged
            beforeHtml += esc(oldLines[i]) + '\n';
            afterHtml  += esc(newLines[j]) + '\n';
            i++; j++;
        } else if (j < n && (i >= m || dp[i][j+1] >= dp[i+1][j])) {
            // Added in new
            afterHtml += `<span style="background:#86efac; display:inline-block; width:100%;">${esc(newLines[j])}</span>\n`;
            j++;
        } else {
            // Removed from old
            beforeHtml += `<span style="background:#fca5a5; display:inline-block; width:100%;">${esc(oldLines[i])}</span>\n`;
            i++;
        }
    }
    return { beforeHtml, afterHtml };
}

/**
 * Render side-by-side preview cards into #optPreviewContainer.
 * Each card shows Exchange N label, original (red) vs fixed preview (green).
 * Falls back to a single card with fallbackText when previews is empty.
 */
function renderPreviewCards(previews, fallbackText) {
    const container = document.getElementById('optPreviewContainer');
    container.innerHTML = '';

    const items = (previews && previews.length > 0) ? previews : [{
        exchange_index: '?', culprit_phase: null, original: '', preview: fallbackText || ''
    }];

    items.forEach(item => {
        const label = document.createElement('div');
        const phaseTag = item.culprit_phase ? ` · ${item.culprit_phase}` : '';
        label.textContent = `Exchange ${item.exchange_index}${phaseTag}`;
        label.style.cssText = 'font-weight:bold; color:#374151; margin-bottom:6px; font-size:0.85em;';

        const row = document.createElement('div');
        row.style.cssText = 'display:grid; grid-template-columns:1fr 1fr; gap:8px;';

        const origLabel = document.createElement('div');
        origLabel.textContent = 'Original (bad)';
        origLabel.style.cssText = 'font-size:0.75em; color:#dc2626; font-weight:bold; margin-bottom:4px;';

        const origBox = document.createElement('div');
        origBox.style.cssText = 'background:#fef2f2; border:1px solid #fca5a5; border-radius:6px; padding:10px; font-size:0.9em; white-space:pre-wrap; line-height:1.5;';
        origBox.textContent = item.original || '(no original stored)';

        const origCol = document.createElement('div');
        origCol.appendChild(origLabel);
        origCol.appendChild(origBox);

        const previewLabel = document.createElement('div');
        previewLabel.textContent = 'Fixed preview';
        previewLabel.style.cssText = 'font-size:0.75em; color:#16a34a; font-weight:bold; margin-bottom:4px;';

        const previewBox = document.createElement('div');
        previewBox.style.cssText = 'background:#f0fdf4; border:1px solid #86efac; border-radius:6px; padding:10px; font-size:0.9em; white-space:pre-wrap; line-height:1.5;';
        previewBox.textContent = item.preview;

        const previewCol = document.createElement('div');
        previewCol.appendChild(previewLabel);
        previewCol.appendChild(previewBox);

        row.appendChild(origCol);
        row.appendChild(previewCol);

        const card = document.createElement('div');
        card.style.cssText = 'border:1px solid #e2e8f0; border-radius:8px; padding:12px; background:#fafafa;';
        card.appendChild(label);
        card.appendChild(row);
        container.appendChild(card);
    });
}

/**
 * Call /api/optimize-prompt, then show the result modal for human review.
 */
async function runOptimization(culpritName, promptName, traceId) {
    const modal = document.getElementById('optimizationModal');
    modal.style.display = 'block';

    // Reset modal to loading state
    document.getElementById('optPreviewContainer').innerHTML =
        '<div style="color:#64748b; padding:12px;">Generating optimization\u2026 (this may take 15\u201330s)</div>';
    document.getElementById('optOriginalPrompt').textContent = '';
    document.getElementById('optOptimizedPrompt').textContent = '';
    document.getElementById('optFailurePattern').textContent = '';
    document.getElementById('optRationale').textContent = '';
    document.getElementById('approveOptBtn').disabled = true;
    _renderRouterPatch(null);

    try {
        const response = await fetch(`${API_BASE}/optimize-prompt`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({culprit_name: culpritName, prompt_name: promptName, trace_id: traceId})
        });
        const result = await response.json();

        if (!response.ok) {
            document.getElementById('optPreviewContainer').innerHTML =
                `<div style="color:#dc2626; padding:12px;">Error: ${result.error || response.statusText}</div>`;
            return;
        }

        currentOptimizationId = result.optimization_id;

        document.getElementById('optFailurePattern').textContent =
            'Failure pattern: ' + result.failure_pattern;
        const diff = computePromptDiff(result.original_prompt, result.optimized_prompt);
        document.getElementById('optOriginalPrompt').innerHTML = diff.beforeHtml;
        document.getElementById('optOptimizedPrompt').innerHTML = diff.afterHtml;
        renderPreviewCards(result.previews, result.preview_response);
        document.getElementById('optRationale').textContent = result.rationale;
        document.getElementById('approveOptBtn').disabled = false;

        // Show routing table patch section if present
        _renderRouterPatch(result.router_patch);

    } catch (e) {
        document.getElementById('optPreviewContainer').innerHTML =
            `<div style="color:#dc2626; padding:12px;">Request failed: ${e.message}</div>`;
    }
}

/**
 * Render the router_patch table in the modal (or hide it if null).
 */
function _renderRouterPatch(routerPatch) {
    const section = document.getElementById('optRouterPatchSection');
    const tbody = document.getElementById('optRouterPatchRows');
    if (!routerPatch) {
        section.style.display = 'none';
        tbody.innerHTML = '';
        return;
    }
    tbody.innerHTML = '';
    const stratRoutes = routerPatch.navigator_strategy_routes || {};
    const entries = Object.entries(stratRoutes);
    if (entries.length === 0) {
        section.style.display = 'none';
        return;
    }
    entries.forEach(([strategy, node]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="padding:6px 10px; font-family:monospace; color:#6d28d9;">${strategy}</td>
            <td style="padding:6px 10px; font-family:monospace; color:#15803d;">${node}</td>
        `;
        tbody.appendChild(tr);
    });
    section.style.display = 'block';
}

/**
 * Approve the current optimization — merges prompt into prompt_overrides.json.
 */
async function approveOptimization() {
    if (!currentOptimizationId) return;
    const btn = document.getElementById('approveOptBtn');
    btn.disabled = true;
    btn.textContent = 'Applying\u2026';

    try {
        const response = await fetch(
            `${API_BASE}/optimize-prompt/${currentOptimizationId}/approve`,
            {method: 'POST'}
        );
        const result = await response.json();

        if (result.status === 'approved') {
            closeOptimizationModal();
            alert('Prompt optimization applied. New sessions will use the updated prompt.');
        } else {
            alert('Failed to approve: ' + JSON.stringify(result));
            btn.disabled = false;
            btn.textContent = 'Approve \u2014 Apply this fix';
        }
    } catch (e) {
        alert('Approval request failed: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Approve \u2014 Apply this fix';
    }
}

/**
 * Show feedback textarea when the engineer clicks "Reject — Not good enough".
 */
function showRejectionFeedback() {
    document.getElementById('optActionButtons').style.display = 'none';
    document.getElementById('optRejectionSection').style.display = 'block';
    document.getElementById('optRejectionReason').value = '';
    document.getElementById('optRejectionReason').focus();
}

/**
 * Submit rejection feedback and call /refine to get a better attempt.
 */
async function submitRejectionAndRetry() {
    const reason = document.getElementById('optRejectionReason').value.trim();
    if (!reason) {
        alert('Please explain why the fix is not satisfying before retrying.');
        return;
    }

    const previousId = currentOptimizationId;

    // Transition modal back to loading state
    document.getElementById('optRejectionSection').style.display = 'none';
    document.getElementById('optActionButtons').style.display = 'flex';
    document.getElementById('optPreviewContainer').innerHTML =
        '<div style="color:#64748b; padding:12px;">Refining based on your feedback\u2026 (this may take 15\u201330s)</div>';
    document.getElementById('optOriginalPrompt').textContent = '';
    document.getElementById('optOptimizedPrompt').textContent = '';
    document.getElementById('optFailurePattern').textContent = '';
    document.getElementById('optRationale').textContent = '';
    document.getElementById('approveOptBtn').disabled = true;

    try {
        const response = await fetch(`${API_BASE}/optimize-prompt/${previousId}/refine`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({rejection_reason: reason})
        });
        const result = await response.json();

        if (!response.ok) {
            document.getElementById('optPreviewContainer').innerHTML =
                `<div style="color:#dc2626; padding:12px;">Error: ${result.error || response.statusText}</div>`;
            document.getElementById('approveOptBtn').disabled = false;
            return;
        }

        // Update modal with refined result
        currentOptimizationId = result.optimization_id;
        document.getElementById('optFailurePattern').textContent =
            'Failure pattern: ' + result.failure_pattern;
        const diff = computePromptDiff(result.original_prompt, result.optimized_prompt);
        document.getElementById('optOriginalPrompt').innerHTML = diff.beforeHtml;
        document.getElementById('optOptimizedPrompt').innerHTML = diff.afterHtml;
        renderPreviewCards(result.previews, result.preview_response);
        document.getElementById('optRationale').textContent = result.rationale;
        document.getElementById('approveOptBtn').disabled = false;
        _renderRouterPatch(result.router_patch);

    } catch (e) {
        document.getElementById('optPreviewContainer').innerHTML =
            `<div style="color:#dc2626; padding:12px;">Request failed: ${e.message}</div>`;
        document.getElementById('approveOptBtn').disabled = false;
    }
}

/**
 * Hard discard — deletes the pending file and closes the modal.
 */
async function discardOptimization() {
    if (currentOptimizationId) {
        await fetch(
            `${API_BASE}/optimize-prompt/${currentOptimizationId}/reject`,
            {method: 'POST'}
        ).catch(() => {});
    }
    closeOptimizationModal();
}

function closeOptimizationModal() {
    document.getElementById('optimizationModal').style.display = 'none';
    // Reset rejection section for next use
    document.getElementById('optRejectionSection').style.display = 'none';
    document.getElementById('optActionButtons').style.display = 'flex';
    document.getElementById('optRejectionReason').value = '';
    currentOptimizationId = null;
    // Reset approve button label for next use
    const btn = document.getElementById('approveOptBtn');
    if (btn) {
        btn.disabled = false;
        btn.textContent = 'Approve \u2014 Apply this fix';
    }
}

// Initialize on page load
init();
