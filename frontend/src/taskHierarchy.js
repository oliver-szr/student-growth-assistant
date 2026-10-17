import { toBackendDeadline, toDatetimeLocalValue } from './datetime.js'

export const MAX_CHILDREN = 20

export function groupTasks(tasks) {
  const parents = new Set(tasks.filter(t => t.task_kind === 'container').map(t => t.id))
  return tasks.filter(t => !t.parent_task_id || !parents.has(t.parent_task_id)).map(task => ({
    task,
    children: tasks.filter(t => t.parent_task_id === task.id).sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
  }))
}

export function editableContent(content) {
  const local = item => ({ ...item, deadline: toDatetimeLocalValue(item.deadline) })
  return { parent: local(content.parent), children: [...content.children].sort((a, b) => a.sort_order - b.sort_order).map(local) }
}

export function breakdownPayload(content) {
  const backend = item => ({ ...item, deadline: toBackendDeadline(item.deadline) })
  return {
    parent: backend(content.parent),
    children: content.children.map((child, sort_order) => ({ ...backend(child), duration_minutes: Number(child.duration_minutes), sort_order })),
  }
}

export function moveChild(children, index, direction) {
  const next = [...children], target = index + direction
  if (target < 0 || target >= next.length) return next
  ;[next[index], next[target]] = [next[target], next[index]]
  return next.map((child, sort_order) => ({ ...child, sort_order }))
}

export function breakdownTotals(children, expected) {
  const total = children.reduce((sum, child) => sum + (Number(child.duration_minutes) || 0), 0)
  return { total, difference: total - expected }
}
