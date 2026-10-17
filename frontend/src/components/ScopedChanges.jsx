import { shanghaiTime } from '../assistant.js'

const LABELS={preserved:'保留不变',moved:'调整时间',added:'新增安排',pending:'待处理',removed:'移出未来安排'}
const intervals=items=>(items||[]).map(x=>`${shanghaiTime(x.start_at).replace('T',' ')}–${shanghaiTime(x.end_at).slice(11)}`).join('；')

export default function ScopedChanges({proposal,pending,onExpand,onDecline}){
  const groups=proposal.change_groups
  if(!groups)return null
  const expandable=proposal.replanning?.requires_expansion&&proposal.status==='no_plan'
  return <div className="scoped-changes" aria-label="局部调整明细">
    <p className="scope-counts">保留 {groups.counts.preserved} 项 · 调整 {groups.counts.moved} 项 · 新增 {groups.counts.added} 项 · 待处理 {groups.counts.pending} 项</p>
    <p>{proposal.replanning?.mode==='expanded'?'已允许调整其他尚未开始、未锁定的任务。':'优先保留未受影响的合法安排。'}采用后，本周与下周将一起保存。</p>
    {proposal.formal_plan_needs_review&&<p className="diagnostic" role="status">原正式计划需要重新核对；新的任务或时间约束尚未通过采用候选更新到日程。</p>}
    {Object.entries(LABELS).map(([key,label])=>groups[key]?.length>0&&<details key={key} open={key!=='preserved'}><summary>{label} · {groups[key].length} 项</summary><ul className="change-list">{groups[key].map(item=><li key={item.ref}><strong>{item.title}</strong>{item.before_segments?.length>0&&<span>原时间：{intervals(item.before_segments)}</span>}{item.after_segments?.length>0&&<span>{key==='preserved'?'保留时间':'新时间'}：{intervals(item.after_segments)}</span>}{item.remaining_minutes!=null&&<span>仍需安排 {item.remaining_minutes} 分钟</span>}{item.reasons?.map((reason,i)=><small key={i}>{reason.message}</small>)}</li>)}</ul></details>)}
    {expandable&&<div className="scope-expansion"><p>当前局部搜索未找到完整安排。是否允许同时调整其他未来任务？历史、已开始和锁定片段仍受保护。</p><div className="button-row"><button type="button" className="button primary" disabled={pending} onClick={onExpand}>允许扩大范围并重新计算</button><button type="button" className="button subtle" disabled={pending} onClick={onDecline}>暂不扩大，放弃本轮候选</button></div></div>}
  </div>
}
