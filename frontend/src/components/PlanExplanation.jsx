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

  if (plan.based_on_plan_id == null) return <p className="helper first-plan">First plan for this week.</p>
  const { pending, result, error } = state
  return (
    <section className="plan-explanation" aria-label="Candidate changes">
      <button className="button secondary" type="button" disabled={pending || busy || blocked} onClick={() => session.current?.start()}>{pending ? 'Explaining...' : 'Explain Changes'}</button>
      {outdated && <p className="helper" role="status">This candidate is outdated and cannot be confirmed without regeneration.</p>}
      {error && <p className="error-box" role="alert">{error}</p>}
      {result && <>
        <h4>Changes</h4>
        <p className="helper">Compared with confirmed snapshot #{result.diff.confirmed_plan_id}. Times are Asia/Shanghai (UTC+08:00).</p>
        {diffGroups(result.diff).map((group) => <section className="diff-group" key={group.key}>
          <h5>{group.label} ({group.items.length})</h5>
          {group.items.length === 0 ? <p className="helper">None.</p> : <ul>{group.items.map((item) => <li key={item.task_id}>
            <strong>{item.title}</strong><span className="helper">Task #{item.task_id} · {item.description}</span>
          </li>)}</ul>}
        </section>)}
        <div className="ai-explanation">
          <h4>AI Explanation</h4>
          {result.explanation_status === 'available' && <p className="helper">Times quoted in this explanation use UTC. Changes above use Shanghai (UTC+08:00).</p>}
          {result.explanation_status === 'unavailable' ? <p className="helper" role="status">AI explanation unavailable. Plan changes remain available.</p> : <p className="explanation-text">{result.explanation}</p>}
          <p className="helper">The candidate is not official until you confirm it.</p>
        </div>
      </>}
    </section>
  )
}
