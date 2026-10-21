export const nearBottom = ({ scrollHeight, clientHeight, scrollTop }) => scrollHeight - clientHeight - scrollTop <= 64
export const reviewMetrics = facts => ['completed_count', 'confirmed_actual_minutes', 'planned_minutes'].map(key => Number.isFinite(facts?.[key]) ? facts[key] : null)
export function progressPercent(actual, target) {
  return Number.isFinite(actual) && Number.isFinite(target) && target > 0 ? Math.max(0, Math.min(100, actual / target * 100)) : null
}

export const workspacePages = ['schedule', 'review', 'profile']
export const defaultSplitRatio = 0.58
export const splitPreferenceKey = 'sga-v2-home-split-ratio'
export const initialWorkbench = {
  navigation: 'home', auxiliaryPage: 'schedule', panel: 'normal', toolPanel: 'collapsed',
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
export const workbenchPanel = state => state.navigation === 'home' ? state.panel : state.toolPanel

export function workbenchReducer(state, action) {
  if (action.type === 'navigate' && ['home', ...workspacePages].includes(action.page)) {
    return { ...state, navigation: action.page, mobile: 'primary',
      toolPanel: action.page === 'home' ? state.toolPanel : 'collapsed',
      visited: action.page === 'home' ? state.visited : [...new Set([...state.visited, action.page])] }
  }
  if (action.type === 'auxiliary' && workspacePages.includes(action.page)) {
    const key = state.navigation === 'home' ? 'panel' : 'toolPanel'
    return { ...state, auxiliaryPage: action.page, mobile: 'auxiliary',
      [key]: state[key] === 'collapsed' ? 'normal' : state[key],
      visited: [...new Set([...state.visited, action.page])] }
  }
  if (action.type === 'panel' && ['collapsed', 'normal', 'expanded'].includes(action.value)) {
    return { ...state, [state.navigation === 'home' ? 'panel' : 'toolPanel']: action.value,
      mobile: action.value === 'collapsed' ? 'primary' : 'auxiliary' }
  }
  if (action.type === 'conversations') return { ...state, conversations: !state.conversations }
  if (action.type === 'mobile' && ['conversations', 'primary', 'auxiliary'].includes(action.value)) {
    const key = state.navigation === 'home' ? 'panel' : 'toolPanel'
    return { ...state, mobile: action.value, [key]: action.value === 'auxiliary' && state[key] === 'collapsed' ? 'normal' : state[key] }
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
  if (state.navigation === page) return 'primary'
  return state.auxiliaryPage === page ? 'auxiliary' : 'hidden'
}
