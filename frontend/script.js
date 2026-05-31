// API base URL - use relative path to work from any host
const API_URL = '/api';
const TOKEN_KEY = 'cma_token';

// Global state
let currentSessionId = null;
let currentRole = null;
let currentUsername = null;

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
    setupPasswordListeners();
    setupAdminListeners();
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
    currentUsername = user.username;
    document.getElementById('loginView').style.display = 'none';
    document.getElementById('appView').style.display = '';  // revert to stylesheet layout
    document.getElementById('currentUser').textContent = `${user.username} (${user.role})`;
    // Only admins see the upload + user-management UI (the server enforces this regardless)
    const isAdmin = user.role === 'admin';
    const addCourse = document.getElementById('addCourseSection');
    if (addCourse) addCourse.style.display = isAdmin ? '' : 'none';
    const userMgmt = document.getElementById('userMgmtSection');
    if (userMgmt) userMgmt.style.display = isAdmin ? '' : 'none';
    if (isAdmin) loadUsers();
    // Initialize chat + course list now that we are authenticated
    createNewSession();
    loadCourseStats();
}

// ---- Change password (all users) ----
function setupPasswordListeners() {
    const btn = document.getElementById('changePwButton');
    if (btn) btn.addEventListener('click', changePassword);
}

async function changePassword() {
    const oldPw = document.getElementById('oldPassword').value;
    const newPw = document.getElementById('newPassword').value;
    const confirmPw = document.getElementById('confirmPassword').value;
    const status = document.getElementById('changePwStatus');
    const btn = document.getElementById('changePwButton');

    if (!oldPw || !newPw) { status.textContent = '请填写当前密码和新密码'; status.className = 'upload-status error'; return; }
    if (newPw.length < 6) { status.textContent = '新密码至少 6 位'; status.className = 'upload-status error'; return; }
    if (newPw !== confirmPw) { status.textContent = '两次输入的新密码不一致'; status.className = 'upload-status error'; return; }

    status.textContent = '提交中…'; status.className = 'upload-status loading'; btn.disabled = true;
    try {
        const response = await authFetch(`${API_URL}/auth/change-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_password: oldPw, new_password: newPw })
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || '修改失败');
        }
        status.textContent = '密码修改成功'; status.className = 'upload-status success';
        document.getElementById('oldPassword').value = '';
        document.getElementById('newPassword').value = '';
        document.getElementById('confirmPassword').value = '';
    } catch (err) {
        status.textContent = err.message; status.className = 'upload-status error';
    } finally {
        btn.disabled = false;
    }
}

// ---- Admin: user management ----
function setupAdminListeners() {
    const btn = document.getElementById('createUserButton');
    if (btn) btn.addEventListener('click', createUser);
}

async function loadUsers() {
    const listEl = document.getElementById('userList');
    if (!listEl) return;
    try {
        const response = await authFetch(`${API_URL}/admin/users`);
        if (!response.ok) throw new Error('加载用户失败');
        const users = await response.json();
        listEl.innerHTML = users.map(u => `
            <div class="user-row">
                <span class="user-name">${escapeHtml(u.username)} <span class="user-role">${u.role}</span></span>
                <span class="user-actions">
                    <button class="user-action" data-action="reset" data-id="${u.id}" data-name="${escapeHtml(u.username)}">重置密码</button>
                    <button class="user-action danger" data-action="delete" data-id="${u.id}" data-name="${escapeHtml(u.username)}">删除</button>
                </span>
            </div>
        `).join('');
        listEl.querySelectorAll('.user-action').forEach(b => {
            b.addEventListener('click', () => {
                const id = b.getAttribute('data-id');
                const name = b.getAttribute('data-name');
                if (b.getAttribute('data-action') === 'delete') deleteUser(id, name);
                else resetUserPassword(id, name);
            });
        });
    } catch (e) {
        listEl.innerHTML = '<span class="no-courses">加载用户失败</span>';
    }
}

async function createUser() {
    const username = document.getElementById('newUsername').value.trim();
    const password = document.getElementById('newUserPassword').value;
    const role = document.getElementById('newUserRole').value;
    const status = document.getElementById('createUserStatus');
    const btn = document.getElementById('createUserButton');

    if (!username || !password) { status.textContent = '请填写用户名和密码'; status.className = 'upload-status error'; return; }
    if (password.length < 6) { status.textContent = '密码至少 6 位'; status.className = 'upload-status error'; return; }

    status.textContent = '创建中…'; status.className = 'upload-status loading'; btn.disabled = true;
    try {
        const response = await authFetch(`${API_URL}/admin/users`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, role })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || '创建失败');
        status.textContent = `已创建：${data.username} (${data.role})`; status.className = 'upload-status success';
        document.getElementById('newUsername').value = '';
        document.getElementById('newUserPassword').value = '';
        await loadUsers();
    } catch (err) {
        status.textContent = err.message; status.className = 'upload-status error';
    } finally {
        btn.disabled = false;
    }
}

async function deleteUser(id, name) {
    if (!confirm(`确定删除用户 "${name}"？`)) return;
    try {
        const response = await authFetch(`${API_URL}/admin/users/${id}`, { method: 'DELETE' });
        if (!response.ok && response.status !== 204) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || '删除失败');
        }
        await loadUsers();
    } catch (err) {
        alert(err.message);
    }
}

async function resetUserPassword(id, name) {
    const newPw = prompt(`为用户 "${name}" 设置新密码（≥6位）：`);
    if (newPw === null) return;
    if (newPw.length < 6) { alert('密码至少 6 位'); return; }
    try {
        const response = await authFetch(`${API_URL}/admin/users/${id}/password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_password: newPw })
        });
        if (!response.ok && response.status !== 204) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || '重置失败');
        }
        alert(`已重置 "${name}" 的密码`);
    } catch (err) {
        alert(err.message);
    }
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