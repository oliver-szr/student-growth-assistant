export const nearBottom = ({ scrollHeight, clientHeight, scrollTop }) => scrollHeight - clientHeight - scrollTop <= 64
export const reviewMetrics = facts => ['completed_count', 'confirmed_actual_minutes', 'planned_minutes'].map(key => Number.isFinite(facts?.[key]) ? facts[key] : null)
export function progressPercent(actual, target) {
  return Number.isFinite(actual) && Number.isFinite(target) && target > 0 ? Math.max(0, Math.min(100, actual / target * 100)) : null
}

export const workspacePages = ['schedule', 'review', 'profile']
export const initialWorkbench = {
  navigation: 'home', page: 'schedule', panel: 'normal', conversations: true,
  mobile: 'chat', visited: ['schedule'],
}

// Navigation changes the view, never the conversation or a page's editing state.
export function workbenchReducer(state, action) {
  if (action.type === 'open' && action.page === 'home') {
    return { ...state, navigation: 'home', mobile: 'chat' }
  }
  if (action.type === 'open' && workspacePages.includes(action.page)) {
    return { ...state, page: action.page, navigation: action.page, mobile: 'workspace',
      panel: state.panel === 'collapsed' ? 'normal' : state.panel,
      visited: [...new Set([...state.visited, action.page])] }
  }
  if (action.type === 'panel' && ['collapsed', 'normal', 'expanded'].includes(action.value)) {
    return { ...state, panel: action.value, mobile: action.value === 'collapsed' ? 'chat' : 'workspace' }
  }
  if (action.type === 'conversations') return { ...state, conversations: !state.conversations }
  if (action.type === 'mobile' && ['conversations', 'chat', 'workspace'].includes(action.value)) {
    return { ...state, mobile: action.value,
      panel: action.value === 'workspace' && state.panel === 'collapsed' ? 'normal' : state.panel }
  }
  return state
}

export function workbenchVisibility(state, narrow) {
  return {
    conversations: narrow ? state.mobile === 'conversations' : state.conversations && state.panel !== 'expanded',
    chat: !narrow || state.mobile === 'chat',
    workspace: narrow ? state.mobile === 'workspace' : state.panel !== 'collapsed',
  }
}
