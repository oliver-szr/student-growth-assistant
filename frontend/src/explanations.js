import { displayDeadline } from './datetime.js'

const interval = (start, end) => `${displayDeadline(start)} → ${displayDeadline(end)}`

export function diffGroups(diff) {
  return [
    { key: 'added', label: '新增', items: diff.added.map((item) => ({ ...item, description: interval(item.start_at, item.end_at) })) },
    { key: 'moved', label: '时间调整', items: diff.moved.map((item) => ({ ...item, description: `原安排：${interval(item.from_start, item.from_end)}；新安排：${interval(item.to_start, item.to_end)}` })) },
    { key: 'removed', label: '未纳入候选计划', items: diff.removed.map((item) => ({ ...item, description: `原安排：${interval(item.start_at, item.end_at)}` })) },
    { key: 'unchanged', label: '未变化', items: diff.unchanged.map((item) => ({ ...item, description: interval(item.start_at, item.end_at) })) },
  ]
}

// Each mounted candidate owns a session. Disposing it ignores late responses;
// generating, changing week, or confirming unmounts the keyed candidate child.
export function createExplanationSession(plan, request, update) {
  let active = true
  let state = { pending: false, result: null, error: '' }
  function publish(patch) {
    state = { ...state, ...patch }
    if (active) update(state)
  }
  return {
    async start() {
      if (!active || state.pending || plan.based_on_plan_id == null || plan.status !== 'candidate') return
      publish({ pending: true, error: '' })
      try {
        const result = await request(plan.id)
        if (active) publish({ result })
      } catch (error) {
        if (active) publish({ error: error.message })
      } finally {
        if (active) publish({ pending: false })
      }
    },
    close() { active = false },
  }
}
