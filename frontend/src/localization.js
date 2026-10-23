// Translate display values only. API enums and original error detail remain unchanged.
export const STATUS_LABELS = { todo: '待完成', done: '已完成', cancelled: '已取消', candidate: '候选', confirmed: '已确认', superseded: '已替换' }
export const PRIORITY_LABELS = { low: '低', normal: '普通', high: '高' }
export const RECURRENCE_LABELS = { weekly: '每周', once: '仅一次' }

const CODE_MESSAGES = {
  MEMORY_VERSION_CONFLICT:'记忆已在其他入口修改，本地文字保留，请核对最新版本。',
  MEMORY_ALREADY_EXISTS:'已有相同记忆，请在档案中审核或编辑现有项。',
  MEMORY_USE_PREFERENCE:'这属于排程约束，请使用正式偏好或时间规则草案；记忆不会改变日程。',
  MEMORY_DELETED:'记忆已从活动检索中移除；历史聊天和既有备份可能仍有原文。',
  MEMORY_NOT_FOUND:'记忆不存在或当前不可访问。',
  MEMORY_EXPLICIT_INTENT_REQUIRED:'临时表达不会保存为长期记忆，请明确希望以后记住的内容。',
  INVALID_MEMORY_ACTION:'记忆状态已经改变，请重新读取后操作。',
  SUMMARY_EMPTY:'还没有可以整理的有效会话消息。',
  SUMMARY_IN_PROGRESS:'小结仍在生成，请查询同一请求结果，避免重复调用。',
  SUMMARY_INTERRUPTED:'小结运行已中断，请查询原请求后重试。',
  SUMMARY_NOT_FOUND:'没有找到原小结请求，请核对后重新读取。',
  SOURCE_UNAVAILABLE:'来源消息或会话已不可访问。',
  LEGACY_RESTORE_SECRETARY_PRESENT:'当前已有记忆或会话小结，旧备份恢复已拒绝。请先导出v5并在独立空库恢复旧备份。',

  DRAFT_COORDINATION_REQUIRED:'请先打开草案并保存有效编辑，再让 AI 修改。',
  RECORD_VERSION_CONFLICT:'复盘记录已在其他入口修改，本地输入保留，请比较后重新读取。',
  RECORD_RANGE_IMMUTABLE:'已存记录的事实范围固定；不同范围请新建记录。',
  REVIEW_FACTS_CHANGED:'事实来源已变化，请保留文字并重新整理最新事实后确认。',
  INVALID_RANGE:'日期范围无效，请检查开始、结束日期及范围上限。',
  RANGE_TOO_LARGE:'范围内事项过多，请缩小日期范围。',
  DRAFT_APPLIED:'这份草案已保存，请查看保存结果。',
  DRAFT_NOT_FOUND:'草案不存在或无法访问，请重新读取。',
  LEGACY_RESTORE_REVIEWS_PRESENT:'已有新式复盘，旧备份无法表达这些资料，恢复已拒绝。请导出最新版后在独立空库恢复。',
  LEGACY_RESTORE_TOOLS_PRESENT:'已有工具运行资料，旧备份恢复已拒绝，请先导出最新版。',
  RUN_NOT_FOUND: '这次回复不存在，请重新读取会话。',
  RUN_VERSION_CONFLICT: '回复已重新开始，请读取最新状态后操作。',
  RUN_NOT_RETRYABLE: '这次回复已完成，不能重复生成。',
  CONVERSATION_NOT_FOUND: '会话不存在，当前选择已保留。请检查会话列表。',
  CONVERSATION_DELETED: '会话已删除，不能继续发送。正式任务和日程仍保留。',
  CONVERSATION_ARCHIVED: '会话已归档，请先恢复后再发送。',
  CONVERSATION_VERSION_CONFLICT: '会话已被其他页面修改。已保留输入，请读取最新状态后重试。',
  CONVERSATION_BUSY: '会话仍有运行中的请求，请等待完成或到原入口处理。本次没有取消运行。',
  CONVERSATION_HAS_DRAFTS: '会话仍有未处理草案，请到原业务入口明确处理。本次没有采用或放弃草案。',
  LEGACY_CONVERSATION_READ_ONLY: '历史工具会话只供阅读，请通过原规划或业务入口操作。',
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
  AI_SKILLS_UNAVAILABLE: '助手技能文件读取或校验失败，已停止操作。请检查服务端技能配置；仍可使用手动功能。',
  AI_CONTEXT_TOO_LARGE: '所选资料超过安全请求上限，请缩小问题范围或到工作区核对；原消息和草案未改变。',
  AI_UNAVAILABLE: 'AI 暂时不可用，仍可手动操作。',
  AI_RESPONSE_INVALID: 'AI 返回的格式有误。可以重试；已有草案请先查看，不必重复生成。',
  STALE_DRAFT: '任务、目标或计划已变化，请取消旧草案并按最新资料重新生成。',
  DRAFT_VERSION_CONFLICT: '草案已被其他页面修改，请重新加载草案后继续。',
  DRAFT_NOT_READY: '草案已确认或取消，请重新加载最新状态。',
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
  const message=typeof detail==='string'?detail:detail?.message
  // Only documented business errors may add a service explanation. Unexpected
  // server/provider text and stack traces still use the safe local fallback.
  const explanation=typeof message==='string'&&message.length<=500&&/[\u4e00-\u9fff]/.test(message)&&!/(Traceback|[A-Za-z]:\\|sk-[\w-]+|api[_ -]?key|Authorization|SELECT |INSERT |UPDATE |DELETE )/i.test(message)?message:''
  if (detail?.code && CODE_MESSAGES[detail.code]) {
    const guidance=CODE_MESSAGES[detail.code]
    return explanation||guidance
  }
  if (Array.isArray(detail)) return detail.map(validationMessage).join('；')
  if (detail === 'Task not found') return '未找到任务，请重新加载。'
  if (detail === 'TimeRule not found') return '未找到时间规则，请重新加载。'
  if (status >= 500) return '服务暂时不可用，请稍后重试；操作前请重新加载最新状态。'
  if(explanation)return explanation
  if (status === 422) return '输入内容无效，请检查表单后重试。'
  return `请求未成功（${status}），请重新加载后重试。`
}

export function clarificationMessage(message) {
  // Preserve Chinese provider clarification; English uses an actionable local fallback.
  return typeof message === 'string' && /[\u4e00-\u9fff]/.test(message)
    ? message
    : '请补充具体日期或星期、开始时间、结束时间，以及是否每周重复。'
}
