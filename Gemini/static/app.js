// Child Learning Assistant - Web Demo JavaScript
// Handles all interactions with the Flask API

const API_BASE = window.location.origin;

// State management
let sessionId = null;
let currentObject = null;
let currentCategory = null;
let correctCount = 0;
let masteryThreshold = 4;

// DOM Elements
const setupForm = document.getElementById('setupForm');
const chatContainer = document.getElementById('chatContainer');
const loading = document.getElementById('loading');
const startBtn = document.getElementById('startBtn');
const sendBtn = document.getElementById('sendBtn');
const newSessionBtn = document.getElementById('newSessionBtn');
const childInput = document.getElementById('childInput');
const chatMessages = document.getElementById('chatMessages');
const sessionInfo = document.getElementById('sessionInfo');
const progressFill = document.getElementById('progressFill');
const objectNameInput = document.getElementById('objectName');
const classifyingIndicator = document.getElementById('classifyingIndicator');
const categoryRecommendation = document.getElementById('categoryRecommendation');
const level2CategoryInput = document.getElementById('level2Category');

// Classification state
let recommendedCategory = null;

// Event Listeners
startBtn.addEventListener('click', startSession);
sendBtn.addEventListener('click', sendResponse);
newSessionBtn.addEventListener('click', resetToSetup);
childInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendResponse();
});
objectNameInput.addEventListener('blur', classifyObject);
objectNameInput.addEventListener('input', () => {
    // Clear recommendation when user modifies object name
    categoryRecommendation.style.display = 'none';
    recommendedCategory = null;
});

// Classify object using LLM
async function classifyObject() {
    const objectName = objectNameInput.value.trim();

    // Don't classify if empty or if user already has a category entered
    if (!objectName) {
        return;
    }

    try {
        // Show classifying indicator
        classifyingIndicator.style.display = 'block';
        categoryRecommendation.style.display = 'none';

        const response = await fetch(`${API_BASE}/api/classify`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                object_name: objectName
            })
        });

        const data = await response.json();
        console.log('[DEBUG] Classification response:', data);

        classifyingIndicator.style.display = 'none';

        if (data.success && data.recommended_category) {
            recommendedCategory = data.recommended_category;
            showCategoryRecommendation(objectName, data.category_display, data.recommended_category);
        } else {
            // Could not classify - show message
            showNoClassificationMessage();
        }
    } catch (error) {
        console.error('Classification error:', error);
        classifyingIndicator.style.display = 'none';
    }
}

// Show category recommendation
function showCategoryRecommendation(objectName, categoryDisplay, category) {
    categoryRecommendation.innerHTML = `
        <div class="recommendation">
            <h4>💡 Recommendation</h4>
            <p>We think "${objectName}" belongs to the "${categoryDisplay}" category (${category})</p>
            <div class="recommendation-buttons">
                <button class="accept-btn" onclick="acceptRecommendation()">✓ Use This Category</button>
                <button onclick="declineRecommendation()">✗ Enter Manually</button>
            </div>
        </div>
    `;
    categoryRecommendation.style.display = 'block';
}

// Show message when classification fails
function showNoClassificationMessage() {
    categoryRecommendation.innerHTML = `
        <div class="recommendation" style="background: linear-gradient(135deg, #ffa726 0%, #fb8c00 100%);">
            <h4>⚠️ Could Not Classify</h4>
            <p>We couldn't automatically classify this object. Please enter a category manually below.</p>
        </div>
    `;
    categoryRecommendation.style.display = 'block';
    // Auto-hide after 3 seconds
    setTimeout(() => {
        categoryRecommendation.style.display = 'none';
    }, 3000);
}

// Accept the recommended category
function acceptRecommendation() {
    if (recommendedCategory) {
        level2CategoryInput.value = recommendedCategory;
        categoryRecommendation.innerHTML = `
            <div class="recommendation" style="background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);">
                <h4>✓ Category Selected</h4>
                <p>Using recommended category: ${recommendedCategory}</p>
            </div>
        `;
        // Auto-hide after 2 seconds
        setTimeout(() => {
            categoryRecommendation.style.display = 'none';
        }, 2000);
    }
}

// Decline the recommendation
function declineRecommendation() {
    categoryRecommendation.style.display = 'none';
    level2CategoryInput.focus();
}

// Start a new learning session
async function startSession() {
    const objectName = document.getElementById('objectName').value.trim();
    const age = document.getElementById('age').value;
    const level2Category = document.getElementById('level2Category').value.trim();
    const level3Category = document.getElementById('level3Category').value.trim();

    if (!objectName) {
        showError('Please enter an object name');
        return;
    }

    // Derive category from most specific level
    const category = level3Category || level2Category || 'object';

    const requestBody = {
        object_name: objectName,
        category: category,
    };

    // Add optional parameters
    if (age) {
        requestBody.age = parseInt(age);
    }
    if (level2Category) {
        requestBody.level2_category = level2Category;
    }
    if (level3Category) {
        requestBody.level3_category = level3Category;
    }

    try {
        showLoading();

        const response = await fetch(`${API_BASE}/api/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });

        const data = await response.json();
        console.log('[DEBUG] Start response:', data);

        if (data.success) {
            sessionId = data.session_id;
            currentObject = data.object;
            currentCategory = data.category;
            correctCount = 0;

            // Update UI - switch to chat first (clears old messages)
            switchToChat();
            updateSessionInfo();
            console.log('[DEBUG] Adding initial message:', data.response);
            addMessage('assistant', data.response);
        } else {
            showError(data.error || 'Failed to start session');
        }
    } catch (error) {
        showError('Network error: ' + error.message);
    } finally {
        hideLoading();
    }
}

// Send child's response
async function sendResponse() {
    const childResponse = childInput.value.trim();

    if (!childResponse) {
        return;
    }

    if (!sessionId) {
        showError('No active session');
        return;
    }

    // Add child's message to chat
    addMessage('user', childResponse);
    childInput.value = '';
    childInput.disabled = true;
    sendBtn.disabled = true;

    try {
        showLoading();

        const response = await fetch(`${API_BASE}/api/continue`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: sessionId,
                child_response: childResponse
            })
        });

        const data = await response.json();
        console.log('[DEBUG] Continue response:', data);

        if (data.success) {
            correctCount = data.correct_count;
            updateProgress();

            // Add assistant's response
            console.log('[DEBUG] Adding message:', data.response);
            addMessage('assistant', data.response);

            // Check for mastery
            if (data.mastery_achieved) {
                showMasteryBadge();
                childInput.disabled = true;
                sendBtn.disabled = true;
            } else {
                childInput.disabled = false;
                sendBtn.disabled = false;
                childInput.focus();
            }
        } else {
            showError(data.error || 'Failed to continue conversation');
            childInput.disabled = false;
            sendBtn.disabled = false;
        }
    } catch (error) {
        showError('Network error: ' + error.message);
        childInput.disabled = false;
        sendBtn.disabled = false;
    } finally {
        hideLoading();
    }
}

// Add message to chat
function addMessage(role, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const label = document.createElement('div');
    label.className = 'message-label';
    label.textContent = role === 'assistant' ? '🤖 Assistant' : '👦 You';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = content;

    messageDiv.appendChild(label);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);

    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Update session info
function updateSessionInfo() {
    sessionInfo.innerHTML = `
        <strong>Object:</strong> ${currentObject} <br>
        <strong>Category:</strong> ${currentCategory} <br>
        <strong>Session ID:</strong> ${sessionId.substring(0, 8)}...
    `;
}

// Update progress bar
function updateProgress() {
    const percentage = (correctCount / masteryThreshold) * 100;
    progressFill.style.width = `${percentage}%`;
    progressFill.textContent = `${correctCount}/${masteryThreshold}`;
}

// Show mastery achievement badge
function showMasteryBadge() {
    const badge = document.createElement('div');
    badge.className = 'mastery-badge';
    badge.innerHTML = `
        <h2>🎉 MASTERY ACHIEVED! 🎉</h2>
        <p>You answered ${correctCount} questions correctly!</p>
        <p>Amazing job! You've mastered the ${currentObject}!</p>
    `;
    chatMessages.appendChild(badge);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Switch to chat view
function switchToChat() {
    setupForm.classList.remove('active');
    chatContainer.classList.add('active');
    chatMessages.innerHTML = '';
    updateProgress();
    childInput.focus();
}

// Reset to setup form
function resetToSetup() {
    sessionId = null;
    currentObject = null;
    currentCategory = null;
    correctCount = 0;
    recommendedCategory = null;

    setupForm.classList.add('active');
    chatContainer.classList.remove('active');

    // Clear inputs
    document.getElementById('objectName').value = '';
    document.getElementById('age').value = '';
    document.getElementById('level2Category').value = '';
    document.getElementById('level3Category').value = '';
    childInput.value = '';
    childInput.disabled = false;
    sendBtn.disabled = false;

    // Clear classification UI
    classifyingIndicator.style.display = 'none';
    categoryRecommendation.style.display = 'none';
}

// Show loading indicator
function showLoading() {
    loading.style.display = 'block';
}

// Hide loading indicator
function hideLoading() {
    loading.style.display = 'none';
}

// Show error message
function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error';
    errorDiv.textContent = '❌ ' + message;

    const content = document.querySelector('.content');
    content.insertBefore(errorDiv, content.firstChild);

    // Remove error after 5 seconds
    setTimeout(() => {
        errorDiv.remove();
    }, 5000);
}

// Initialize
console.log('Child Learning Assistant Web Demo loaded');
console.log('API Base:', API_BASE);
