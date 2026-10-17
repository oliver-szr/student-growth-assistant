import { groupTasks } from '../taskHierarchy.js'
import { displayDeadline } from '../datetime.js'

export default function TaskHierarchy({ tasks, renderTask, renderContainer, onAddChild, onEditContainer, pending }) {
  return <div className="task-hierarchy">{groupTasks(tasks).map(({ task, children }) => task.task_kind === 'container' ?
    <article className="item-card task-container" key={task.id}>
      <div className="item-top"><h4>{task.title}</h4><span className="badge">父任务 · 汇总容器</span></div>
      {task.description && <p>{task.description}</p>}
      <p>截止 {displayDeadline(task.deadline)}</p>
      <p className="hierarchy-progress">已确认完成 {task.progress?.completed_children || 0} / {children.length} 项 · 总预计 {task.progress?.total_estimate_minutes || 0} 分钟 · 待完成剩余 {task.progress?.remaining_minutes || 0} 分钟</p>
      <p className="helper">已安排 {task.progress?.scheduled_children || 0} 项 · 已记录投入 {task.progress?.executed_children || 0} 项（{task.progress?.actual_minutes || 0} 分钟） · 部分完成 {task.progress?.partial_children || 0} 项 · 已取消 {task.progress?.cancelled_children || 0} 项</p>
      <p className="helper">总预计为子任务初始估时之和，剩余量来自当前任务状态和反馈。仅子任务参与排程和执行；建议顺序不代表强制前置依赖。</p>
      <div className="button-row"><button type="button" className="button subtle" disabled={pending} onClick={() => onEditContainer?.(task)}>编辑父任务</button><button type="button" className="button secondary" disabled={pending || children.length >= 20} onClick={() => onAddChild?.(task)}>手动增加子任务</button></div>
      {renderContainer?.(task)}
      <details open><summary>子任务（{children.length}）</summary>{children.length ? <div className="hierarchy-children">{children.map((child, i) => <div key={child.id}><p className="helper">建议顺序 {i + 1}</p>{renderTask(child)}</div>)}</div> : <p className="state-box">还没有子任务，可手动添加。</p>}</details>
    </article> : renderTask(task))}</div>
}
