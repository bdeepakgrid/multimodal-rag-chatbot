// Central API client. Every backend call goes through here so there is exactly
// one place that knows the base path.
const BASE = '/api/v1';

let currentAuthToken = localStorage.getItem('auth_token') || null;
let currentUser = null;
try {
  const savedUser = localStorage.getItem('auth_user');
  if (savedUser) currentUser = JSON.parse(savedUser);
} catch {
  currentUser = null;
}

export function setAuthToken(token, user = null) {
  currentAuthToken = token;
  currentUser = user;
  if (token) {
    localStorage.setItem('auth_token', token);
  } else {
    localStorage.removeItem('auth_token');
  }
  if (user) {
    localStorage.setItem('auth_user', JSON.stringify(user));
  } else {
    localStorage.removeItem('auth_user');
  }
}

export function getAuthToken() {
  return currentAuthToken;
}

export function getCurrentUser() {
  return currentUser;
}

export function setApiKey(key) {
  setAuthToken(key, { username: 'key_user', role: key.includes('tech') ? 'technician' : (key.includes('reviewer') ? 'reviewer' : 'admin') });
}

export function getApiKey() {
  return currentAuthToken;
}

function authHeaders(customHeaders = {}) {
  const token = getAuthToken();
  return {
    ...customHeaders,
    'Authorization': `Bearer ${token}`,
    'API-Key': token,
  };
}

async function handle(response) {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON, keep generic status
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function loginUser(username, password) {
  const response = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await handle(response);
  setAuthToken(data.access_token, data.user);
  return data;
}

export async function signupUser(username, email, password, role) {
  const response = await fetch(`${BASE}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password, role }),
  });
  const data = await handle(response);
  setAuthToken(data.access_token, data.user);
  return data;
}

export function logoutUser() {
  setAuthToken(null, null);
}

export async function fetchMe() {
  const response = await fetch(`${BASE}/auth/me`, {
    headers: authHeaders(),
  });
  return handle(response);
}

export async function sendChatMessage(query, sessionId, image = null) {
  const body = image ? new FormData() : null;
  if (body) {
    body.append('query', query);
    body.append('session_id', sessionId);
    body.append('image', image);
  }
  const response = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: body ? authHeaders() : authHeaders({ 'Content-Type': 'application/json' }),
    body: body || JSON.stringify({ query, session_id: sessionId }),
  });
  return handle(response);
}

export async function listCollections() {
  const response = await fetch(`${BASE}/collections`, {
    headers: authHeaders(),
  });
  return handle(response);
}

export async function listAllDocuments() {
  const response = await fetch(`${BASE}/collections/documents`, {
    headers: authHeaders(),
  });
  return handle(response);
}

export async function getCollectionStats(tenantId) {
  const response = await fetch(`${BASE}/collections/${encodeURIComponent(tenantId)}/stats`, {
    headers: authHeaders(),
  });
  return handle(response);
}

export async function ingestFiles(tenantId, files, tags) {
  const formData = new FormData();
  formData.append('tenant_id', tenantId || 'default');
  if (tags && tags.trim()) formData.append('tags', tags.trim());
  files.forEach((file) => formData.append('files', file));

  const response = await fetch(`${BASE}/ingest`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  return handle(response);
}

export async function deleteDocument(tenantId, sourceFile) {
  const response = await fetch(
    `${BASE}/collections/${encodeURIComponent(tenantId)}/document/${encodeURIComponent(sourceFile)}`,
    {
      method: 'DELETE',
      headers: authHeaders(),
    }
  );
  return handle(response);
}

export function rawDocumentUrl(tenantId, sourceFile) {
  return `${BASE}/collections/${encodeURIComponent(tenantId)}/document/${encodeURIComponent(sourceFile)}/raw`;
}

export async function listUsers() {
  const response = await fetch(`${BASE}/auth/users`, {
    headers: authHeaders(),
  });
  return handle(response);
}

export async function updateUserRole(userId, role) {
  const response = await fetch(`${BASE}/auth/users/${encodeURIComponent(userId)}/role`, {
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ role }),
  });
  return handle(response);
}
