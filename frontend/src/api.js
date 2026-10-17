import { localizedError } from './localization.js'

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
    super(localizedError(status, detail))
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
      throw new Error('请求超时。请重新加载最新状态，再重试操作。')
    }
    if (error instanceof TypeError) {
      throw new Error('无法连接后端，请检查后端服务是否正在运行。')
    }
    if (error instanceof SyntaxError) {
      throw new Error('后端返回了无法读取的内容，请稍后重试。')
    }
    throw error
  } finally {
    clearTimeout(timeout)
  }
}

export const getTasks = () => request('/api/tasks')
export const createTask = (data) => request('/api/tasks', { method: 'POST', body: JSON.stringify(data) })
export const updateTask = (id, data) => request(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const createTaskBreakdown = data => request('/api/tasks/breakdown-drafts', { method: 'POST', body: JSON.stringify(data) }, 125000)
export const getTaskBreakdowns = () => request('/api/tasks/breakdown-drafts')
export const getTaskBreakdown = id => request(`/api/tasks/breakdown-drafts/${id}`)
export const editTaskBreakdown = (id, data) => request(`/api/tasks/breakdown-drafts/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const confirmTaskBreakdown = (id, version) => request(`/api/tasks/breakdown-drafts/${id}/confirm`, { method: 'POST', body: JSON.stringify({ version }) })
export const discardTaskBreakdown = (id, version) => request(`/api/tasks/breakdown-drafts/${id}/discard`, { method: 'POST', body: JSON.stringify({ version }) })
export const submitTaskFeedback = (id, data) => request(`/api/tasks/${id}/feedback`, { method: 'POST', body: JSON.stringify(data) })
export const getTaskFeedback = (id) => request(`/api/tasks/${id}/feedback`)
export const getTaskGrowthContext = (id) => request(`/api/tasks/${id}/growth-context`)
export const saveTaskGrowthContext = (id, data) => request(`/api/tasks/${id}/growth-context`, { method: 'PUT', body: JSON.stringify(data) })
export const getDurationAdvice = (id) => request(`/api/growth/tasks/${id}/duration-advice`)
export const startWorkSession = (data) => request('/api/work-sessions/start', { method: 'POST', body: JSON.stringify(data) })
export const getCurrentWorkSession = (id) => request(`/api/tasks/${id}/work-sessions/current`)
export const pauseWorkSession = (id) => request(`/api/work-sessions/${id}/pause`, { method: 'POST' })
export const resumeWorkSession = (id) => request(`/api/work-sessions/${id}/resume`, { method: 'POST' })
export const finishWorkSession = (id) => request(`/api/work-sessions/${id}/finish`, { method: 'POST' })

export const getTimeRules = () => request('/api/time-rules')
export const createTimeRule = (data) => request('/api/time-rules', { method: 'POST', body: JSON.stringify(data) })
export const updateTimeRule = (id, data) => request(`/api/time-rules/${id}`, { method: 'PATCH', body: JSON.stringify(data) })

// Allow the backend's bounded 120-second provider request to finish first.
export const parseConstraint = (text) => request('/api/constraints/parse', { method: 'POST', body: JSON.stringify({ text }) }, 125000)

export const createCandidatePlan = (data) => request('/api/plans/candidates', { method: 'POST', body: JSON.stringify(data) })
export const getPlan = (id) => request(`/api/plans/${id}`)
export const getConfirmedPlan = (weekStart) => request(`/api/plans/confirmed?week_start=${encodeURIComponent(weekStart)}`)
export const confirmPlan = (id) => request(`/api/plans/${id}/confirm`, { method: 'POST' })

export const explainCandidate = (id, language = 'zh-CN') => request(`/api/plans/${id}/explanation`, { method: 'POST', body: JSON.stringify({ language }) }, 125000)

export const createAssistantSession=()=>request('/api/assistant/sessions',{method:'POST',body:'{}'})
export const openWorkspaceSession=(scope,week_start)=>request('/api/assistant/sessions/open',{method:'POST',body:JSON.stringify({scope,...(week_start?{week_start}:{})})})
export const confirmGrowthDraft=id=>request(`/api/assistant/drafts/${id}/confirm`,{method:'POST'})
export const discardGrowthDraft=id=>request(`/api/assistant/drafts/${id}/discard`,{method:'POST'})
export const getAssistantSession=id=>request(`/api/assistant/sessions/${id}`)
export const sendAssistantMessage=(id,data)=>request(`/api/assistant/sessions/${id}/messages`,{method:'POST',body:JSON.stringify(data)},125000)
export const previewAssistant=(id,data)=>request(`/api/assistant/proposals/${id}/preview`,{method:'POST',body:JSON.stringify(data)})
export const replanAssistant=(id,target)=>sendAssistantMessage(id,{client_message_id:crypto.randomUUID(),text:target?'重新安排所选任务，尽量保留其他安排':'局部重规划，尽量保留其他安排',replan:true,...(target?{actions:[{op:'update',target,fields:{}}]}:{})})
export const expandAssistantScope=id=>previewAssistant(id,{client_message_id:crypto.randomUUID(),expand_scope:true})
export const confirmAssistant=id=>request(`/api/assistant/proposals/${id}/confirm`,{method:'POST'})
export const discardAssistant=id=>request(`/api/assistant/proposals/${id}/discard`,{method:'POST'})
export const explainAssistant=id=>request(`/api/assistant/proposals/${id}/explanation`,{method:'POST'},125000)
export const getAssistantPreferences=()=>request('/api/assistant/preferences')
export const saveAssistantPreferences=data=>request('/api/assistant/preferences',{method:'PUT',body:JSON.stringify(data)})
export const getAssistantSettings=()=>request('/api/assistant/settings')
export const getTaskCategories=(active)=>request(`/api/task-categories${active===undefined?'':`?active=${active}`}`)
export const createTaskCategory=data=>request('/api/task-categories',{method:'POST',body:JSON.stringify(data)})
export const updateTaskCategory=(key,data)=>request(`/api/task-categories/${encodeURIComponent(key)}`,{method:'PATCH',body:JSON.stringify(data)})
export const getPreferenceRules=()=>request('/api/assistant/preference-rules')
export const createPreferenceRule=data=>request('/api/assistant/preference-rules',{method:'POST',body:JSON.stringify(data)})
export const updatePreferenceRule=(id,data)=>request(`/api/assistant/preference-rules/${id}`,{method:'PATCH',body:JSON.stringify(data)})
export const createAssistantRun=(id,data)=>request(`/api/assistant/sessions/${id}/runs`,{method:'POST',body:JSON.stringify(data)})
export const getAssistantRun=id=>request(`/api/assistant/runs/${id}`)
export const cancelAssistantRun=id=>request(`/api/assistant/runs/${id}/cancel`,{method:'POST'})
export const retryAssistantRun=id=>request(`/api/assistant/runs/${id}/retry`,{method:'POST'})

export const getGoals = () => request('/api/goals')
export const createGoal = (data) => request('/api/goals', { method: 'POST', body: JSON.stringify(data) })
export const updateGoal = (id, data) => request(`/api/goals/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const updateGrowthDirection = (direction) => request('/api/goals/direction', { method: 'PUT', body: JSON.stringify({ direction }) })
export const getGrowthProfile = () => request('/api/growth/profile')
export const getGrowthAttention = () => request('/api/growth/attention')
export const getGrowthInsights = () => request('/api/growth/insights')
export const analyzeGrowthInsights = () => request('/api/growth/insights/analyze', { method: 'POST' }, 125000)
export const editGrowthInsight = (id, time_window) => request(`/api/growth/insights/${id}`, { method: 'PATCH', body: JSON.stringify({ time_window }) })
export const acceptGrowthInsight = (id) => request(`/api/growth/insights/${id}/accept`, { method: 'POST' })
export const ignoreGrowthInsight = (id) => request(`/api/growth/insights/${id}/ignore`, { method: 'POST' })
export const getGrowthReviews = (weekStart) => request(`/api/growth/reviews${weekStart ? `?week_start=${encodeURIComponent(weekStart)}` : ''}`)
export const getGrowthStatistics = (weeks = 4, endWeek) => request(`/api/growth/statistics?weeks=${encodeURIComponent(weeks)}${endWeek ? `&end_week=${encodeURIComponent(endWeek)}` : ''}`)
export const createGrowthReview = (weekStart) => request('/api/growth/reviews', { method: 'POST', body: JSON.stringify({ week_start: weekStart }) })
export const getLocalBackups = () => request('/api/data/backups')
export const exportGrowthData = () => request('/api/data/export', {}, 60000)
export const importGrowthData = (snapshot) => request('/api/data/import', { method: 'POST', body: JSON.stringify(snapshot) }, 60000)

export const getTasksDashboard=()=>request('/api/tasks/dashboard')
export const getProfileContext=()=>request('/api/profile/context')
export const getReviewContext=()=>request('/api/review/context')
