export const UI_COPY = Object.freeze({deadline:'截止时间',remaining:'剩余时长（分钟）',actual:'实际投入（分钟）',pending:'待确认',adopt:'采用方案',discard:'放弃',saveProfile:'保存修改',saveFeedback:'保存记录',adjust:'调整安排',emptyTask:'暂无任务。',emptyGoal:'暂无目标。',emptyPreference:'暂无偏好。'})
export function changeCounts(changes=[]){
 const groups={added:new Set(),moved:new Set(),removed:new Set()}
 for(const c of changes){const kind=c.kind==='added'?'added':c.kind==='removed'?'removed':'moved';groups[kind].add(c.ref)}
 return Object.fromEntries(Object.entries(groups).map(([key,refs])=>[key,refs.size]))
}
export function changeSummary(changes=[]){const n=changeCounts(changes);return [n.added&&`新增安排 ${n.added} 项`,n.moved&&`调整 ${n.moved} 项`,n.removed&&`移除安排 ${n.removed} 项`].filter(Boolean).join(' · ')||'保留现有安排'}
