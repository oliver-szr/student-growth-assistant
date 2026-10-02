const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export function readableDetail(detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === 'string') return item
      if (!item || typeof item !== 'object') return 'Invalid value'
      const location = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : ''
      const message = typeof item.msg === 'string' ? item.msg : 'Invalid value'
      return location ? `${location}: ${message}` : message
    }).join('; ')
  }
  if (detail && typeof detail.message === 'string') return detail.message
  return ''
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(readableDetail(detail) || `Request failed (${status}).`)
    this.name = 'ApiError'
    this.status = status
    this.code = typeof detail?.code === 'string' ? detail.code : ''
    this.detail = detail
  }
}

async function request(path, options = {}, timeoutMs = 15000) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      signal: controller.signal,
      headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    })

    const body = await response.json()
    if (!response.ok) {
      throw new ApiError(response.status, body?.detail)
    }
    return body
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error('The request timed out. Reload the latest state before retrying a change.')
    }
    if (error instanceof TypeError) {
      throw new Error('Could not connect to the backend. Check that it is running.')
    }
    if (error instanceof SyntaxError) {
      throw new Error('The backend returned an unreadable response.')
    }
    throw error
  } finally {
    clearTimeout(timeout)
  }
}

export const getTasks = () => request('/api/tasks')
export const createTask = (data) => request('/api/tasks', { method: 'POST', body: JSON.stringify(data) })
export const updateTask = (id, data) => request(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(data) })

export const getTimeRules = () => request('/api/time-rules')
export const createTimeRule = (data) => request('/api/time-rules', { method: 'POST', body: JSON.stringify(data) })
export const updateTimeRule = (id, data) => request(`/api/time-rules/${id}`, { method: 'PATCH', body: JSON.stringify(data) })

// Allow the backend's bounded 20-second provider request to finish first.
export const parseConstraint = (text) => request('/api/constraints/parse', { method: 'POST', body: JSON.stringify({ text }) }, 25000)

export const createCandidatePlan = (data) => request('/api/plans/candidates', { method: 'POST', body: JSON.stringify(data) })
export const getPlan = (id) => request(`/api/plans/${id}`)
export const getConfirmedPlan = (weekStart) => request(`/api/plans/confirmed?week_start=${encodeURIComponent(weekStart)}`)
export const confirmPlan = (id) => request(`/api/plans/${id}/confirm`, { method: 'POST' })

export const explainCandidate = (id, language = 'en') => request(`/api/plans/${id}/explanation`, { method: 'POST', body: JSON.stringify({ language }) }, 25000)
