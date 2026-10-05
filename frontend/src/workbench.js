export const nearBottom = ({ scrollHeight, clientHeight, scrollTop }) => scrollHeight - clientHeight - scrollTop <= 64
export const reviewMetrics = facts => ['completed_count', 'confirmed_actual_minutes', 'planned_minutes'].map(key => Number.isFinite(facts?.[key]) ? facts[key] : null)
export function progressPercent(actual, target) {
  return Number.isFinite(actual) && Number.isFinite(target) && target > 0 ? Math.max(0, Math.min(100, actual / target * 100)) : null
}
