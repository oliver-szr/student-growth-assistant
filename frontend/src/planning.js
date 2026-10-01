import { toDatetimeLocalValue } from './datetime.js'

export function sameTaskSelection(selectedTaskIds, candidateTaskIds) {
  if (selectedTaskIds.length !== candidateTaskIds.length) return false
  const selectedIds = new Set(selectedTaskIds)
  const candidateIds = new Set(candidateTaskIds)
  return selectedIds.size === candidateIds.size && [...selectedIds].every((id) => candidateIds.has(id))
}

export function groupPlanItems(items) {
  const days = new Map()
  for (const item of items) {
    const date = toDatetimeLocalValue(item.start_at).slice(0, 10)
    if (!days.has(date)) days.set(date, [])
    days.get(date).push(item)
  }
  // Preserve the API's start_at / kind / id order within each day.
  return Array.from(days, ([date, items]) => ({ date, items }))
}

export function planTimeRange(item) {
  const start = toDatetimeLocalValue(item.start_at)
  const end = toDatetimeLocalValue(item.end_at)
  return `${start.slice(11)}–${start.slice(0, 10) === end.slice(0, 10) ? end.slice(11) : end.replace('T', ' ')}`
}
