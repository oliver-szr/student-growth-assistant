// All grouping is performed by the backend in Asia/Shanghai. Date labels are
// calendar strings, never parsed through a browser's local timezone.
export const percentText = value => Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—'
export function minutesText(actual, known = 0, unknown = 0) {
  if (Number.isFinite(actual)) return `${actual} 分钟`
  if (known > 0) return `已知 ${known} 分钟（不完整）`
  return unknown > 0 ? '耗时未知' : '尚无反馈'
}
export function signedText(value) {
  return Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value}` : '—'
}
export function weeklyValue(row, metric) {
  if (metric === 'completed_count') return row.completed_count
  return Number.isFinite(row.actual_minutes) ? row.actual_minutes : row.known_actual_minutes > 0 ? row.known_actual_minutes : null
}
export function chartBars(weekly, metric) {
  const values = weekly.map(row => weeklyValue(row, metric))
  const max = Math.max(1, ...values.filter(Number.isFinite))
  const step = 620 / Math.max(1, weekly.length)
  return weekly.map((row, index) => ({ row, value: values[index], x: 48 + index * step,
    width: Math.min(38, step * .6), height: Number.isFinite(values[index]) ? values[index] / max * 120 : null,
    incomplete: metric === 'actual_minutes' && row.actual_minutes === null && row.unknown_actual_count > 0 }))
}
