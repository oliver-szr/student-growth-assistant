// This MVP displays every Task deadline in fixed Asia/Shanghai time (UTC+08:00).
// datetime-local has no offset, so attach one explicitly when sending it.
const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000

export function toBackendDeadline(localValue, originalApiValue) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(localValue)) {
    throw new Error('Choose a deadline date and time.')
  }
  // Editing another field should not truncate existing seconds or microseconds.
  if (originalApiValue && localValue === toDatetimeLocalValue(originalApiValue)) return originalApiValue
  return `${localValue}:00+08:00`
}

export function toDatetimeLocalValue(apiValue) {
  if (!apiValue || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(apiValue)) return ''
  // Date parses the explicit API offset. UTC getters then avoid the browser's timezone.
  const instant = new Date(apiValue)
  if (Number.isNaN(instant.getTime())) return ''
  return new Date(instant.getTime() + SHANGHAI_OFFSET_MS).toISOString().slice(0, 16)
}

export function displayDeadline(apiValue) {
  return toDatetimeLocalValue(apiValue).replace('T', ' ') || '—'
}

export function mondayOfDate(dateValue) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateValue)) throw new Error('Choose a valid week date.')
  const [year, month, day] = dateValue.split('-').map(Number)
  // Construct calendar fields explicitly; never parse a date-only string in local time.
  const calendar = new Date(0)
  calendar.setUTCFullYear(year, month - 1, day)
  if (year < 1 || calendar.toISOString().slice(0, 10) !== dateValue) {
    throw new Error('Choose a valid week date.')
  }
  calendar.setUTCDate(calendar.getUTCDate() - (calendar.getUTCDay() + 6) % 7)
  return calendar.toISOString().slice(0, 10)
}

export function currentShanghaiMonday(now = new Date()) {
  const shanghaiDate = new Date(now.getTime() + SHANGHAI_OFFSET_MS).toISOString().slice(0, 10)
  return mondayOfDate(shanghaiDate)
}
