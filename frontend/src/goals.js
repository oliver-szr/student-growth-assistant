// Goal responses contain metadata that the strict write contract must reject.
export function goalPayload(form) {
  return {
    title: form.title,
    motivation: form.motivation ?? '',
    goal_type: form.goal_type ?? 'long_term',
    priority: Number(form.priority),
    metric_kind: form.metric_kind,
    weekly_target: Number(form.weekly_target),
    unit_label: form.unit_label,
    due_date: form.due_date || null,
    status: form.status ?? 'active',
  }
}
