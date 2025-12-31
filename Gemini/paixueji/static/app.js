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
    const tone = document.getElementById('assistantTone').value;
    const focusMode = document.getElementById('nextQuestionFocus').value;

    // Save tone preference
    localStorage.setItem('paixueji_tone', tone);

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
                tone: tone,
                focus_mode: focusMode
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

    const focusMode = document.getElementById('nextQuestionFocus').value;

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
            currentMessageDiv = addMessage('assistant', '', chunk.focus_mode, isCorrect);
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

        // INFINITE MODE: No completion UI - conversation never ends
    }

    // Handle detected object (AI decided to CONTINUE but detected a new object)
    if (chunk.detected_object_name && chunk.switch_decision_reasoning) {
        detectedObject = chunk.detected_object_name;
        document.getElementById('detectedObjectName').textContent = detectedObject;
        document.getElementById('switchToObjectName').textContent = detectedObject;
        document.getElementById('switchReasoning').textContent = chunk.switch_decision_reasoning;
        document.getElementById('manualSwitchPanel').style.display = 'block';
        console.log('[INFO] Object detected but not switching:', detectedObject, '| Reasoning:', chunk.switch_decision_reasoning);
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

    // Load saved tone preference
    const savedTone = localStorage.getItem('paixueji_tone');
    if (savedTone) {
        const toneSelect = document.getElementById('assistantTone');
        if (toneSelect) {
            toneSelect.value = savedTone;
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

// Initialize on page load
init();
