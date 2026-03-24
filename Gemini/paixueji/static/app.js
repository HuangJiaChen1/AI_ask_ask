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
const RATE_LIMIT_FALLBACK_MESSAGE = 'The model is busy right now, so there was no answer to show. Please try again in a moment.';

// Global state
let sessionId = null;
let currentMessageDiv = null;
let isStreaming = false;
let currentStreamController = null;
let correctAnswerCount = 0;
let conversationComplete = false;
let detectedObject = null;  // For manual topic switch override
let awaitingObjectSelection = false;  // Waiting for object choice flag
let lastRequest = null;           // { type: 'start' | 'continue', childInput?: string }
let retryCountdownInterval = null;
let retryAutoTimer = null;
let errorBubble = null;           // DOM reference to active error bubble

// Game-eligible entities (populated from /api/objects has_game flag)
const gameEntityNames = new Set();

// UI state
let currentObject = null;  // Current object being discussed
let guidePhase = null;  // Guide phase (active, success, hint, exit)
let guideTurnCount = 0;  // Current turn in guide mode
let currentThemeName = null;  // IB PYP theme name
let currentKeyConcept = null;  // Key concept for theme
let currentIntentType = null;       // Last classified intent (9-node architecture)
let currentResponseType = null;     // Last response node that actually ran
let currentHookType = null;         // Hook type selected for this session
let currentClassificationStatus = null;
let currentClassificationFailureReason = null;
let currentActiveDimension = null;
let currentCurrentDimension = null;
let currentDimensionsCovered = [];
let currentDimensionHintText = null;

const INTENT_METADATA = {
    ACTION: {
        color: '#10b981',
        description: 'The child is asking the assistant to do something or change direction.',
        descriptionZh: '孩子在请助手做点什么，或换个方向继续。',
    },
    AVOIDANCE: {
        color: '#6b7280',
        description: 'The child is trying to avoid or leave the current topic.',
        descriptionZh: '孩子想避开或结束当前话题。',
    },
    BOUNDARY: {
        color: '#ef4444',
        description: 'The child is asking about something risky or unsafe.',
        descriptionZh: '孩子在询问可能有风险或不安全的做法。',
    },
    CLARIFYING_CONSTRAINT: {
        color: '#f59e0b',
        description: 'The child is engaged but explains they cannot do or access something.',
        descriptionZh: '孩子仍然愿意聊，但说明自己现在做不到或接触不到。',
    },
    CLARIFYING_IDK: {
        color: '#f59e0b',
        description: 'The child seems unsure or does not know the answer yet.',
        descriptionZh: '孩子现在不太确定，或者还不知道答案。',
    },
    CLARIFYING_WRONG: {
        color: '#f59e0b',
        description: 'The child tried to answer, but the answer seems off.',
        descriptionZh: '孩子试着回答了，但答案可能不太对。',
    },
    CORRECT_ANSWER: {
        color: '#16a34a',
        description: 'The child gave an on-target answer.',
        descriptionZh: '孩子给出了基本正确的回答。',
    },
    CURIOSITY: {
        color: '#8b5cf6',
        description: 'The child is asking to learn more about the topic.',
        descriptionZh: '孩子正在提问，想更了解这个话题。',
    },
    EMOTIONAL: {
        color: '#14b8a6',
        description: 'The child is expressing a feeling.',
        descriptionZh: '孩子正在表达自己的感受。',
    },
    INFORMATIVE: {
        color: '#3b82f6',
        description: 'The child is sharing something they already know.',
        descriptionZh: '孩子在主动分享自己已经知道的事情。',
    },
    PLAY: {
        color: '#ec4899',
        description: 'The child is being playful or imaginative.',
        descriptionZh: '孩子在用玩笑或想象力来回应。',
    },
    SOCIAL: {
        color: '#f97316',
        description: 'The child is asking about the assistant itself.',
        descriptionZh: '孩子在问助手本身，而不是在问这个话题。',
    },
    SOCIAL_ACKNOWLEDGMENT: {
        color: '#64748b',
        description: 'The child is reacting briefly to what the assistant said.',
        descriptionZh: '孩子只是在简短回应助手刚才说的话。',
    },
};

const RESPONSE_METADATA = {
    ACTION: {
        color: '#10b981',
        description: 'The assistant is following the child’s request or changing direction as asked.',
        descriptionZh: '助手正在按孩子的要求行动，或按要求换个方向继续。',
    },
    AVOIDANCE: {
        color: '#6b7280',
        description: 'The assistant is honoring the child’s wish to stop and offering a low-pressure next step.',
        descriptionZh: '助手正在尊重孩子想暂停的话，并给一个没有压力的下一步选项。',
    },
    BOUNDARY: {
        color: '#ef4444',
        description: 'The assistant is redirecting risky curiosity into a safer way to explore.',
        descriptionZh: '助手正在把有风险的好奇心转成更安全的探索方式。',
    },
    CLARIFYING_CONSTRAINT: {
        color: '#f59e0b',
        description: 'The assistant is validating the child’s limitation and keeping the topic going imaginatively.',
        descriptionZh: '助手正在接住孩子现实中的限制，同时用想象继续这个话题。',
    },
    CLARIFYING_IDK: {
        color: '#f59e0b',
        description: 'The assistant is giving a clue instead of repeating the same question.',
        descriptionZh: '助手正在给一个线索，而不是把同一个问题再问一遍。',
    },
    CLARIFYING_WRONG: {
        color: '#f59e0b',
        description: 'The assistant is gently correcting the answer and inviting the child to look or think again.',
        descriptionZh: '助手正在温和地纠正答案，并邀请孩子再看看或再想想。',
    },
    CORRECT_ANSWER: {
        color: '#16a34a',
        description: 'The assistant is confirming the answer and rewarding it with one related wow fact.',
        descriptionZh: '助手正在确认孩子答对了，并送上一个相关的小惊喜事实。',
    },
    CURIOSITY: {
        color: '#8b5cf6',
        description: 'The assistant is answering the child’s question, adding one interesting detail, and ending with an easy follow-up.',
        descriptionZh: '助手正在回答孩子的问题，补充一个有趣细节，并用一个容易接住的追问收尾。',
    },
    EMOTIONAL: {
        color: '#14b8a6',
        description: 'The assistant is responding to the child’s feeling first, then offering a gentle next step.',
        descriptionZh: '助手正在先回应孩子的感受，再给一个温和的下一步。',
    },
    GIVE_ANSWER_IDK: {
        color: '#f59e0b',
        description: 'The assistant is stopping the hinting and giving the answer directly.',
        descriptionZh: '助手不再继续提示，而是直接把答案告诉孩子。',
    },
    FALLBACK_FREEFORM: {
        color: '#0f766e',
        description: 'The assistant is using a natural freeform recovery response because intent classification failed.',
        descriptionZh: '因为意图分类失败，助手正在使用自然的自由恢复式回应。',
    },
    GUIDE_EXIT: {
        color: '#ef4444',
        description: 'The assistant is ending the guided discovery gracefully because it is not working right now.',
        descriptionZh: '助手正在礼貌结束这段引导，因为现在这样聊下去效果不太好。',
    },
    GUIDE_HINT: {
        color: '#f59e0b',
        description: 'The assistant is giving a stronger, more concrete hint after the child has struggled a few times.',
        descriptionZh: '助手正在给一个更具体、更明显的提示，因为孩子已经卡住了几次。',
    },
    GUIDE_RESPONSE: {
        color: '#6366f1',
        description: 'The assistant is giving the next guided-discovery step based on how the child is progressing.',
        descriptionZh: '助手正在根据孩子目前的进展，给出下一步引导。',
    },
    GUIDE_SUCCESS: {
        color: '#16a34a',
        description: 'The assistant is celebrating that the child reached the bigger idea.',
        descriptionZh: '助手正在庆祝孩子已经理解到那个更大的想法。',
    },
    INFORMATIVE: {
        color: '#3b82f6',
        description: 'The assistant is celebrating what the child volunteered without interrupting it with correction.',
        descriptionZh: '助手正在庆祝孩子主动分享的内容，不急着打断或纠正。',
    },
    INTRODUCTION: {
        color: '#0ea5e9',
        description: 'The assistant is opening the conversation by naming the object, making it feel familiar, and sharing a fun fact.',
        descriptionZh: '助手正在用认识物体、拉近感觉和一个有趣事实来开启对话。',
    },
    PLAY: {
        color: '#ec4899',
        description: 'The assistant is joining the child’s imagination and turning it into playful exploration.',
        descriptionZh: '助手正在顺着孩子的想象，一起把对话变成好玩的探索。',
    },
    QUESTION: {
        color: '#6366f1',
        description: 'The assistant is starting a discovery question to guide the child toward a bigger idea.',
        descriptionZh: '助手正在用一个发现式问题，引导孩子走向更大的核心想法。',
    },
    SOCIAL: {
        color: '#f97316',
        description: 'The assistant is answering a question about itself briefly and reconnecting through the child’s experience.',
        descriptionZh: '助手正在简短回答关于自己的问题，再把重点连回孩子的真实体验。',
    },
    SOCIAL_ACKNOWLEDGMENT: {
        color: '#64748b',
        description: 'The assistant gives a brief warm reaction without repeating the same fact.',
        descriptionZh: '助手会先给一个简短温暖的回应，不重复刚才的事实。',
    },
    TOPIC_SWITCH: {
        color: '#0ea5e9',
        description: 'The assistant is celebrating the new object before moving the conversation there.',
        descriptionZh: '助手正在先庆祝新的物体，再把对话切换过去。',
    },
};

const HOOK_TYPE_METADATA = {
    '意图好奇':      { color: '#7c3aed', description: 'Ask about the child\'s creative intent',        descriptionZh: '询问孩子的创作意图' },
    '想象导向':      { color: '#0891b2', description: 'Pull the object into a fantasy world',          descriptionZh: '把物品带入奇幻世界' },
    '情绪投射':      { color: '#be185d', description: 'Project emotions onto the object (animism)',    descriptionZh: '把情感投射到物品上' },
    '角色代入':      { color: '#b45309', description: 'Put the child in an interactive role',          descriptionZh: '让孩子扮演互动角色' },
    '选择偏好':      { color: '#059669', description: 'Express personal likes or dislikes',            descriptionZh: '表达个人喜好' },
    '细节发现':      { color: '#2563eb', description: 'Notice a specific sensory detail',              descriptionZh: '引导发现一个细节' },
    '经验、生活链接': { color: '#d97706', description: 'Connect to the child\'s own experiences',       descriptionZh: '与孩子自身经历联结' },
    '创意改造':      { color: '#dc2626', description: 'Imagine redesigning or upgrading the object',   descriptionZh: '鼓励孩子改造或升级物品' },
};

const DIMENSION_METADATA = {
    // Physical (blue family)
    'appearance':  { color: '#3b82f6' },
    'senses':      { color: '#60a5fa' },
    'function':    { color: '#2563eb' },
    'structure':   { color: '#1d4ed8' },
    'context':     { color: '#93c5fd' },
    'change':      { color: '#bfdbfe' },
    // Engagement (green/purple family)
    'emotions':     { color: '#10b981' },
    'relationship': { color: '#a855f7' },
    'reasoning':    { color: '#8b5cf6' },
    'imagination':  { color: '#06b6d4' },
    'narrative':    { color: '#f59e0b' },
};

function setBilingualDescription(element, english, chinese) {
    if (!element) {
        return;
    }

    if (!english && !chinese) {
        element.textContent = '-';
        return;
    }

    element.replaceChildren();

    const englishLine = document.createElement('div');
    englishLine.textContent = english;
    element.appendChild(englishLine);

    const chineseLine = document.createElement('div');
    chineseLine.textContent = chinese;
    chineseLine.style.marginTop = '2px';
    element.appendChild(chineseLine);
}

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

function addAssistantErrorMessage(message) {
    const bubble = addMessage('assistant', message);
    bubble.classList.add('assistant-error');
    return bubble;
}

function isRateLimitedErrorPayload(data) {
    return data && (data.code === 429 || data.error_type === 'rate_limited');
}

function renderRateLimitError(data = null) {
    currentMessageDiv = null;
    addAssistantErrorMessage(data?.user_message || RATE_LIMIT_FALLBACK_MESSAGE);
}

function clearRetryState() {
    clearInterval(retryCountdownInterval);
    clearTimeout(retryAutoTimer);
    retryCountdownInterval = null;
    retryAutoTimer = null;
    if (errorBubble) { errorBubble.remove(); errorBubble = null; }
}

function clearPartialBubble() {
    if (currentMessageDiv) {
        currentMessageDiv.parentElement?.remove();
        currentMessageDiv = null;
    }
}

function renderRetryUI(is429, message) {
    const bubble = document.createElement('div');
    bubble.className = 'retry-error-bubble';

    const msg = document.createElement('p');
    msg.className = 'retry-message';

    const actions = document.createElement('div');
    actions.className = 'retry-actions';

    if (is429) {
        let remaining = 5;
        msg.textContent = `⚠ The model is busy. Retrying in ${remaining}s…`;

        const retryNowBtn = document.createElement('button');
        retryNowBtn.className = 'btn-retry-now';
        retryNowBtn.textContent = 'Retry now';
        retryNowBtn.onclick = () => executeRetry();

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn-cancel-retry';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.onclick = () => clearRetryState();

        retryCountdownInterval = setInterval(() => {
            remaining--;
            if (remaining > 0) {
                msg.textContent = `⚠ The model is busy. Retrying in ${remaining}s…`;
            }
        }, 1000);

        retryAutoTimer = setTimeout(() => executeRetry(), 5000);

        actions.append(retryNowBtn, cancelBtn);
    } else {
        msg.textContent = `⚠ ${message || 'Response interrupted.'}`;

        const retryBtn = document.createElement('button');
        retryBtn.className = 'btn-retry-manual';
        retryBtn.textContent = '↻ Retry';
        retryBtn.onclick = () => executeRetry();

        const dismissBtn = document.createElement('button');
        dismissBtn.className = 'btn-cancel-retry';
        dismissBtn.textContent = 'Dismiss';
        dismissBtn.onclick = () => clearRetryState();

        actions.append(retryBtn, dismissBtn);
    }

    bubble.append(msg, actions);
    messagesContainer.appendChild(bubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    errorBubble = bubble;
}

function executeRetry() {
    const req = lastRequest;
    clearRetryState();
    if (!req) return;
    if (req.type === 'start') {
        startConversation();
    } else if (req.type === 'continue') {
        // Re-run streaming only — user message is already in the DOM
        sendBtn.disabled = true;
        isStreaming = true;
        updateStopButton();
        continueConversation(req.childInput);
    }
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
    currentIntentType = null;
    currentResponseType = null;
    currentHookType = null;
    currentClassificationStatus = null;
    currentClassificationFailureReason = null;

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
        clearRetryState();
        lastRequest = { type: 'start' };

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
        if (error.name === 'AbortError') {
            console.log('[INFO] Stream interrupted by user');
            return;
        }
        console.error('[ERROR] Failed to start conversation:', error);
        const is429 = String(error.message || '').includes('HTTP 429');
        clearPartialBubble();
        renderRetryUI(is429, is429 ? null : error.message);
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
 * Stream a continuation response for the given child input.
 * Does NOT add the user message to the DOM — caller is responsible for that.
 */
async function continueConversation(childInput) {
    clearRetryState();
    lastRequest = { type: 'continue', childInput };

    try {
        console.log('[INFO] Sending message:', childInput);

        currentStreamController = new AbortController();

        const response = await fetch(`${API_BASE}/continue`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                child_input: childInput
            }),
            signal: currentStreamController.signal
        });

        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('Session not found. Please start a new conversation.');
            }
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        currentMessageDiv = null;

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                console.log('[INFO] Stream ended');
                break;
            }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.trim()) continue;
                const eventMatch = line.match(/^event: (.+)$/m);
                const dataMatch = line.match(/^data: (.+)$/m);
                if (eventMatch && dataMatch) {
                    const eventType = eventMatch[1];
                    const data = JSON.parse(dataMatch[1]);
                    await handleSSEEvent(eventType, data);
                }
            }
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            console.log('[INFO] Stream interrupted by user');
            return;
        }
        console.error('[ERROR] Failed to send message:', error);
        const is429 = String(error.message || '').includes('HTTP 429');
        clearPartialBubble();
        renderRetryUI(is429, is429 ? null : error.message);
    } finally {
        currentStreamController = null;
        isStreaming = false;
        sendBtn.disabled = false;
        updateStopButton();
        userInput.focus();
    }
}

/**
 * Send a user message
 */
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text || !sessionId) return;

    if (isStreaming && currentStreamController) {
        console.log('[INFO] Interrupting previous stream');
        currentStreamController.abort();
        currentStreamController = null;
    }

    clearRetryState();
    thinkingTimeDisplay.textContent = '';
    thinkingTimeDisplay.style.opacity = 0;

    addMessage('user', text);
    userInput.value = '';

    sendBtn.disabled = true;
    isStreaming = true;
    updateStopButton();

    lastRequest = { type: 'continue', childInput: text };
    await continueConversation(text);
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
            console.error('[ERROR] Stream error:', data);
            clearPartialBubble();
            renderRetryUI(isRateLimitedErrorPayload(data), data?.user_message || data?.message);
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
    if ('intent_type' in chunk) {
        currentIntentType = chunk.intent_type;
        updateDebugPanel();
    }

    // Update response type (which node actually ran — may differ from intent_type via routing intercept)
    if ('response_type' in chunk) {
        currentResponseType = chunk.response_type;
        updateDebugPanel();
    }

    if ('classification_status' in chunk) {
        currentClassificationStatus = chunk.classification_status;
        updateDebugPanel();
    }
    if ('classification_failure_reason' in chunk) {
        currentClassificationFailureReason = chunk.classification_failure_reason;
        updateDebugPanel();
    }

    // Update dimension debug state (set on follow-up question chunks)
    if (chunk.active_dimension !== undefined && chunk.active_dimension !== null) {
        currentActiveDimension = chunk.active_dimension;
        updateDebugPanel();
    }
    if (chunk.current_dimension !== undefined && chunk.current_dimension !== null) {
        currentCurrentDimension = chunk.current_dimension;
        updateDebugPanel();
    }
    if (chunk.dimensions_covered !== undefined && chunk.dimensions_covered !== null) {
        currentDimensionsCovered = chunk.dimensions_covered;
        updateDebugPanel();
    }
    if (chunk.dimension_hint_text !== undefined && chunk.dimension_hint_text !== null) {
        currentDimensionHintText = chunk.dimension_hint_text;
        updateDebugPanel();
    }

    // Update hook type (set on introduction, persists for session)
    if (chunk.selected_hook_type) {
        currentHookType = chunk.selected_hook_type;
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
    const intentDescriptionElement = document.getElementById('debugIntentDescription');
    if (intentElement) {
        const normalizedIntent = currentIntentType ? currentIntentType.toUpperCase() : null;
        const intentMeta = normalizedIntent ? INTENT_METADATA[normalizedIntent] : null;

        intentElement.textContent = currentIntentType || '-';
        intentElement.style.color = intentMeta ? intentMeta.color : '#6b7280';

        if (intentDescriptionElement) {
            if (intentMeta) {
                setBilingualDescription(
                    intentDescriptionElement,
                    intentMeta.description,
                    intentMeta.descriptionZh,
                );
            } else if (currentIntentType) {
                setBilingualDescription(
                    intentDescriptionElement,
                    'The system detected a conversation pattern.',
                    '系统识别到一种对话模式。',
                );
            } else {
                intentDescriptionElement.textContent = '-';
            }
        }
    }

    // Update response type display
    const responseTypeEl = document.getElementById('debugResponseType');
    const responseDescriptionEl = document.getElementById('debugResponseDescription');
    if (responseTypeEl) {
        const normalizedResponseType = currentResponseType ? currentResponseType.toUpperCase() : null;
        const responseMeta = normalizedResponseType ? RESPONSE_METADATA[normalizedResponseType] : null;

        responseTypeEl.textContent = currentResponseType || '-';
        responseTypeEl.style.color = responseMeta ? responseMeta.color : '#0f172a';

        if (responseDescriptionEl) {
            if (responseMeta) {
                setBilingualDescription(
                    responseDescriptionEl,
                    responseMeta.description,
                    responseMeta.descriptionZh,
                );
            } else if (currentResponseType) {
                setBilingualDescription(
                    responseDescriptionEl,
                    'The assistant is using a conversation strategy for this moment.',
                    '助手正在使用当前这一轮对话所需的回应策略。',
                );
            } else {
                responseDescriptionEl.textContent = '-';
            }
        }
    }

    // Update hook type
    const hookTypeEl = document.getElementById('debugHookType');
    if (hookTypeEl) {
        const hookMeta = currentHookType ? HOOK_TYPE_METADATA[currentHookType] : null;
        hookTypeEl.textContent = currentHookType || '-';
        hookTypeEl.style.color = hookMeta ? hookMeta.color : '#64748b';
        const hookDescEl = document.getElementById('debugHookTypeDescription');
        if (hookDescEl) {
            if (hookMeta) {
                setBilingualDescription(hookDescEl, hookMeta.description, hookMeta.descriptionZh);
            } else {
                hookDescEl.textContent = '-';
            }
        }
    }

    const classificationStatusEl = document.getElementById('debugClassificationStatus');
    const classificationReasonEl = document.getElementById('debugClassificationReason');
    if (classificationStatusEl) {
        if (currentClassificationStatus === 'failed') {
            classificationStatusEl.textContent = 'FAILED';
            classificationStatusEl.style.color = '#dc2626';
        } else if (currentClassificationStatus === 'ok') {
            classificationStatusEl.textContent = 'OK';
            classificationStatusEl.style.color = '#16a34a';
        } else {
            classificationStatusEl.textContent = '-';
            classificationStatusEl.style.color = '#64748b';
        }
    }
    if (classificationReasonEl) {
        classificationReasonEl.textContent = currentClassificationFailureReason || '-';
    }

    // --- Dimension debug section ---
    const activeDimEl = document.getElementById('debugActiveDimension');
    if (activeDimEl) {
        if (currentActiveDimension) {
            const meta = DIMENSION_METADATA[currentActiveDimension] || {};
            activeDimEl.textContent = currentActiveDimension;
            activeDimEl.style.color = meta.color || '#0f172a';
        } else {
            activeDimEl.textContent = '-';
            activeDimEl.style.color = '#94a3b8';
        }
    }

    const currentDimEl = document.getElementById('debugCurrentDimension');
    if (currentDimEl) {
        if (currentCurrentDimension) {
            const meta = DIMENSION_METADATA[currentCurrentDimension] || {};
            currentDimEl.textContent = currentCurrentDimension;
            currentDimEl.style.color = meta.color || '#0f172a';
        } else {
            currentDimEl.textContent = '-';
            currentDimEl.style.color = '#94a3b8';
        }
    }

    const coveredEl = document.getElementById('debugDimensionsCovered');
    if (coveredEl) {
        coveredEl.textContent = currentDimensionsCovered.length > 0
            ? currentDimensionsCovered.join(' · ')
            : '-';
    }

    const hintEl = document.getElementById('debugDimensionHint');
    if (hintEl) {
        hintEl.textContent = currentDimensionHintText || '(no hint — entity not in DB or all covered)';
    }
}

function toggleDimensionHint() {
    const hint = document.getElementById('debugDimensionHint');
    const btn = hint.previousElementSibling;
    if (hint.style.display === 'none') {
        hint.style.display = 'block';
        btn.textContent = 'Hint ▼';
    } else {
        hint.style.display = 'none';
        btn.textContent = 'Hint ▶';
    }
}

/**
 * Show the "chat phase complete" modal (4th correct answer reached).
 * For game-eligible entities the button becomes "Let's Play!" and triggers handoff.
 */
function showChatPhaseCompleteModal() {
    const modal = document.getElementById('chatPhaseCompleteModal');
    modal.style.display = 'flex';

    const btn = modal.querySelector('button');
    if (currentObject && gameEntityNames.has(currentObject)) {
        btn.textContent = "Let's Play!";
        btn.onclick = handoff;
    } else {
        btn.textContent = 'Got it!';
        btn.onclick = closeChatPhaseCompleteModal;
    }
}

function closeChatPhaseCompleteModal() {
    document.getElementById('chatPhaseCompleteModal').style.display = 'none';
    document.getElementById('userInput').disabled = true;
    document.getElementById('sendBtn').disabled = true;
}

/**
 * Save conversation history and redirect to WonderLens.
 */
async function handoff() {
    try {
        const res = await fetch('/api/handoff', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId }),
        });
        if (!res.ok) throw new Error('Handoff failed: ' + res.status);
        const data = await res.json();
        window.location.href = data.redirect_url;
    } catch (err) {
        console.error('Handoff error:', err);
        closeChatPhaseCompleteModal();
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
    currentObject = null;
    guidePhase = null;
    guideTurnCount = 0;
    currentThemeName = null;
    currentKeyConcept = null;
    currentIntentType = null;
    currentResponseType = null;
    currentHookType = null;
    currentClassificationStatus = null;
    currentClassificationFailureReason = null;

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
                if (item.has_game) {
                    opt.textContent = '🎮 ' + item.name;
                    gameEntityNames.add(item.name.toLowerCase());
                } else {
                    opt.textContent = item.name;
                }
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
 * Fetch exchanges and show the manual critique form.
 */
async function showManualCritiqueForm() {
    try {
        const response = await fetch(`${API_BASE}/exchanges/${sessionId}`);
        const result = await response.json();

        if (!result.success) {
            alert('Failed to load exchanges: ' + result.error);
            return;
        }

        if (result.exchanges.length === 0 && !result.introduction) {
            alert('No exchanges found. Need at least one child response after the introduction.');
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

        // Introduction card (index 0)
        if (result.introduction) {
            const intro = result.introduction;
            const introWrapper = document.createElement('div');
            introWrapper.style.cssText = 'margin-bottom:16px; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;';

            const introHeader = document.createElement('div');
            introHeader.style.cssText = 'padding:12px; background:#f8fafc; display:flex; align-items:flex-start; gap:10px; cursor:pointer;';
            introHeader.innerHTML = `
                <input type="checkbox" id="exchange_cb_0" data-index="0" style="margin-top:3px; cursor:pointer;" onchange="toggleExchangeCritique(0)">
                <div style="flex:1; min-width:0;">
                    <strong style="color:#1e293b;">Introduction</strong>
                    <span style="display:inline-block; background:#0891b2; color:#fff; font-size:0.7em; font-weight:600; padding:1px 7px; border-radius:9px; margin-left:6px; vertical-align:middle;">INTRODUCTION</span>
                    <div style="font-size:0.85em; color:#64748b; margin-top:4px; white-space:pre-wrap;">${escapeHtml(truncate(intro.content, 120))}</div>
                </div>
            `;
            introHeader.onclick = function(e) {
                if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
                    const cb = document.getElementById('exchange_cb_0');
                    cb.checked = !cb.checked;
                    toggleExchangeCritique(0);
                }
            };

            const introFormDiv = document.createElement('div');
            introFormDiv.id = 'exchange_form_0';
            introFormDiv.style.cssText = 'display:none; padding:16px; border-top:1px solid #e2e8f0;';
            introFormDiv.innerHTML = buildIntroductionCritiqueFormHTML(intro);

            introWrapper.appendChild(introHeader);
            introWrapper.appendChild(introFormDiv);
            exchangeList.appendChild(introWrapper);
        }

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
            const classifierBadge = exchange.classification_status === 'failed'
                ? `<span style="display:inline-block; background:#dc2626; color:#fff; font-size:0.65em; font-weight:600; padding:1px 7px; border-radius:9px; margin-left:5px; vertical-align:middle;">CLASSIFIER FAILED</span>`
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
                    <span style="display:inline-block; background:${badgeColor}; color:#fff; font-size:0.7em; font-weight:600; padding:1px 7px; border-radius:9px; margin-left:6px; vertical-align:middle;">${badgeLabel}</span>${intentBadge}${classifierBadge}${timeLabel}
                    <div style="font-size:0.85em; color:#64748b; margin-top:4px;">
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
            <div style="font-weight:bold; color:#475569; margin-bottom:6px;">Child Response</div>
            <div style="background:#fefce8; padding:8px; border-radius:4px; font-size:0.9em; margin-bottom:4px; white-space:pre-wrap;">${escapeHtml(exchange.child_response)}</div>
            <div style="font-size:0.78em; color:#64748b; margin-bottom:8px; display:flex; gap:12px;">
                ${exchange.intent_type ? `<span>Intent: <strong>${exchange.intent_type}</strong></span>` : ''}
                ${exchange.classification_status === 'failed' ? `<span>Classifier: <strong>FAILED</strong> (${escapeHtml(exchange.classification_failure_reason || 'unknown')})</span>` : ''}
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
 * Build HTML for the Introduction critique form (index 0).
 * Shows only "Introduction Content" (model response) and a conclusion textarea.
 */
function buildIntroductionCritiqueFormHTML(introduction) {
    return `
        <div style="margin-bottom:16px;">
            <div style="font-weight:bold; color:#475569; margin-bottom:6px;">Introduction Content</div>
            <div style="background:#f0fdf4; padding:8px; border-radius:4px; font-size:0.9em; margin-bottom:8px; white-space:pre-wrap;">${escapeHtml(introduction.content || '')}</div>
            <div style="display:flex; gap:8px;">
                <div style="flex:1;"><label style="font-size:0.8em; color:#64748b;">What is expected</label><textarea id="mr_exp_0" rows="2" style="width:100%; box-sizing:border-box; padding:6px; border:1px solid #cbd5e1; border-radius:4px; font-family:inherit; resize:vertical;" placeholder="How should the introduction have been written?"></textarea></div>
                <div style="flex:1;"><label style="font-size:0.8em; color:#64748b;">Why is it problematic</label><textarea id="mr_prob_0" rows="2" style="width:100%; box-sizing:border-box; padding:6px; border:1px solid #cbd5e1; border-radius:4px; font-family:inherit; resize:vertical;" placeholder="What's wrong with this introduction?"></textarea></div>
            </div>
        </div>
        <div>
            <label style="font-weight:bold; color:#475569; font-size:0.9em;">Conclusion</label>
            <textarea id="ec_concl_0" rows="2" style="width:100%; box-sizing:border-box; padding:6px; border:1px solid #cbd5e1; border-radius:4px; font-family:inherit; resize:vertical; margin-top:4px;" placeholder="Summary of issues with this introduction..."></textarea>
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
            ['mr_exp_', 'mr_prob_', 'ec_concl_'].forEach(prefix => {
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

        const expected   = (document.getElementById('mr_exp_'   + idx) || {}).value || '';
        const problem    = (document.getElementById('mr_prob_'  + idx) || {}).value || '';
        const conclusion = (document.getElementById('ec_concl_' + idx) || {}).value || '';

        // Skip exchanges where the user checked the box but wrote no critique
        if (!expected.trim() && !problem.trim() && !conclusion.trim()) return;

        exchangeCritiques.push({
            exchange_index: idx,
            model_response_expected: expected,
            model_response_problem:  problem,
            conclusion:              conclusion
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
