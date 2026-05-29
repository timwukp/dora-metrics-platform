// Thin wrapper around fetch.
//
// Why a custom error class? Components want to distinguish "backend has not
// finished starting yet" (503) from "the API is permanently configured wrong"
// (404, 401) — a plain `Error` only carries a message string and forces every
// consumer to parse it. `ApiError.status` lets callers branch cleanly.
//
// Why `getApiKey()` from sessionStorage? Mutating endpoints (collect, etc.)
// require X-API-Key. We do not put the key in source — operators set it once
// per browser via `sessionStorage.setItem('dora.api_key', '...')` and the
// helper picks it up. Cookies were rejected because allow_credentials=false.
const BASE_URL = '/api/v1'

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function getApiKey() {
  try {
    return window.sessionStorage?.getItem('dora.api_key') || null
  } catch {
    return null
  }
}

async function fetchJson(path, params = {}, init = {}) {
  const url = new URL(path, window.location.origin)
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined) url.searchParams.set(k, v)
  })

  let resp
  try {
    resp = await fetch(url, init)
  } catch (e) {
    // Network-level failure (DNS, offline, CORS preflight rejected, etc.).
    throw new ApiError(`Network error: ${e.message}`, 0, null)
  }

  let body = null
  const contentType = resp.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    try { body = await resp.json() } catch { body = null }
  }

  if (!resp.ok) {
    const detail = body?.detail || `HTTP ${resp.status}`
    throw new ApiError(detail, resp.status, body)
  }
  return body
}

export const api = {
  getDoraSummary: (repo, days = 30) =>
    fetchJson(`${BASE_URL}/metrics/dora`, { repo, days }),

  getDeployFrequency: (repo, days = 30) =>
    fetchJson(`${BASE_URL}/metrics/deploy-freq`, { repo, days }),

  getLeadTime: (repo, days = 30) =>
    fetchJson(`${BASE_URL}/metrics/lead-time`, { repo, days }),

  getChangeFailRate: (repo, days = 30) =>
    fetchJson(`${BASE_URL}/metrics/change-fail`, { repo, days }),

  getMttr: (repo, days = 30) =>
    fetchJson(`${BASE_URL}/metrics/mttr`, { repo, days }),

  getClaudeCode: (days = 30) =>
    fetchJson(`${BASE_URL}/metrics/claude-code`, { days }),

  getTimeline: (repo, days = 90) =>
    fetchJson(`${BASE_URL}/metrics/timeline`, { repo, days }),

  getReviews: (repo, days = 30) =>
    fetchJson(`${BASE_URL}/reviews`, { repo, days }),

  getRepos: () =>
    fetchJson(`${BASE_URL}/repos`),

  triggerCollection: () => {
    const key = getApiKey()
    if (!key) {
      return Promise.reject(new ApiError(
        'X-API-Key not set. Run: sessionStorage.setItem("dora.api_key","<key>")',
        401, null,
      ))
    }
    return fetchJson(`${BASE_URL}/collect/github`, {}, {
      method: 'POST',
      headers: { 'X-API-Key': key },
    })
  },
}
