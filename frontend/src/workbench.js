import { shanghaiTime } from './assistant.js'

export function workspaceClock(settings, elapsed = 0) {
  const time = Date.parse(settings?.now) + Math.max(0, elapsed)
  return Number.isFinite(time) ? `${settings.demo ? '演示 · ' : ''}${shanghaiTime(time).replace('T', ' ')} 北京时间` : ''
}

export function shiftPreviewDate(date, days, min, max) {
  const time = Date.parse(`${date}T00:00:00+08:00`) + days * 86400000
  if (!Number.isFinite(time)) return date
  const next = shanghaiTime(time).slice(0, 10)
  return next < min ? min : next > max ? max : next
}

export const nearBottom = ({ scrollHeight, clientHeight, scrollTop }) => scrollHeight - clientHeight - scrollTop <= 64
export const reviewMetrics = facts => ['completed_count', 'confirmed_actual_minutes', 'planned_minutes'].map(key => Number.isFinite(facts?.[key]) ? facts[key] : null)
export function progressPercent(actual, target) {
  return Number.isFinite(actual) && Number.isFinite(target) && target > 0 ? Math.max(0, Math.min(100, actual / target * 100)) : null
}

export const workspacePages = ['schedule', 'review', 'profile']
export const defaultSplitRatio = 0.58
export const splitPreferenceKey = 'sga-v2-home-split-ratio'
export const initialWorkbench = {
  navigation: 'home', auxiliaryPage: 'schedule', panel: 'normal',
  conversations: true, mobile: 'primary', visited: ['schedule'], splitRatio: defaultSplitRatio,
}

export function clampSplitRatio(value) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0.35, Math.min(0.75, value)) : defaultSplitRatio
}

export function readSplitRatio(storage) {
  try {
    const raw = storage.getItem(splitPreferenceKey)
    return raw === null || raw.trim() === '' ? defaultSplitRatio : clampSplitRatio(Number(raw))
  } catch { return defaultSplitRatio }
}

// Keep the preference across resizes; clamp the rendered ratio to usable pane widths.
export function splitBounds(available) {
  const width = Number.isFinite(available) ? Math.max(680, available) : 1164
  return { min: Math.max(0.35, 360 / width), max: Math.min(0.75, 1 - 320 / width) }
}
export function renderedSplitRatio(preferred, available) {
  const { min, max } = splitBounds(available)
  return Math.max(min, Math.min(max, clampSplitRatio(preferred)))
}
export const workbenchPanel = state => state.panel

export function workbenchReducer(state, action) {
  if (action.type === 'navigate' && ['home', ...workspacePages].includes(action.page)) {
    return { ...state, navigation: action.page, mobile: 'primary',
      visited: action.page === 'home' ? state.visited : [...new Set([...state.visited, action.page])] }
  }
  if (action.type === 'auxiliary' && workspacePages.includes(action.page)) {
    return { ...state, auxiliaryPage: action.page, mobile: 'auxiliary',
      panel: state.panel === 'collapsed' ? 'normal' : state.panel,
      visited: [...new Set([...state.visited, action.page])] }
  }
  if (action.type === 'panel' && ['collapsed', 'normal', 'expanded'].includes(action.value)) {
    return { ...state, panel: action.value,
      mobile: action.value === 'collapsed' ? 'primary' : 'auxiliary' }
  }
  if (action.type === 'conversations') return { ...state, conversations: !state.conversations }
  if (action.type === 'mobile' && ['conversations', 'primary', 'auxiliary'].includes(action.value)) {
    return { ...state, mobile: action.value, panel: action.value === 'auxiliary' && state.panel === 'collapsed' ? 'normal' : state.panel }
  }
  if (action.type === 'split') return { ...state, splitRatio: clampSplitRatio(action.value) }
  return state
}

export function workbenchVisibility(state, narrow) {
  const panel = workbenchPanel(state)
  return {
    conversations: narrow ? state.mobile === 'conversations' : state.navigation === 'home' && state.conversations && panel !== 'expanded',
    primary: !narrow || state.mobile === 'primary',
    auxiliary: narrow ? state.mobile === 'auxiliary' : panel !== 'collapsed',
  }
}

export function toolPlacement(state, page) {
  return state.navigation === page ? 'primary' : 'hidden'
}
