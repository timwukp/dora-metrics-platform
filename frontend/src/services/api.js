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

// Components pass either `{ days }` for "last N days" or `{ start, end }` for
// an explicit window (e.g. a Sprint). `buildRange` flattens that to the query
// params the backend expects, dropping anything undefined.
function buildRange({ days, start, end }) {
  if (start && end) return { start, end }
  return { days }
}

export const api = {
  getDoraSummary: (repo, range) =>
    fetchJson(`${BASE_URL}/metrics/dora`, { repo, ...buildRange(range) }),

  getDeployFrequency: (repo, range) =>
    fetchJson(`${BASE_URL}/metrics/deploy-freq`, { repo, ...buildRange(range) }),

  getLeadTime: (repo, range) =>
    fetchJson(`${BASE_URL}/metrics/lead-time`, { repo, ...buildRange(range) }),

  getChangeFailRate: (repo, range) =>
    fetchJson(`${BASE_URL}/metrics/change-fail`, { repo, ...buildRange(range) }),

  getMttr: (repo, range) =>
    fetchJson(`${BASE_URL}/metrics/mttr`, { repo, ...buildRange(range) }),

  getClaudeCode: (range) =>
    fetchJson(`${BASE_URL}/metrics/claude-code`, buildRange(range)),

  getTimeline: (repo, days = 90) =>
    fetchJson(`${BASE_URL}/metrics/timeline`, { repo, days }),

  getReviews: (repo, range) =>
    fetchJson(`${BASE_URL}/reviews`, { repo, ...buildRange(range) }),

  getRepos: () =>
    fetchJson(`${BASE_URL}/repos`),

  getSprints: () =>
    fetchJson(`${BASE_URL}/sprints`),

  getLevelHistory: (repo, weeks = 26) =>
    fetchJson(`${BASE_URL}/metrics/level-history`, { repo, weeks }),

  // Returns Markdown text directly (not JSON). Used by the retro export
  // button to download a .md file. We bypass `fetchJson` here because the
  // response isn't application/json.
  getRetroMarkdown: async (repo, range, sprintLabel) => {
    const url = new URL(`${BASE_URL}/reports/retro`, window.location.origin)
    if (repo) url.searchParams.set('repo', repo)
    if (range?.start) url.searchParams.set('start', range.start)
    if (range?.end) url.searchParams.set('end', range.end)
    if (range?.days) url.searchParams.set('days', range.days)
    if (sprintLabel) url.searchParams.set('sprint_label', sprintLabel)
    const resp = await fetch(url)
    if (!resp.ok) throw new ApiError(`Retro export failed: HTTP ${resp.status}`, resp.status)
    return resp.text()
  },

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
