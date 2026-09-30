import { groupPlanItems, planTimeRange } from '../planning.js'

export default function PlanTimeline({ items }) {
  return (
    <div className="plan-timeline">
      {groupPlanItems(items).map((day) => (
        <section className="plan-day" key={day.date} aria-label={day.date}>
          <h4>{day.date}</h4>
          <ol>
            {day.items.map((item) => (
              <li className={`plan-item ${item.kind}`} key={item.id}>
                <span className="plan-time">{planTimeRange(item)}</span>
                <div><strong>{item.title_snapshot}</strong><span className="plan-kind">{item.kind === 'course' ? 'Course' : 'Task'}</span></div>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  )
}
