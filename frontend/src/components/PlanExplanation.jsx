import { useEffect, useRef, useState } from 'react'
import { explainCandidate } from '../api.js'
import { createExplanationSession, diffGroups } from '../explanations.js'

export default function PlanExplanation({ plan, outdated, blocked, busy }) {
  const [state, setState] = useState({ pending: false, result: null, error: '' })
  const session = useRef(null)
  useEffect(() => {
    const current = createExplanationSession(plan, explainCandidate, setState)
    session.current = current
    return () => current.close()
  }, [plan.id, plan.based_on_plan_id])

  if (plan.based_on_plan_id == null) return <p className="helper first-plan">这是本周的首次候选计划。</p>
  const { pending, result, error } = state
  return (
    <section className="plan-explanation" aria-label="候选计划变化">
      <button className="button secondary" type="button" disabled={pending || busy || blocked} onClick={() => session.current?.start()}>{pending ? '正在解释…' : '查看变化说明'}</button>
      {outdated && <p className="helper" role="status">该候选计划已过期，请重新生成后再确认。</p>}
      {error && <p className="error-box" role="alert">{error}</p>}
      {result && <>
        <h4>计划变化</h4>
        <p className="helper">对比正式计划快照 #{result.diff.confirmed_plan_id}。以下时间均为北京时间（UTC+08:00）。</p>
        {diffGroups(result.diff).map((group) => <section className="diff-group" key={group.key}>
          <h5>{group.label} ({group.items.length})</h5>
          {group.items.length === 0 ? <p className="helper">无。</p> : <ul>{group.items.map((item) => <li key={item.task_id}>
            <strong>{item.title}</strong><span className="helper">任务 #{item.task_id} · {item.description}</span>
          </li>)}</ul>}
        </section>)}
        <div className="ai-explanation">
          <h4>AI 变化说明</h4>
          {result.explanation_status === 'available' && <p className="helper">AI 说明中的时间使用 UTC；上方变化列表使用北京时间（UTC+08:00）。</p>}
          {result.explanation_status === 'unavailable' ? <p className="helper" role="status">AI 说明暂不可用，仍可查看计划变化并确认方案。</p> : <p className="explanation-text">{result.explanation}</p>}
          <p className="helper">只有你确认后，候选计划才会成为正式计划。</p>
        </div>
      </>}
    </section>
  )
}
