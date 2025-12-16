/**
 * Ask Ask Assistant - Streaming Chat Client
 *
 * This file handles:
 * - SSE (Server-Sent Events) streaming from the backend
 * - Typewriter effect for real-time text display
 * - Session management
 * - User input handling
 */

const API_BASE = 'http://localhost:5001/api';

// Global state
let sessionId = null;
let currentMessageDiv = null;
let isStreaming = false;

// DOM elements
const messagesContainer = document.getElementById('messages');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const ageSelector = document.getElementById('ageSelector');

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

    // Disable controls
    userInput.disabled = true;
    sendBtn.disabled = true;
    isStreaming = true;

    try {
        console.log('[INFO] Starting conversation with age:', age || 'not specified');

        const response = await fetch(`${API_BASE}/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                age: age ? parseInt(age) : null
            })
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
        console.error('[ERROR] Failed to start conversation:', error);
        messagesContainer.innerHTML = '';
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = `Error: ${error.message}. Please check if the server is running.`;
        messagesContainer.appendChild(errorDiv);
    } finally {
        // Re-enable controls
        isStreaming = false;
        userInput.disabled = false;
        sendBtn.disabled = false;
        userInput.focus();

        // Hide age selector after starting
        if (sessionId) {
            ageSelector.style.display = 'none';
        }
    }
}

/**
 * Send a user message
 */
async function sendMessage() {
    const text = userInput.value.trim();

    // Validate input
    if (!text || !sessionId || isStreaming) {
        return;
    }

    // Add user message to chat
    addMessage('user', text);
    userInput.value = '';

    // Disable controls
    userInput.disabled = true;
    sendBtn.disabled = true;
    isStreaming = true;

    try {
        console.log('[INFO] Sending message:', text);

        const response = await fetch(`${API_BASE}/continue`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: sessionId,
                child_input: text
            })
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
        console.error('[ERROR] Failed to send message:', error);
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = `Error: ${error.message}`;
        messagesContainer.appendChild(errorDiv);
    } finally {
        // Re-enable controls
        isStreaming = false;
        userInput.disabled = false;
        sendBtn.disabled = false;
        userInput.focus();
    }
}

/**
 * Handle SSE events from the server
 * @param {string} eventType - The type of event
 * @param {object} data - The event data
 */
async function handleSSEEvent(eventType, data) {
    console.log(`[${eventType}]`, data);

    switch (eventType) {
        case 'metadata':
            // Handle metadata (session ID, state, etc.)
            if (data.session_id) {
                sessionId = data.session_id;
                console.log('[INFO] Session ID:', sessionId);
            }
            if (data.is_stuck !== undefined) {
                console.log('[INFO] Child is stuck:', data.is_stuck);
            }
            break;

        case 'text_chunk':
            // Display text chunk immediately (streaming provides the real-time effect)
            if (currentMessageDiv && data.text) {
                displayChunk(currentMessageDiv, data.text);
            }
            break;

        case 'complete':
            // Stream completed successfully
            console.log('[INFO] Stream complete:', data);
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
