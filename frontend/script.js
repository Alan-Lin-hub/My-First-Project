// API base URL - use relative path to work from any host
const API_URL = '/api';
const TOKEN_KEY = 'cma_token';

// Global state
let currentSessionId = null;
let currentRole = null;

// DOM elements
let chatMessages, chatInput, sendButton, totalCourses, courseTitles;

// ---- Token helpers ----
function getToken() { return localStorage.getItem(TOKEN_KEY); }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

// fetch wrapper: attaches the Bearer token and bounces to login on 401
async function authFetch(url, options = {}) {
    const opts = { ...options, headers: { ...(options.headers || {}) } };
    const token = getToken();
    if (token) opts.headers['Authorization'] = `Bearer ${token}`;
    const response = await fetch(url, opts);
    if (response.status === 401) {
        clearToken();
        showLogin('登录已过期，请重新登录');
        throw new Error('Not authenticated');
    }
    return response;
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Get DOM elements after page loads
    chatMessages = document.getElementById('chatMessages');
    chatInput = document.getElementById('chatInput');
    sendButton = document.getElementById('sendButton');
    totalCourses = document.getElementById('totalCourses');
    courseTitles = document.getElementById('courseTitles');

    setupEventListeners();
    setupUploadListeners();
    setupAuthListeners();
    checkAuth();
});

// ---- Authentication ----
function setupAuthListeners() {
    const loginForm = document.getElementById('loginForm');
    if (loginForm) loginForm.addEventListener('submit', handleLogin);
    const logoutButton = document.getElementById('logoutButton');
    if (logoutButton) logoutButton.addEventListener('click', logout);
}

async function checkAuth() {
    const token = getToken();
    if (!token) { showLogin(); return; }
    try {
        const response = await fetch(`${API_URL}/auth/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!response.ok) { clearToken(); showLogin(); return; }
        showApp(await response.json());
    } catch (e) {
        showLogin();
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const errorEl = document.getElementById('loginError');
    const submitBtn = document.getElementById('loginSubmit');
    errorEl.textContent = '';
    submitBtn.disabled = true;
    try {
        const response = await fetch(`${API_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || '登录失败');
        setToken(data.access_token);
        showApp({ username: data.username, role: data.role });
    } catch (err) {
        errorEl.textContent = err.message;
    } finally {
        submitBtn.disabled = false;
    }
}

function logout() {
    clearToken();
    currentRole = null;
    showLogin();
}

function showLogin(message) {
    document.getElementById('loginView').style.display = 'flex';
    document.getElementById('appView').style.display = 'none';
    const errorEl = document.getElementById('loginError');
    if (errorEl) errorEl.textContent = message || '';
    const pw = document.getElementById('loginPassword');
    if (pw) pw.value = '';
}

function showApp(user) {
    currentRole = user.role;
    document.getElementById('loginView').style.display = 'none';
    document.getElementById('appView').style.display = '';  // revert to stylesheet layout
    document.getElementById('currentUser').textContent = `${user.username} (${user.role})`;
    // Only admins see the upload UI (the server enforces this regardless)
    const addCourse = document.getElementById('addCourseSection');
    if (addCourse) addCourse.style.display = (user.role === 'admin') ? '' : 'none';
    // Initialize chat + course list now that we are authenticated
    createNewSession();
    loadCourseStats();
}

// Event Listeners
function setupEventListeners() {
    // Chat functionality
    sendButton.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });
    
    
    // Suggested questions
    document.querySelectorAll('.suggested-item').forEach(button => {
        button.addEventListener('click', (e) => {
            const question = e.target.getAttribute('data-question');
            chatInput.value = question;
            sendMessage();
        });
    });
}


// Course Upload
function setupUploadListeners() {
    const uploadButton = document.getElementById('uploadButton');
    const fileInput = document.getElementById('courseFileInput');
    const status = document.getElementById('uploadStatus');
    if (!uploadButton || !fileInput) return;

    uploadButton.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', async () => {
        const file = fileInput.files[0];
        if (!file) return;

        status.textContent = `Uploading "${file.name}"…`;
        status.className = 'upload-status loading';
        uploadButton.disabled = true;

        try {
            const formData = new FormData();
            formData.append('file', file);

            const response = await authFetch(`${API_URL}/courses/upload`, {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Upload failed');

            const verb = data.replaced ? 'Updated' : 'Added';
            status.textContent = `${verb}: ${data.course_title} — ${data.lessons} lessons, ${data.chunks} chunks`;
            status.className = 'upload-status success';

            // Refresh the course list so the new/updated course shows up
            await loadCourseStats();
        } catch (error) {
            status.textContent = `Error: ${error.message}`;
            status.className = 'upload-status error';
        } finally {
            uploadButton.disabled = false;
            fileInput.value = '';
        }
    });
}

// Chat Functions
async function sendMessage() {
    const query = chatInput.value.trim();
    if (!query) return;

    // Disable input
    chatInput.value = '';
    chatInput.disabled = true;
    sendButton.disabled = true;

    // Add user message
    addMessage(query, 'user');

    // Add loading message - create a unique container for it
    const loadingMessage = createLoadingMessage();
    chatMessages.appendChild(loadingMessage);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
        const response = await authFetch(`${API_URL}/query`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                query: query,
                session_id: currentSessionId
            })
        });

        if (!response.ok) {
            // Surface the backend's error detail (e.g. missing API key) instead of a generic message
            let detail = 'Query failed';
            try {
                const errData = await response.json();
                if (errData && errData.detail) detail = errData.detail;
            } catch (e) { /* response had no JSON body */ }
            throw new Error(detail);
        }

        const data = await response.json();
        
        // Update session ID if new
        if (!currentSessionId) {
            currentSessionId = data.session_id;
        }

        // Replace loading message with response
        loadingMessage.remove();
        addMessage(data.answer, 'assistant', data.sources);

    } catch (error) {
        // Replace loading message with error
        loadingMessage.remove();
        addMessage(`Error: ${error.message}`, 'assistant');
    } finally {
        chatInput.disabled = false;
        sendButton.disabled = false;
        chatInput.focus();
    }
}

function createLoadingMessage() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    messageDiv.innerHTML = `
        <div class="message-content">
            <div class="loading">
                <span></span>
                <span></span>
                <span></span>
            </div>
        </div>
    `;
    return messageDiv;
}

function addMessage(content, type, sources = null, isWelcome = false) {
    const messageId = Date.now();
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}${isWelcome ? ' welcome-message' : ''}`;
    messageDiv.id = `message-${messageId}`;
    
    // Convert markdown to HTML for assistant messages
    const displayContent = type === 'assistant' ? marked.parse(content) : escapeHtml(content);
    
    let html = `<div class="message-content">${displayContent}</div>`;
    
    if (sources && sources.length > 0) {
        html += `
            <details class="sources-collapsible">
                <summary class="sources-header">Sources</summary>
                <div class="sources-content">${sources.join(', ')}</div>
            </details>
        `;
    }
    
    messageDiv.innerHTML = html;
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    return messageId;
}

// Helper function to escape HTML for user messages
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Removed removeMessage function - no longer needed since we handle loading differently

async function createNewSession() {
    currentSessionId = null;
    chatMessages.innerHTML = '';
    addMessage('Welcome to the Course Materials Assistant! I can help you with questions about courses, lessons and specific content. What would you like to know?', 'assistant', null, true);
}

// Load course statistics
async function loadCourseStats() {
    try {
        console.log('Loading course stats...');
        const response = await authFetch(`${API_URL}/courses`);
        if (!response.ok) throw new Error('Failed to load course stats');
        
        const data = await response.json();
        console.log('Course data received:', data);
        
        // Update stats in UI
        if (totalCourses) {
            totalCourses.textContent = data.total_courses;
        }
        
        // Update course titles
        if (courseTitles) {
            if (data.course_titles && data.course_titles.length > 0) {
                courseTitles.innerHTML = data.course_titles
                    .map(title => `<div class="course-title-item">${title}</div>`)
                    .join('');
            } else {
                courseTitles.innerHTML = '<span class="no-courses">No courses available</span>';
            }
        }
        
    } catch (error) {
        console.error('Error loading course stats:', error);
        // Set default values on error
        if (totalCourses) {
            totalCourses.textContent = '0';
        }
        if (courseTitles) {
            courseTitles.innerHTML = '<span class="error">Failed to load courses</span>';
        }
    }
}