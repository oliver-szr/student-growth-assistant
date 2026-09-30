import PlanTimeline from './PlanTimeline.jsx'

export default function PlanPreview({ plan, candidate = false, outdated, blocked, selectionChanged = false, busy, onConfirm, emptyText = 'No confirmed plan for this week.' }) {
  const heading = candidate ? 'Candidate Plan' : 'Current Confirmed Plan'
  return (
    <section className={`panel plan-panel ${candidate ? 'candidate-panel' : 'confirmed-panel'}`} aria-label={heading}>
      <h3>{heading}</h3>
      {!plan ? <p className="helper">{candidate ? 'Generate a candidate to review your week.' : emptyText}</p> : <>
        <p className="plan-state">{candidate ? outdated ? 'Outdated candidate' : blocked ? 'Candidate status changed' : selectionChanged ? 'Selection changed' : 'Candidate — not confirmed yet' : 'Confirmed'}</p>
        {candidate && selectionChanged && <p className="helper" role="status">Task selection changed. Generate a new candidate before confirming.</p>}
        <p className="helper">Plan #{plan.id} · Week of {plan.week_start} · {plan.status}</p>
        <details className="plan-metadata">
          <summary>Plan details</summary>
          <dl className="details">
            <div><dt>Source revision</dt><dd>{plan.source_revision}</dd></div>
            <div><dt>Based on plan</dt><dd>{plan.based_on_plan_id === null ? 'None' : `#${plan.based_on_plan_id}`}</dd></div>
          </dl>
        </details>
        <PlanTimeline items={plan.items} />
        {candidate && <div className="button-row">
          <button className="button primary" type="button" disabled={busy || outdated || blocked || selectionChanged} onClick={onConfirm}>{busy ? 'Please wait...' : 'Confirm Candidate'}</button>
        </div>}
      </>}
    </section>
  )
}
