import { WEEKDAYS } from './constants.js'
import { clarificationMessage } from './localization.js'

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
  if (result.status === 'needs_clarification') return { heading: '需要补充信息', message: clarificationMessage(result.message) }
  if (result.status === 'unsupported') return { heading: '暂不支持此请求', message: '此功能只支持添加课程和保留时间，不处理任务或计划操作。' }
  return null
}
