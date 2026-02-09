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
let categoryData = {};
let detectedObject = null;  // For manual topic switch override
let systemManagedMode = false;  // System-managed focus mode flag
let awaitingObjectSelection = false;  // Waiting for object choice flag

// Bug tracking state for restore → auto-replay → approval flow
let buggyResponse = null;
let newResponse = null;
let contextMessage = null;
let buggyResponseIndex = null;
let isRestoredSession = false;
let currentObject = null;  // Current object being discussed
let currentCharacter = null;  // Current character
let currentFocusMode = null;  // Current focus mode
let guidePhase = null;  // Guide phase (active, success, hint, exit)
let guideTurnCount = 0;  // Current turn in guide mode

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
 * @param {string} focus - Focus mode used (optional)
 * @param {boolean|null} isCorrect - Feedback status (true=correct, false=encouraging, null=none)
 * @returns {HTMLElement} The message bubble element
 */
function addMessage(role, initialText = '', focus = null, isCorrect = null) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    if (focus) {
        const focusTag = document.createElement('span');
        focusTag.className = 'focus-tag';
        focusTag.textContent = formatFocusName(focus);
        messageDiv.appendChild(focusTag);
    }

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
 * Format focus name for display (e.g., "width_color" -> "Width: Color")
 */
function formatFocusName(focus) {
    if (!focus) return '';
    return focus.split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(': ');
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
    const level1Category = document.getElementById('level1Category').value;
    const level2Category = document.getElementById('level2Category').value;
    const level3Category = document.getElementById('level3Category').value;
    const character = document.getElementById('assistantCharacter').value;
    const focusMode = document.getElementById('nextQuestionFocus').value;
    systemManagedMode = (focusMode === 'system_managed');

    // Save state for debug panel
    currentObject = objectName;
    currentCharacter = character;
    currentFocusMode = focusMode;

    // Save character preference
    localStorage.setItem('paixueji_character', character);

    // Set active focus mode dropdown to match start selection
    const activeFocusSelect = document.getElementById('activeFocusMode');
    if (activeFocusSelect) {
        activeFocusSelect.value = focusMode;

        // If in system_managed mode, disable the entire dropdown
        if (systemManagedMode) {
            activeFocusSelect.disabled = true;
        } else {
            // In manual mode, disable the "System Managed" option
            const systemOption = activeFocusSelect.querySelector('option[value="system_managed"]');
            if (systemOption) {
                systemOption.disabled = true;
            }

            // Add event listener to disable system_managed if user switches away from it
            activeFocusSelect.onchange = function() {
                if (this.value !== 'system_managed') {
                    const systemOption = this.querySelector('option[value="system_managed"]');
                    if (systemOption) {
                        systemOption.disabled = true;
                    }
                    console.log('[INFO] Switched to manual mode, system_managed disabled');
                }
            };
        }

        // Show the control
        const controlDiv = document.getElementById('activeFocusControl');
        if (controlDiv) {
            controlDiv.style.display = 'flex';
        }
    }

    // Validation - only object name is required
    if (!objectName) {
        alert('Please enter an object name');
        return;
    }

    // Convert "none" to null
    const level1Value = (level1Category && level1Category !== 'none') ? level1Category : null;
    const level2Value = (level2Category && level2Category !== 'none') ? level2Category : null;
    const level3Value = (level3Category && level3Category !== 'none') ? level3Category : null;

    // Clear previous messages
    messagesContainer.innerHTML = '';
    sessionId = null;
    thinkingTimeDisplay.textContent = '';
    thinkingTimeDisplay.style.opacity = 0;

    // Reset progress
    correctAnswerCount = 0;
    conversationComplete = false;
    updateProgressIndicator();

    // Hide start form, show progress indicator and messages
    startForm.style.display = 'none';
    progressIndicator.style.display = 'flex';
    messagesContainer.style.display = 'flex';
    document.querySelector('.input-area').style.display = 'flex';

    // Disable send button during streaming
    sendBtn.disabled = true;
    isStreaming = true;
    updateStopButton();

    try {
        console.log('[INFO] Starting Paixueji conversation | age:', age, 'object:', objectName,
                    'level1:', level1Value, 'level2:', level2Value, 'level3:', level3Value);

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
                level1_category: level1Value,
                level2_category: level2Value,
                level3_category: level3Value,
                character: character,
                focus_mode: focusMode,
                system_managed: systemManagedMode
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
 * Start a direct guide mode test - skips introduction and enters guide phase immediately.
 */
async function startGuideTest() {
    const age = parseInt(document.getElementById('age').value);
    const objectName = document.getElementById('objectName').value.trim();
    const character = document.getElementById('assistantCharacter').value;

    // Save state for debug panel
    currentObject = objectName;
    currentCharacter = character;
    currentFocusMode = 'depth';  // Guide mode always uses depth

    // Validation - only object name is required
    if (!objectName) {
        alert('Please enter an object name');
        return;
    }

    // Clear previous messages
    messagesContainer.innerHTML = '';
    sessionId = null;
    thinkingTimeDisplay.textContent = '';
    thinkingTimeDisplay.style.opacity = 0;

    // Set progress to 4 (simulating 4 correct answers)
    correctAnswerCount = 4;
    conversationComplete = false;
    systemManagedMode = false;
    updateProgressIndicator();

    // Hide start form, show progress indicator and messages
    startForm.style.display = 'none';
    progressIndicator.style.display = 'flex';
    messagesContainer.style.display = 'flex';
    document.querySelector('.input-area').style.display = 'flex';

    // Hide active focus control in guide mode
    const activeFocusControl = document.getElementById('activeFocusControl');
    if (activeFocusControl) {
        activeFocusControl.style.display = 'none';
    }

    // Disable send button during streaming
    sendBtn.disabled = true;
    isStreaming = true;
    updateStopButton();

    // Add status message
    const statusDiv = document.createElement('div');
    statusDiv.className = 'status-message';
    statusDiv.style.cssText = 'background: #fef3c7; padding: 10px; border-radius: 6px; margin-bottom: 10px; color: #92400e; font-style: italic;';
    statusDiv.textContent = 'Running theme classification...';
    messagesContainer.appendChild(statusDiv);

    try {
        console.log('[INFO] Starting GUIDE TEST | age:', age, 'object:', objectName, 'character:', character);

        // Create AbortController for this stream
        currentStreamController = new AbortController();

        const response = await fetch(`${API_BASE}/start-guide`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                age: age,
                object_name: objectName,
                character: character
            }),
            signal: currentStreamController.signal
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        // Remove status message once streaming starts
        statusDiv.remove();

        // Create message bubble for streaming response (will be created on first chunk)
        currentMessageDiv = null;

        // Read streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();

            if (done) {
                console.log('[INFO] Guide test stream ended');
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
            console.log('[INFO] Guide test stream interrupted by user');
            return;
        }

        console.error('[ERROR] Failed to start guide test:', error);
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

    // Get focus mode from active dropdown (allows mid-chat switching)
    const activeFocusSelect = document.getElementById('activeFocusMode');
    const focusMode = activeFocusSelect ? activeFocusSelect.value : document.getElementById('nextQuestionFocus').value;

    // Update current focus mode for debug panel
    currentFocusMode = focusMode;
    updateDebugPanel();

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
                child_input: text,
                focus_mode: focusMode
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

            // If this is a restored session, track the new response and show approval buttons
            if (isRestoredSession && currentMessageDiv) {
                newResponse = currentMessageDiv.textContent;
                showApprovalButtons();
            }
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

    // Handle text chunks (non-finish chunks with response text)
    if (!chunk.finish && chunk.response) {
        if (!currentMessageDiv) {
            // Create message with feedback indicator on first chunk
            const isCorrect = chunk.is_correct !== undefined ? chunk.is_correct : null;
            // Use system_focus_mode if in system-managed mode, otherwise use focus_mode
            const displayFocus = chunk.system_focus_mode || chunk.focus_mode;
            currentMessageDiv = addMessage('assistant', '', displayFocus, isCorrect);
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

        // Display duration and token usage if available
        if (chunk.duration) {
            console.log(`[INFO] Response duration: ${chunk.duration.toFixed(2)}s`);
            thinkingTimeDisplay.textContent = `Response time: ${chunk.duration.toFixed(2)}s`;
            thinkingTimeDisplay.style.opacity = 1;
        }

        if (chunk.token_usage) {
            console.log('[INFO] Token usage:', chunk.token_usage);
        }

        // Show save button after first response completes
        if (sessionId) {
            const saveBtn = document.getElementById('saveStateBtn');
            if (saveBtn) {
                saveBtn.style.display = 'inline-block';
            }
        }

        // INFINITE MODE: No completion UI - conversation never ends
    }

    // Object selection uses natural language instead of UI buttons
    // User reads suggested objects in AI response text and types their choice as next message
    // (Removed showObjectSelection call - no longer using UI panel)

    // Handle detected object (AI decided to CONTINUE but detected a new object)
    if (chunk.detected_object_name && chunk.switch_decision_reasoning) {
        detectedObject = chunk.detected_object_name;
        document.getElementById('detectedObjectName').textContent = detectedObject;
        document.getElementById('switchToObjectName').textContent = detectedObject;
        document.getElementById('switchReasoning').textContent = chunk.switch_decision_reasoning;
        document.getElementById('manualSwitchPanel').style.display = 'block';
        console.log('[INFO] Object detected but not switching:', detectedObject, '| Reasoning:', chunk.switch_decision_reasoning);
    }

    // Update current object if it changed (from switching)
    if (chunk.current_object_name && chunk.current_object_name !== currentObject) {
        currentObject = chunk.current_object_name;
        updateDebugPanel();
        console.log('[INFO] Object switched to:', currentObject);
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
}

/**
 * Load category data from object_prompts.json
 */
async function loadCategoryData() {
    try {
        const response = await fetch('/static/object_prompts.json');
        categoryData = await response.json();
        populateLevel1Dropdown();
        console.log('[INFO] Category data loaded');
    } catch (error) {
        console.error('[ERROR] Failed to load category data:', error);
    }
}

/**
 * Populate Level 1 category dropdown
 */
function populateLevel1Dropdown() {
    const level1Select = document.getElementById('level1Category');
    const level1Categories = Object.keys(categoryData.level1_categories || {});

    level1Select.innerHTML = '<option value="">Select...</option>';

    // Add "None of the Above" option
    const noneOption = document.createElement('option');
    noneOption.value = 'none';
    noneOption.textContent = 'None of the Above';
    level1Select.appendChild(noneOption);

    // Add level1 categories
    level1Categories.forEach(cat => {
        const option = document.createElement('option');
        option.value = cat;
        option.textContent = formatCategoryName(cat);
        level1Select.appendChild(option);
    });
}

/**
 * Handle Level 1 category change - populate Level 2 dropdown
 */
function onLevel1Change() {
    const level1 = document.getElementById('level1Category').value;
    const level2Select = document.getElementById('level2Category');
    const level3Select = document.getElementById('level3Category');

    // Reset level3 dropdown
    level3Select.disabled = true;
    level3Select.innerHTML = '<option value="">Select...</option>';

    if (!level1 || level1 === 'none') {
        level2Select.disabled = true;
        level2Select.innerHTML = '<option value="">Select...</option>';
        return;
    }

    // Find all level2 categories with this parent
    const level2Categories = Object.entries(categoryData.level2_categories || {})
        .filter(([key, val]) => val.parent === level1)
        .map(([key, val]) => key);

    level2Select.disabled = false;
    level2Select.innerHTML = '<option value="">Select...</option>';

    // Add "None of the Above" option
    const noneOption = document.createElement('option');
    noneOption.value = 'none';
    noneOption.textContent = 'None of the Above';
    level2Select.appendChild(noneOption);

    // Add level2 categories
    level2Categories.forEach(cat => {
        const option = document.createElement('option');
        option.value = cat;
        option.textContent = formatCategoryName(cat);
        level2Select.appendChild(option);
    });
}

/**
 * Handle Level 2 category change - populate Level 3 dropdown
 */
function onLevel2Change() {
    const level2 = document.getElementById('level2Category').value;
    const level3Select = document.getElementById('level3Category');

    if (!level2 || level2 === 'none') {
        level3Select.disabled = true;
        level3Select.innerHTML = '<option value="">Select...</option>';
        return;
    }

    // Find all level3 categories with this parent
    const level3Categories = Object.entries(categoryData.level3_categories || {})
        .filter(([key, val]) => val.parent === level2)
        .map(([key, val]) => key);

    level3Select.disabled = false;
    level3Select.innerHTML = '<option value="">Select...</option>';

    // Add "None of the Above" option
    const noneOption = document.createElement('option');
    noneOption.value = 'none';
    noneOption.textContent = 'None of the Above';
    level3Select.appendChild(noneOption);

    // Add level3 categories
    level3Categories.forEach(cat => {
        const option = document.createElement('option');
        option.value = cat;
        option.textContent = formatCategoryName(cat);
        level3Select.appendChild(option);
    });
}

/**
 * Classify an object and auto-populate category dropdowns
 */
async function classifyObject() {
    const objectName = document.getElementById('objectName').value.trim();
    const classifyBtn = document.getElementById('classifyBtn');
    const classifyStatus = document.getElementById('classifyStatus');

    if (!objectName) {
        classifyStatus.className = 'classify-status error';
        classifyStatus.textContent = 'Please enter an object name first';
        return;
    }

    // Disable button and show loading
    classifyBtn.disabled = true;
    classifyStatus.className = 'classify-status loading';
    classifyStatus.textContent = 'Classifying...';

    try {
        const response = await fetch(`${API_BASE}/classify`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                object_name: objectName
            })
        });

        const result = await response.json();

        if (!result.success) {
            throw new Error(result.error || 'Classification failed');
        }

        const { level1_category, level2_category } = result;

        // Update dropdowns
        const level1Select = document.getElementById('level1Category');
        const level2Select = document.getElementById('level2Category');

        if (level2_category === 'none') {
            // No match found - select "None of the Above"
            level1Select.value = 'none';
            level2Select.disabled = true;
            level2Select.innerHTML = '<option value="">Select...</option>';

            classifyStatus.className = 'classify-status success';
            classifyStatus.textContent = `"${objectName}" doesn't match our categories. Selected "None of the Above"`;
        } else {
            // Match found - update both dropdowns
            level1Select.value = level1_category;

            // Trigger level1 change to populate level2
            onLevel1Change();

            // Set level2 value
            level2Select.value = level2_category;

            classifyStatus.className = 'classify-status success';
            classifyStatus.textContent = `✓ Classified as: ${formatCategoryName(level2_category)} (${formatCategoryName(level1_category)})`;
        }

    } catch (error) {
        console.error('Classification error:', error);
        classifyStatus.className = 'classify-status error';
        classifyStatus.textContent = `Error: ${error.message}`;
    } finally {
        classifyBtn.disabled = false;
    }
}

/**
 * Format category name for display (e.g., "fresh_ingredients" → "Fresh Ingredients")
 */
function formatCategoryName(name) {
    return name.split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
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

    // Update character
    const characterElement = document.getElementById('debugCharacter');
    if (characterElement) {
        characterElement.textContent = currentCharacter ? formatCategoryName(currentCharacter) : '-';
    }

    // Update focus mode
    const focusElement = document.getElementById('debugFocusMode');
    if (focusElement) {
        focusElement.textContent = currentFocusMode ? formatFocusName(currentFocusMode) : '-';
    }

    // Update system managed status
    const systemManagedElement = document.getElementById('debugSystemManaged');
    if (systemManagedElement) {
        systemManagedElement.textContent = systemManagedMode ? 'Yes' : 'No';
    }

    // Update correct answers count
    const correctCountElement = document.getElementById('debugCorrectCount');
    if (correctCountElement) {
        correctCountElement.textContent = `${correctAnswerCount}/4`;
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

    // Hide active focus control
    const activeFocusControl = document.getElementById('activeFocusControl');
    if (activeFocusControl) {
        activeFocusControl.style.display = 'none';
    }

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
 * Save focus preference to localStorage
 */
function saveFocusPreference() {
    const focusMode = document.getElementById('nextQuestionFocus').value;
    localStorage.setItem('paixueji_focus', focusMode);
}

/**
 * Initialize the application
 */
function init() {
    console.log('[INFO] Paixueji Streaming Chat initialized');

    // Load category data
    loadCategoryData();

    // Load saved character preference
    const savedCharacter = localStorage.getItem('paixueji_character');
    if (savedCharacter) {
        const characterSelect = document.getElementById('assistantCharacter');
        if (characterSelect) {
            characterSelect.value = savedCharacter;
        }
    }

    // Load saved focus preference
    const savedFocus = localStorage.getItem('paixueji_focus');
    if (savedFocus) {
        const focusSelect = document.getElementById('nextQuestionFocus');
        if (focusSelect) {
            focusSelect.value = savedFocus;
        }
    }

    // Show empty state
    if (messagesContainer.children.length === 0) {
        const emptyState = document.createElement('div');
        emptyState.className = 'empty-state';
        emptyState.innerHTML = `
            <p>👋 Welcome to Paixueji!</p>
            <small>Enter an object name, click "Classify" to auto-categorize, then "Start Learning!" to begin</small>
        `;
        messagesContainer.appendChild(emptyState);
    }

    // Clear classification status when user types in object name
    const objectNameInput = document.getElementById('objectName');
    const classifyStatus = document.getElementById('classifyStatus');
    if (objectNameInput && classifyStatus) {
        objectNameInput.addEventListener('input', () => {
            classifyStatus.className = 'classify-status';
            classifyStatus.textContent = '';
        });
    }

    // Focus on object name input
    document.getElementById('objectName').focus();
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
 * Send AI critique (existing automated flow).
 */
async function sendAICritique() {
    closeCritiqueChoice();

    const btn = document.getElementById('sendReportBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Analyzing...';

    try {
        const response = await fetch(`${API_BASE}/critique`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ session_id: sessionId })
        });
        const result = await response.json();

        if (result.success) {
            btn.textContent = 'Report Saved!';
            btn.style.background = '#10b981';
            console.log('[INFO] AI report saved to:', result.report_path);
        } else {
            btn.textContent = 'Error';
            btn.style.background = '#ef4444';
            console.error('[ERROR] Critique failed:', result.error);
            alert('Failed to generate report: ' + result.error);
        }
    } catch (e) {
        btn.textContent = 'Error';
        btn.style.background = '#ef4444';
        console.error('[ERROR] Critique request failed:', e);
        alert('Failed to send report: ' + e.message);
    }

    setTimeout(() => {
        btn.disabled = false;
        btn.textContent = originalText;
        btn.style.background = '#f59e0b';
    }, 2000);
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

        // Populate the exchange list
        const exchangeList = document.getElementById('exchangeList');
        exchangeList.innerHTML = '';

        result.exchanges.forEach(exchange => {
            const wrapper = document.createElement('div');
            wrapper.style.cssText = 'margin-bottom:16px; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;';

            // Checkbox header with preview
            const header = document.createElement('div');
            header.style.cssText = 'padding:12px; background:#f8fafc; display:flex; align-items:flex-start; gap:10px; cursor:pointer;';
            header.innerHTML = `
                <input type="checkbox" id="exchange_cb_${exchange.index}" data-index="${exchange.index}" style="margin-top:3px; cursor:pointer;" onchange="toggleExchangeCritique(${exchange.index})">
                <div style="flex:1; min-width:0;">
                    <strong style="color:#1e293b;">Exchange ${exchange.index}</strong>
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

            // Collapsible critique form (hidden by default)
            const formDiv = document.createElement('div');
            formDiv.id = `exchange_form_${exchange.index}`;
            formDiv.style.cssText = 'display:none; padding:16px; border-top:1px solid #e2e8f0;';
            formDiv.innerHTML = buildExchangeCritiqueFormHTML(exchange);

            wrapper.appendChild(header);
            wrapper.appendChild(formDiv);
            exchangeList.appendChild(wrapper);
        });

        // Clear global conclusion
        document.getElementById('globalConclusion').value = '';

        // Show overlay
        document.getElementById('manualCritiqueOverlay').style.display = 'block';

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
            <div style="background:#fefce8; padding:8px; border-radius:4px; font-size:0.9em; margin-bottom:8px; white-space:pre-wrap;">${escapeHtml(exchange.child_response)}</div>
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
    }
}

/**
 * Close and reset the manual critique form.
 */
function closeManualCritique() {
    document.getElementById('manualCritiqueOverlay').style.display = 'none';
}

/**
 * Collect all checked exchanges and submit manual critique.
 */
async function submitManualCritique() {
    // Collect checked exchanges
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
        return;
    }

    const globalConclusion = document.getElementById('globalConclusion').value;
    const submitBtn = document.getElementById('submitManualCritiqueBtn');
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
            closeManualCritique();
            const btn = document.getElementById('sendReportBtn');
            btn.textContent = 'Report Saved!';
            btn.style.background = '#10b981';
            console.log('[INFO] Manual critique saved to:', result.report_path);
            console.log('[INFO] Exchanges critiqued:', result.exchanges_critiqued);
            setTimeout(() => {
                btn.textContent = '\uD83D\uDCDD Send Report for Review';
                btn.style.background = '#f59e0b';
            }, 2000);
        } else {
            alert('Failed to save critique: ' + result.error);
        }
    } catch (e) {
        console.error('[ERROR] Manual critique failed:', e);
        alert('Failed to submit critique: ' + e.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit Critique';
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

/**
 * Save current session state to JSON file for bug reproduction
 * Excludes the last assistant message (buggy response)
 */
async function saveState() {
    if (!sessionId) {
        alert('No active session to save');
        return;
    }

    try {
        console.log('[INFO] Saving session state...');

        const response = await fetch(`${API_BASE}/save-state`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ session_id: sessionId })
        });

        const result = await response.json();

        if (!result.success) {
            throw new Error(result.error || 'Failed to save state');
        }

        // Download JSON file
        const blob = new Blob([JSON.stringify(result.state, null, 2)],
                              { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = result.filename;
        link.click();
        URL.revokeObjectURL(url);

        console.log('[INFO] State saved:', result.filename);

        // Show info about excluded response
        if (result.state.metadata.excluded_buggy_response) {
            alert(`Session state saved to ${result.filename}\n\nExcluded last AI response (buggy) from save.\nConversation ends with your last message, ready for replay after fixing the bug.`);
        } else {
            alert(`Session state saved to ${result.filename}`);
        }

    } catch (error) {
        console.error('[ERROR] Failed to save state:', error);
        alert(`Failed to save state: ${error.message}`);
    }
}

/**
 * Restore session from uploaded JSON file and auto-replay last user message
 */
async function restoreState() {
    const fileInput = document.getElementById('restoreFileInput');
    const restoreStatus = document.getElementById('restoreStatus');

    if (!fileInput.files || fileInput.files.length === 0) {
        restoreStatus.style.color = '#ef4444';
        restoreStatus.textContent = 'Please select a file first';
        return;
    }

    const file = fileInput.files[0];

    try {
        restoreStatus.style.color = '#3b82f6';
        restoreStatus.textContent = 'Loading file...';

        // Read file
        const fileText = await file.text();
        const state = JSON.parse(fileText);

        // Validate basic structure
        if (!state.metadata || !state.session_state || !state.conversation_history) {
            throw new Error('Invalid state file format');
        }

        restoreStatus.textContent = 'Restoring session...';

        // Send to backend
        const response = await fetch(`${API_BASE}/restore-state`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ state: state })
        });

        const result = await response.json();

        if (!result.success) {
            throw new Error(result.error || 'Failed to restore state');
        }

        // Update frontend state
        sessionId = result.session_id;
        currentObject = result.restored_state.object_name;
        correctAnswerCount = result.restored_state.correct_answer_count;

        // Clear and populate messages
        messagesContainer.innerHTML = '';

        // Extract buggy response metadata
        buggyResponseIndex = state.metadata.buggy_response_index;
        contextMessage = state.metadata.last_user_message;

        // Find last user message index (the one before buggy response)
        let lastUserMessageIndex = null;
        for (let i = state.conversation_history.length - 1; i >= 0; i--) {
            if (state.conversation_history[i].role === 'user') {
                lastUserMessageIndex = i;
                break;
            }
        }

        // Render conversation history, SKIP:
        // 1. System message (idx 0)
        // 2. Last user message (will be auto-replayed, avoid duplicate)
        // 3. Buggy assistant response
        state.conversation_history.forEach((msg, idx) => {
            if (idx === 0) return; // Skip system message

            // Skip last user message (will be auto-replayed)
            if (lastUserMessageIndex !== null && idx === lastUserMessageIndex) {
                return; // Don't render it (auto-replay will add it)
            }

            // Skip rendering the buggy response (even though it's in the data)
            if (buggyResponseIndex !== null && idx === buggyResponseIndex) {
                buggyResponse = msg.content; // Store for later comparison
                return; // Don't render it
            }

            if (msg.role === 'user') {
                addMessage('user', msg.content);
            } else if (msg.role === 'assistant') {
                addMessage('assistant', msg.content);
            }
        });

        // Mark as restored session for approval flow
        isRestoredSession = true;

        // Update UI
        startForm.style.display = 'none';
        progressIndicator.style.display = 'flex';
        messagesContainer.style.display = 'flex';
        document.querySelector('.input-area').style.display = 'flex';

        // Set up activeFocusControl dropdown based on restored state
        const activeFocusSelect = document.getElementById('activeFocusMode');
        const activeFocusControl = document.getElementById('activeFocusControl');
        const wasSystemManaged = state.session_state.system_managed_focus;
        const savedFocusMode = state.session_state.current_focus_mode || 'depth';

        if (activeFocusSelect && activeFocusControl) {
            // Set dropdown value to saved focus mode
            activeFocusSelect.value = savedFocusMode;

            // If was system_managed, disable the entire dropdown
            if (wasSystemManaged) {
                activeFocusSelect.disabled = true;
                systemManagedMode = true;  // Update global flag
            } else {
                // In manual mode, disable the "System Managed" option
                activeFocusSelect.disabled = false;
                const systemOption = activeFocusSelect.querySelector('option[value="system_managed"]');
                if (systemOption) {
                    systemOption.disabled = true;
                }
            }

            // Show the control
            activeFocusControl.style.display = 'flex';
        }

        // Update current state variables for debug panel
        currentCharacter = state.session_state.character;
        currentFocusMode = savedFocusMode;
        currentObject = state.session_state.object_name;

        updateProgressIndicator();
        updateDebugPanel();

        // Show save button
        document.getElementById('saveStateBtn').style.display = 'inline-block';

        // Enable input
        sendBtn.disabled = false;
        userInput.disabled = false;
        userInput.focus();

        restoreStatus.style.color = '#10b981';
        restoreStatus.textContent = `✓ Session restored (${result.restored_state.conversation_turns} messages)`;

        console.log('[INFO] Session restored:', result.session_id);

        // Auto-replay: Send the last user message automatically
        if (result.restored_state.last_user_message) {
            const lastUserMsg = result.restored_state.last_user_message;
            console.log(`[INFO] Auto-replaying last user message: "${lastUserMsg}"`);

            // Wait a moment for UI to settle, then send the message
            setTimeout(async () => {
                // Add the user message to the UI (it was skipped during restore)
                addMessage('user', lastUserMsg);

                // Get current focus mode
                const activeFocusMode = document.getElementById('activeFocusMode');
                const focusMode = activeFocusMode ? activeFocusMode.value : 'depth';

                // Disable send button during streaming
                sendBtn.disabled = true;
                isStreaming = true;

                restoreStatus.textContent += ' | Auto-replaying last message...';

                try {
                    // Create AbortController for this stream
                    currentStreamController = new AbortController();

                    const response = await fetch(`${API_BASE}/continue`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            session_id: sessionId,
                            child_input: lastUserMsg,
                            focus_mode: focusMode
                        }),
                        signal: currentStreamController.signal
                    });

                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }

                    // Create message bubble for streaming response
                    currentMessageDiv = null;

                    // Read streaming response
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';

                    while (true) {
                        const { done, value } = await reader.read();

                        if (done) {
                            console.log('[INFO] Auto-replay stream ended');
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
                    console.error('[ERROR] Auto-replay error:', error);
                    alert(`Auto-replay failed: ${error.message}`);
                } finally {
                    isStreaming = false;
                    sendBtn.disabled = false;
                    currentStreamController = null;
                }
            }, 500);
        }

    } catch (error) {
        console.error('[ERROR] Failed to restore state:', error);
        restoreStatus.style.color = '#ef4444';
        restoreStatus.textContent = `Error: ${error.message}`;
    }
}

/**
 * Show approval buttons after auto-replay completes
 */
function showApprovalButtons() {
    // Validate we have all required data
    if (!buggyResponse || !newResponse || !contextMessage) {
        console.warn('Missing comparison data, skipping approval UI');
        return;
    }

    const approvalContainer = document.getElementById('approvalContainer');
    if (approvalContainer) {
        approvalContainer.style.display = 'flex';
    }
}

/**
 * Handle approval of bugfix - generate and download HTML comparison
 */
async function handleApproval() {
    // Disable buttons to prevent double-click
    const approveBtn = document.getElementById('approveBtn');
    const rejectBtn = document.getElementById('rejectBtn');
    approveBtn.disabled = true;
    rejectBtn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/generate-bugfix-comparison`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                buggy_response: buggyResponse,
                new_response: newResponse,
                context_message: contextMessage
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const result = await response.json();

        // Create blob and download HTML file
        const blob = new Blob([result.html], { type: 'text/html' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = result.filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

        alert(`✓ Bug comparison saved as ${result.filename}`);

        // Hide approval buttons and reset state
        document.getElementById('approvalContainer').style.display = 'none';
        resetBugTrackingState();

    } catch (error) {
        console.error('Error generating comparison:', error);
        alert(`Failed to generate comparison: ${error.message}`);
        approveBtn.disabled = false;
        rejectBtn.disabled = false;
    }
}

/**
 * Handle rejection of bugfix - just hide buttons
 */
function handleRejection() {
    // Simply hide approval buttons
    document.getElementById('approvalContainer').style.display = 'none';
    resetBugTrackingState();
}

/**
 * Reset bug tracking state variables
 */
function resetBugTrackingState() {
    buggyResponse = null;
    newResponse = null;
    contextMessage = null;
    buggyResponseIndex = null;
    isRestoredSession = false;
}

// Initialize on page load
init();
