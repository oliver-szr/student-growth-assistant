import PlanTimeline from './PlanTimeline.jsx'
import { STATUS_LABELS } from '../localization.js'
import PlanExplanation from './PlanExplanation.jsx'

export default function PlanPreview({ plan, candidate = false, outdated, blocked, selectionChanged = false, busy, onConfirm, emptyText = '本周还没有正式计划。' }) {
  const heading = candidate ? '候选计划' : '当前正式计划'
  return (
    <section className={`panel plan-panel ${candidate ? 'candidate-panel' : 'confirmed-panel'}`} aria-label={heading}>
      <h3>{heading}</h3>
      {!plan ? <p className="helper">{candidate ? '先生成候选计划，查看本周安排。' : emptyText}</p> : <>
        <p className="plan-state">{candidate ? outdated ? '候选计划已过期' : blocked ? '候选计划状态已变化' : selectionChanged ? '所选任务已变化' : '候选计划，尚未确认' : '已确认'}</p>
        {candidate && selectionChanged && <p className="helper" role="status">所选任务已变化，请重新生成候选计划后再确认。</p>}
        <p className="helper">计划 #{plan.id} · 周起始日：{plan.week_start} · {STATUS_LABELS[plan.status]}</p>
        <details className="plan-metadata">
          <summary>计划详情</summary>
          <dl className="details">
            <div><dt>数据版本</dt><dd>{plan.source_revision}</dd></div>
            <div><dt>参考计划</dt><dd>{plan.based_on_plan_id === null ? '无' : `#${plan.based_on_plan_id}`}</dd></div>
          </dl>
        </details>
        <PlanTimeline items={plan.items} />
        {candidate && <div className="button-row">
          <button className="button primary" type="button" disabled={busy || outdated || blocked || selectionChanged} onClick={onConfirm}>{busy ? '请稍候…' : '确认候选计划'}</button>
        </div>}
        {candidate && <PlanExplanation key={plan.id} plan={plan} outdated={outdated} blocked={blocked} busy={busy} />}
      </>}
    </section>
  )
}
