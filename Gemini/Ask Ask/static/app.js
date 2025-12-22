/**
 * Ask Ask Assistant - Streaming Chat Client
 *
 * This file handles:
 * - SSE (Server-Sent Events) streaming from the backend
 * - Real-time text display using StreamChunk format
 * - Session management
 * - User input handling
 */

// Automatically use the same host as the frontend (works for localhost, server, and ngrok)
const API_BASE = `${window.location.protocol}//${window.location.host}/api`;

// Global state
let sessionId = null;
let currentMessageDiv = null;
let isStreaming = false;
let currentStreamController = null;

// DOM elements
const messagesContainer = document.getElementById('messages');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const ageSelector = document.getElementById('ageSelector');
const thinkingTimeDisplay = document.getElementById('thinking-time');

/**
 * Add a message to the chat interface
 * @param {string} role - 'assistant' or 'user'
 * @param {string} initialText - Initial text to display (optional)
 * @returns {HTMLElement} The message bubble element
 */
function addMessage(role, initialText = '') {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.textContent = initialText;

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
    element.textContent += text;
    // Auto-scroll as text appears
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

/**
 * Start a new conversation
 */
async function startConversation() {
    const age = document.getElementById('age').value;

    // Clear previous messages
    messagesContainer.innerHTML = '';
    sessionId = null;
    thinkingTimeDisplay.textContent = '';
    thinkingTimeDisplay.style.opacity = 0;

    // Disable controls
    userInput.disabled = true;
    sendBtn.disabled = true;
    isStreaming = true;
    updateStopButton();

    try {
        console.log('[INFO] Starting conversation with age:', age || 'not specified');

        // Create AbortController for this stream
        currentStreamController = new AbortController();

        const response = await fetch(`${API_BASE}/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                age: age ? parseInt(age) : null
            }),
            signal: currentStreamController.signal
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        // Create message bubble for streaming response
        currentMessageDiv = addMessage('assistant', '');

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

        // Re-enable controls
        isStreaming = false;
        userInput.disabled = false;
        sendBtn.disabled = false;
        updateStopButton();
        userInput.focus();

        // Hide age selector after starting
        if (sessionId) {
            ageSelector.style.display = 'none';
        }
    }
}

/**
 * Stop the current streaming response
 */
async function stopStreaming() {
    if (!sessionId) {
        return;
    }

    console.log('[INFO] Stopping stream...');

    // Call backend to cancel stream
    try {
        const response = await fetch(`${API_BASE}/stop`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: sessionId
            })
        });

        const result = await response.json();
        if (result.success) {
            console.log('[INFO] Stream stopped successfully');
        } else {
            console.warn('[WARNING] Failed to stop stream:', result.error);
        }
    } catch (error) {
        console.error('[ERROR] Error stopping stream:', error);
    }

    // Also abort frontend connection
    if (currentStreamController) {
        currentStreamController.abort();
        currentStreamController = null;
    }

    // Reset UI state
    isStreaming = false;
    userInput.disabled = false;
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

    // Interrupt ongoing stream if exists
    if (isStreaming) {
        console.log('[INFO] Interrupting previous stream');
        await stopStreaming();
        // Wait briefly for cleanup
        await new Promise(resolve => setTimeout(resolve, 100));
    }

    // Clear thinking time display
    thinkingTimeDisplay.textContent = '';
    thinkingTimeDisplay.style.opacity = 0;

    // Add user message to chat
    addMessage('user', text);
    userInput.value = '';

    // Disable controls
    userInput.disabled = true;
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

        // Create message bubble for streaming response
        currentMessageDiv = addMessage('assistant', '');

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

        // Re-enable controls
        isStreaming = false;
        userInput.disabled = false;
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

    // Display stuck status if present
    if (chunk.is_stuck !== undefined && chunk.is_stuck) {
        console.log('[INFO] Child appears stuck - suggesting topics');
    }

    // Handle text chunks (non-finish chunks with response text)
    if (!chunk.finish && chunk.response) {
        if (currentMessageDiv) {
            displayChunk(currentMessageDiv, chunk.response);
        }
    }

    // Handle final chunk (finish=true)
    if (chunk.finish) {
        // Only update if final response is longer (prevents cutoffs from incomplete final chunks)
        if (currentMessageDiv && chunk.response) {
            const currentText = currentMessageDiv.textContent;
            if (chunk.response.length > currentText.length) {
                // Final chunk has more text, use it
                currentMessageDiv.textContent = chunk.response;
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

        // Check if session is finished
        if (chunk.session_finished) {
            console.log('[INFO] Session finished');
            // Could add UI indicator here if needed
        }
    }
}

/**
 * Initialize the application
 */
function init() {
    console.log('[INFO] Ask Ask Streaming Chat initialized');

    // Show empty state
    if (messagesContainer.children.length === 0) {
        const emptyState = document.createElement('div');
        emptyState.className = 'empty-state';
        emptyState.innerHTML = `
            <p>👋 Welcome to Ask Ask!</p>
            <small>Select your age and click "Start Conversation" to begin</small>
        `;
        messagesContainer.appendChild(emptyState);
    }

    // Focus on age selector
    document.getElementById('age').focus();
}

// Initialize on page load
init();
