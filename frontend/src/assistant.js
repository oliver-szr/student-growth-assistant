const formatter=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
export function shanghaiTime(value){return formatter.format(new Date(value)).replace(' ','T')}
export function calendarPosition(item){
  const start=shanghaiTime(item.start_at),end=shanghaiTime(item.end_at)
  const minutes=s=>Number(s.slice(11,13))*60+Number(s.slice(14,16))
  return {date:start.slice(0,10),top:minutes(start)-480,height:minutes(end)-minutes(start)}
}
export function visibleSchedule(confirmed,proposal){
  if(proposal?.status!=='ready')return confirmed
  const preserved=new Set(proposal.change_groups?.preserved?.map(x=>x.ref)||[])
  const items=[...confirmed.filter(x=>!proposal.selected_refs.includes(x.ref)&&!(proposal.removed_refs||[]).includes(x.ref)),...(proposal.retained||[]),...proposal.items.map(x=>({...x,candidate:!preserved.has(x.ref)}))]
  return [...new Map(items.map(x=>[`${x.ref}:${x.start_at}:${x.end_at}`,x])).values()]
}
export function manualAction(form){
  return {op:form.target?'update':'add',...(form.target?{target:form.target}:{}),fields:{title:form.title,duration_minutes:Number(form.minutes),deadline:`${form.deadline}:00+08:00`,priority:form.priority,task_type:form.task_type||'other',...(form.splittable===undefined?{}:{profile:{splittable:Boolean(form.splittable),min_block_minutes:Number(form.min_block_minutes||30),max_segments:Number(form.max_segments||4)}})}}
}
const URGENCY_LABELS={overdue:'已逾期',critical:'尽快处理',urgent:'近期截止',soon:'7天内截止',normal:'截止较远',at_risk:'需要调整',available:'可安排'}
export function focusCards(items){
  return (Array.isArray(items)?items:[]).slice(0,3).map(item=>({...item,urgency_label:item.availability_state==='in_progress'?'进行中':item.availability_state==='locked'?'已锁定':item.availability_state==='scheduled'?'已安排':URGENCY_LABELS[item.urgency]||'可安排',importance_label:item.importance==='high'?'高':item.importance==='low'?'低':'普通'}))
}
export function workDuration(minutes){
  if(!Number.isFinite(minutes))return '时长待核对'
  const hours=Math.floor(minutes/60),rest=minutes%60
  return `${hours?hours+'小时':''}${rest||!hours?rest+'分钟':''}`
}
export function attentionDeadline(value,now){
  const time=shanghaiTime(value),day=time.slice(0,10),today=now?shanghaiTime(now).slice(0,10):''
  return `${day===today?'今天':day.slice(5).replace('-','月')+'日'} ${time.slice(11,16)}截止`
}
export function recommendationLabel(recommendation,now){
  return (recommendation.items||[]).map(item=>{
    const a=shanghaiTime(item.start_at),b=shanghaiTime(item.end_at)
    return `${a.slice(0,10)===shanghaiTime(now).slice(0,10)?'':a.slice(5,10)+' '}${a.slice(11,16)}–${b.slice(11,16)}`
  }).join('、')
}
export const PRIORITIES={high:'重要',normal:'普通',low:'较低'}
