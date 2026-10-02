import { WEEKDAYS } from './constants.js'

export function proposalToFormRule(proposal) {
  return {
    kind: proposal.kind,
    title: proposal.title,
    recurrence: proposal.recurrence,
    weekday: proposal.recurrence === 'weekly' ? proposal.weekday : null,
    date: proposal.recurrence === 'once' ? proposal.date : null,
    start_time: proposal.start_time,
    end_time: proposal.end_time,
  }
}

export function proposalDay(proposal) {
  return proposal.recurrence === 'weekly' ? WEEKDAYS[proposal.weekday - 1] : proposal.date
}

export function timeRuleFormPayload({ kind, title, recurrence, weekday, date, startTime, endTime }, originalRule) {
  const repeats = kind === 'course' ? 'weekly' : recurrence
  return {
    kind,
    title,
    recurrence: repeats,
    weekday: repeats === 'weekly' ? Number(weekday) : null,
    date: repeats === 'once' ? date : null,
    start_time: originalRule && startTime === originalRule.start_time.slice(0, 5) ? originalRule.start_time : startTime,
    end_time: originalRule && endTime === originalRule.end_time.slice(0, 5) ? originalRule.end_time : endTime,
  }
}

export function parsingNotice(result) {
  if (result.status === 'needs_clarification') return { heading: 'More information needed', message: result.message }
  if (result.status === 'unsupported') return { heading: 'Unsupported request', message: 'This AI feature only understands courses and protected time.' }
  return null
}
