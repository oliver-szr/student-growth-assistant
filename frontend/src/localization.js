// Translate display values only. API enums and original error detail remain unchanged.
export const STATUS_LABELS = { todo: '待完成', done: '已完成', cancelled: '已取消', candidate: '候选', confirmed: '已确认', superseded: '已替换' }
export const PRIORITY_LABELS = { low: '低', normal: '普通', high: '高' }
export const RECURRENCE_LABELS = { weekly: '每周', once: '仅一次' }

const CODE_MESSAGES = {
  INVALID_STATISTICS_RANGE: '请选择最近4、8或12周；结束周须为不晚于当前周的周一。',
  STALE_CANDIDATE: '候选计划已过期：当前时间、任务、时间规则或正式计划发生了变化。请重新生成后再确认。',
  PLAN_NOT_CANDIDATE: '此计划已不是待确认的候选计划，请重新加载并生成新方案。',
  PLAN_NOT_FOUND: '未找到计划，请重新加载。',
  PLAN_BASELINE_INVALID: '该候选计划的对比基准不可用，请重新生成。',
  PAST_PLANNING_WINDOW: '所选周已经结束，请选择仍有未来时间的周。',
  PLAN_REQUIRES_ASSISTANT: '当前安排包含分段、锁定、指定时段或已开始的记录，请在规划工作台调整，以保留原有记录。',
  TASK_NOT_FOUND: '部分所选任务已不存在，请重新加载任务列表。',
  TASK_NOT_TODO: '只能安排待完成任务，请重新加载后选择。',
  UNSCHEDULABLE: '当前排程规则未找到完整方案。请减少任务、调整截止时间或保护时间后重试。',
  GENERATED_SCHEDULE_INVALID: '生成的计划未通过校验，未保存。请重新生成。',
  INVALID_WEEK: '请选择有效的周日期（以周一为起点）。',
  INVALID_TASKS: '所选任务信息无效，请检查任务时长、截止时间和状态。',
  INVALID_TIME_RULES: '时间规则无效，请检查课程是否重叠，以及日期和起止时间是否正确。',
  AI_NOT_CONFIGURED: '尚未配置 AI，仍可手动拆解任务、添加任务、课程和保护时间。',
  AI_UNAVAILABLE: 'AI 暂时不可用，仍可手动操作。',
  AI_RESPONSE_INVALID: 'AI 返回的内容未通过校验，请补充描述后重试或手动添加。',
  STALE_DRAFT: '任务、目标或计划已变化，请取消旧草案并按最新资料重新生成。',
  DRAFT_VERSION_CONFLICT: '草案已被其他页面修改，请重新加载草案后继续。',
  DRAFT_NOT_READY: '草案已确认或取消，请重新加载最新状态。',
  DRAFT_APPLIED: '草案已经确认，不能通过取消草案撤销任务。',
  DRAFT_NOT_FOUND: '未找到任务拆解草案，请重新加载。',
  INVALID_BREAKDOWN: '请保留至少一个合法子任务，检查标题、5分钟整数倍时长和截止时间。',
  BREAKDOWN_DEADLINE_INVALID: '父子任务截止时间必须在未来，请修改草案。',
  CHILD_DEADLINE_INVALID: '子任务截止时间不能晚于父任务，请先核对子任务。',
  CONTAINER_NOT_EXECUTABLE: '父任务是汇总容器，请选择具体子任务执行或排程。',
  CONTAINER_STATUS_DERIVED: '父任务进度由子任务汇总，请分别处理子任务。',
  INVALID_TASK_HIERARCHY: '仅支持父容器与子任务两级结构，不能引用自身或循环嵌套。',
  PARENT_NOT_FOUND: '父任务不存在，请重新加载任务列表。',
  TASK_HAS_EXECUTION_FACTS: '任务已有计划、执行记录或锁定，不能直接转换类型，请另建父容器。',
  TOO_MANY_CHILDREN: '每个父任务最多20个子任务。',
  INVALID_GOAL: '关联目标不存在或已停用，请重新选择。',
  IDEMPOTENCY_CONFLICT: '此请求标识已用于另一份输入，请重新开始。',
}

const FIELD_LABELS = {
  title: '标题', description: '说明', duration_minutes: '剩余时长', deadline: '截止时间',
  priority: '优先级', status: '状态', kind: '类型', recurrence: '重复方式', weekday: '星期',
  date: '日期', start_time: '开始时间', end_time: '结束时间', week_start: '周日期',
  task_ids: '所选任务', active: '启用状态', text: '时间描述', language: '语言',
  parent: '父任务', children: '子任务', content: '草案', version: '草案版本',
  expected_duration_minutes: '原始预期时长', sort_order: '建议顺序', parent_task_id: '父任务', task_kind: '任务类型',
}

function validationMessage(item) {
  const message = typeof item?.msg === 'string' ? item.msg : ''
  const location = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== 'body').map((part) => FIELD_LABELS[part] || (typeof part === 'number' ? `第 ${part + 1} 项` : '输入')).join(' / ') : ''
  let correction = '内容无效，请检查后重试。'
  if (/title must not be blank|title cannot be null|Field required|field cannot be null/.test(message)) correction = '不能为空，请填写。'
  else if (/multiple of 5/.test(message)) correction = '必须是大于零的 5 分钟整数倍。'
  else if (/5分钟/.test(message)) correction = '必须为5分钟的整数倍。'
  else if (/子任务截止时间/.test(message)) correction = '子任务截止时间不能晚于父任务。'
  else if (/建议顺序/.test(message)) correction = '建议顺序不能重复。'
  else if (/start_time must be before end_time/.test(message)) correction = '开始时间必须早于结束时间，暂不支持跨夜。'
  else if (/weekly requires/.test(message)) correction = '每周重复时请选择星期，不要填写具体日期。'
  else if (/once requires/.test(message)) correction = '仅一次时请填写日期，不要选择星期。'
  else if (/course must be weekly/.test(message)) correction = '课程必须设置为每周重复。'
  else if (/Monday/.test(message)) correction = '请选择周一。'
  else if (/task_ids must be unique/.test(message)) correction = '不能重复选择同一个任务。'
  else if (/timezone|offset|local times/.test(message)) correction = '时间格式无效，请按北京时间填写。'
  else if (item?.type === 'greater_than') correction = `必须大于 ${item.ctx?.gt ?? 0}。`
  else if (item?.type === 'less_than_equal') correction = `不能大于 ${item.ctx?.le ?? '允许的上限'}。`
  else if (item?.type === 'string_too_long') correction = `不能超过 ${item.ctx?.max_length ?? '允许的'} 个字符。`
  return `${location ? `${location}：` : ''}${correction}`
}

export function localizedError(status, detail) {
  if (detail?.code && CODE_MESSAGES[detail.code]) return CODE_MESSAGES[detail.code]
  if (Array.isArray(detail)) return detail.map(validationMessage).join('；')
  if (detail === 'Task not found') return '未找到任务，请重新加载。'
  if (detail === 'TimeRule not found') return '未找到时间规则，请重新加载。'
  if (status >= 500) return '服务暂时不可用，请稍后重试；操作前请重新加载最新状态。'
  if (status === 422) return '输入内容无效，请检查表单后重试。'
  return `请求未成功（${status}），请重新加载后重试。`
}

export function clarificationMessage(message) {
  // Preserve Chinese provider clarification; English uses an actionable local fallback.
  return typeof message === 'string' && /[\u4e00-\u9fff]/.test(message)
    ? message
    : '请补充具体日期或星期、开始时间、结束时间，以及是否每周重复。'
}
