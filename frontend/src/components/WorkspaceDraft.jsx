import { useEffect,useRef,useState } from 'react'
import { getWorkspaceDraft,editWorkspaceDraft,actWorkspaceDraft } from '../api.js'
import { registerEditor,editableDraft,canConfirmDraft,previewCompletionDeadline } from '../draftCoordination.js'
import { BreakdownEditor } from './TaskBreakdown.jsx'
import { editableContent,breakdownPayload } from '../taskHierarchy.js'
import EditRecovery,{useEditRecovery} from './EditRecovery.jsx'
import { toDatetimeLocalValue,toBackendDeadline } from '../datetime.js'
import { shiftDate } from '../calendar.js'

export const draftLabels={planning:'日程方案',breakdown:'任务拆解',profile:'档案修改',feedback:'执行反馈',review_record:'复盘记录'}
export const draftEvent=()=>window.dispatchEvent(new Event('sga-drafts-changed'))
const statusLabels={ready:'待审核',applied:'已保存',stale:'资料已变化',superseded:'已有更新版本',discarded:'已放弃',conflict:'存在冲突',needs_input:'需要补充信息',no_plan:'尚无完整方案'}
const fieldLabels={title:'名称',description:'说明',duration_minutes:'预计分钟',deadline:'截止时间',motivation:'为什么重要',weekly_target:'每周目标',unit_label:'单位',name:'名称',actual_minutes:'实际投入分钟',remaining_minutes:'剩余分钟',reason:'原因',summary:'回顾摘要',conclusion:'我的结论',next_steps:'下一步（可空）',priority:'优先顺序',text:'参考说明',hours:'小时',start:'开始时间',end:'结束时间',due_date:'目标日期',metric_kind:'衡量方式',goal_type:'目标类型',enabled:'启用'}
fieldLabels.fixed_start='指定开始时间'
fieldLabels.splittable='允许分段'
fieldLabels.min_block_minutes='最小分段分钟'
fieldLabels.max_segments='最多分段数'
const sourceLabels={user_explicit:'你提供',conversation_context:'前文提供',confirmed_preference:'已确认偏好',system_default:'系统默认，可修改',unresolved:'未设置',formal_task:'正式任务'}
export function PreviewDetails({draft}){
  const value=draft?.content?.schedule
  return <>{value&&<div className="helper"><p>建议起点：{value.day} {value.start_time}（{sourceLabels[draft.field_sources?.start_time]||'暂定'}）</p><p>预计工作时长：{value.duration_minutes}分钟（{sourceLabels[draft.field_sources?.duration_minutes]||'暂定'}）{value.segments>1?`，分${value.segments}段；段间休息${value.break_minutes}分钟，不计入工作时长`:''}</p><p>硬截止时间：{value.deadline?toDatetimeLocalValue(value.deadline).replace('T',' '):'未设置'}</p></div>}
    {draft?.unresolved?.map(note=><p className="recovery-note" key={note}>{note}</p>)}{draft?.notices?.filter((note,index,all)=>all.indexOf(note)===index).map(note=><p className="helper" key={note}>{note}</p>)}</>
}
function ScheduleFields({value,onChange}){
  return <><Fields value={{title:value.title,duration_minutes:value.duration_minutes,deadline:value.deadline,priority:value.priority}} onChange={next=>onChange({...value,...next})}/><div className="form-grid"><label>希望完成日期<input type="date" value={value.day} onChange={e=>onChange({...value,day:e.target.value})}/></label><label>建议开始时间<input type="time" step="300" value={value.start_time} onChange={e=>onChange({...value,start_time:e.target.value,start_exact:true})}/></label><label>工作分段数<input type="number" min="1" max="8" value={value.segments} onChange={e=>onChange({...value,segments:Number(e.target.value)})}/></label><label>段间休息分钟<input type="number" min="0" max="120" step="5" value={value.break_minutes} onChange={e=>onChange({...value,break_minutes:Number(e.target.value)})}/></label></div></>
}
function Fields({value,onChange}){
  return <div className="form-grid">{Object.entries(value).map(([key,item])=>{
    if(['fields','parameters','settings','profile'].includes(key)&&item&&typeof item==='object')return <Fields key={key} value={item} onChange={next=>onChange({...value,[key]:next})}/>
    if(['metric_kind','goal_type','status','adjustment_mode','mode','priority'].includes(key)){
      const options=key==='metric_kind'?[['time','投入时长'],['count','次数'],['deliverable','成果物']]:key==='goal_type'?[['long_term','长期'],['stage','阶段']]:key==='status'?[['active','进行中'],['paused','暂停'],['completed','已完成'],['archived','归档']]:key==='priority'?(typeof item==='number'?[[1,'最优先'],[2,'重要'],[3,'保持推进']]:[['high','高'],['normal','普通'],['low','低']]):[['balanced','兼顾'],['preference','习惯优先'],['stable','稳定优先']]
      return <label key={key}>{fieldLabels[key]||'安排取舍'}<select value={item} onChange={e=>onChange({...value,[key]:typeof item==='number'?Number(e.target.value):e.target.value})}>{options.map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></label>
    }
    if(key==='enabled'||key==='splittable')return <label key={key}>{fieldLabels[key]||'启用'}<input type="checkbox" checked={Boolean(item)} onChange={e=>onChange({...value,[key]:e.target.checked})}/></label>
    if(key==='outcome')return <label key={key}>执行结果<select value={item} onChange={e=>onChange({...value,[key]:e.target.value})}><option value="completed">完成</option><option value="partial">部分完成</option><option value="postponed">暂缓</option></select></label>
    if(!fieldLabels[key]||item&&typeof item==='object')return null
    const number=['duration_minutes','weekly_target','actual_minutes','remaining_minutes','hours'].includes(key)||typeof item==='number'
    const date=key==='deadline'||key==='fixed_start'
    return <label key={key}>{fieldLabels[key]}{['summary','conclusion','next_steps','description','motivation','reason'].includes(key)?<textarea aria-label={fieldLabels[key]} value={item||''} onChange={e=>onChange({...value,[key]:e.target.value})}/>:<input type={date?'datetime-local':key==='due_date'?'date':number?'number':'text'} value={date?toDatetimeLocalValue(item):item??''} onChange={e=>onChange({...value,[key]:date?(e.target.value?toBackendDeadline(e.target.value):null):number?(e.target.value===''?null:Number(e.target.value)):e.target.value})}/>}</label>
  })}</div>
}

export function ReviewFields({value,onChange,sidebar=false}){
  return <><label>标题<input required maxLength={160} value={value.title} onChange={e=>onChange({...value,title:e.target.value})}/></label>{[['summary','回顾摘要'],['conclusion','我的结论'],['next_steps','下一步（可空）']].map(([key,label])=><label key={key}>{label}<textarea aria-label={label} rows={sidebar?(key==='summary'?6:4):undefined} maxLength={key==='next_steps'?4000:6000} value={value[key]||''} onChange={e=>onChange({...value,[key]:e.target.value})}/></label>)}</>
}

function ReviewPeriod({value}){
  return <p className="review-draft-period"><time dateTime={value.start_date}>{value.start_date}</time><span>至</span><time dateTime={shiftDate(value.end_date,-1)}>{shiftDate(value.end_date,-1)}</time></p>
}

function ReviewReading({value}){
  return <article className="review-draft-reading" aria-label="已保存的复盘内容">
    <header><h3>{value.title}</h3><ReviewPeriod value={value}/></header>
    {[['summary','回顾摘要'],['conclusion','我的结论'],['next_steps','下一步']].map(([key,label])=><section key={key}><h4>{label}</h4><p className={!value[key]?'muted':undefined}>{value[key]||'未填写'}</p></section>)}
  </article>
}

export default function WorkspaceDraft({workspace,kind,id,onSaved,onClose}){
  const [draft,setDraft]=useState(null),[value,setValue]=useState(null),[dirty,setDirty]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false),[remote,setRemote]=useState(null)
  const [readRetry,setReadRetry]=useState(0),[loading,setLoading]=useState(true)
  const current=useRef(null);current.current={draft,value,dirty}
  const recovery=useEditRecovery({workspace,resource:`shared-draft:${kind}:${id}`,base:draft?.version,value:{value},dirty,
    restore:saved=>{setValue(saved.value);setDirty(true)}})
  function adopt(next){const content=kind==='breakdown'?editableContent(next.content):next.content;current.current={draft:next,value:content,dirty:false};setDraft(next);setValue(content);setDirty(false);setRemote(null)}
  useEffect(()=>{let alive=true;setLoading(true);setError('');getWorkspaceDraft(kind,id).then(async next=>{
    // Generic planning edits create an immutable replacement. Refreshing its
    // original link must reopen the server's latest version, not a dead card.
    if(next.status==='superseded'&&next.replacement_id)next=await getWorkspaceDraft(kind,next.replacement_id)
    if(alive)adopt(next)
  }).catch(cause=>{if(alive)setError(cause.message)}).finally(()=>{if(alive)setLoading(false)});return()=>{alive=false}},[kind,id,readRetry])
  useEffect(()=>{
    let valid=true
    const read=()=>{const state=current.current;if(!state?.draft)return;getWorkspaceDraft(kind,state.draft.id).then(next=>{
      if(!valid||next.version===current.current?.draft?.version)return
      if(current.current?.dirty)setRemote(next);else adopt(next)
    }).catch(cause=>{if(valid)setError(cause.message)})}
    window.addEventListener('sga-drafts-changed',read)
    return()=>{valid=false;window.removeEventListener('sga-drafts-changed',read)}
  },[kind,id])
  async function save(){
    const state=current.current;if(!state?.draft)throw Error('草案尚未读取完成。')
    if(!state.dirty)return state.draft
    try{
      const payload=kind==='breakdown'?breakdownPayload(state.value):state.value
      const next=await editWorkspaceDraft(kind,state.draft.id,state.draft.version,payload)
      adopt(next);draftEvent();return next
    }catch(cause){setError(cause.message);getWorkspaceDraft(kind,id).then(setRemote).catch(()=>{});throw cause}
  }
  useEffect(()=>registerEditor(`shared:${kind}:${id}`,{dirty:()=>current.current?.dirty||false,save,
    reference:async()=>{if(!current.current?.draft)return null;const latest=await getWorkspaceDraft(kind,current.current.draft.id);return {kind,id:latest.id,version:latest.version}}}),[kind,id])
  function change(next){setValue(next);setDirty(true);setError('')}
  const editable=editableDraft(draft)
  const review=kind==='review_record',savedReview=review&&draft?.status==='applied'
  async function useCompletionDeadline(){
    if(busy)return;setBusy(true);setError('')
    try{
      const saved=await save(),latest=await getWorkspaceDraft(kind,saved.id)
      if(latest.version!==saved.version){setRemote(latest);throw Error('草案已改变，请先比较最新安排，再选择截止时间。')}
      const deadline=previewCompletionDeadline(latest)
      if(!deadline)throw Error('当前没有可采用的候选时段，请先调整安排。')
      change({...saved.content,schedule:{...saved.content.schedule,deadline}})
    }catch(cause){setError(cause.message)}finally{setBusy(false)}
  }
  async function act(action){
    if(busy)return
    if(action==='discard'&&dirty&&!window.confirm('放弃这份草案及未保存的修改？'))return
    setBusy(true);setError('')
    try{
      // Explicit abandonment never requires invalid local fields to be saved.
      const saved=action==='discard'?current.current.draft:await save()
      const latest=await getWorkspaceDraft(kind,saved.id)
      if(latest.version!==saved.version)throw Error('草案已改变，输入保留，请比较后重新读取。')
      if(action==='confirm'&&(latest.status!=='ready'||latest.unresolved?.length)){
        adopt(latest)
        throw Error(latest.unresolved?.join(' ')||'当前安排仍有冲突或信息未补齐，请修改后再确认。')
      }
      const next=await actWorkspaceDraft(kind,saved.id,saved.version,action)
      adopt(next);draftEvent();if(action==='confirm')onSaved?.()
    }catch(cause){setError(cause.message);getWorkspaceDraft(kind,current.current?.draft?.id||id).then(setRemote).catch(()=>{})}finally{setBusy(false)}
  }
  const saveButton=<button className="button secondary" disabled={busy||!dirty||!editable} onClick={()=>{setBusy(true);save().catch(()=>{}).finally(()=>setBusy(false))}}>保存草案编辑</button>
  const confirmButton=<button className="button primary" disabled={busy||!canConfirmDraft(draft,dirty)} onClick={()=>act('confirm')}>{kind==='planning'?'确认采用方案':'确认正式保存'}</button>
  return <section className={`workspace-draft panel${review?' review-draft':''}`} aria-label="共享草案编辑器" data-status={draft?.status}><div className="section-heading"><h2>{draftLabels[kind]}{review?<span className="review-draft-status" role="status">{statusLabels[draft?.status]||'读取中'}</span>:<> · {statusLabels[draft?.status]||'读取中'}</>}</h2><button className="button subtle" disabled={busy} onClick={()=>{if(dirty)setError('有未保存修改，请保存或保留缓存后再关闭。');else onClose?.()}}>关闭草案</button></div>
    {error&&<p className="error-box" role="alert">{error}</p>}<EditRecovery recovery={recovery} label="共享草案编辑"/>
    {remote&&<details open className="recovery-note"><summary>服务端最新内容（本地编辑仍保留）</summary>{kind==='review_record'?<ReviewReading value={remote.content}/>:<fieldset disabled>{remote.content.schedule?<Fields value={remote.content.schedule}/>:<>{(remote.content.operations||remote.content.actions||[]).map((op,index)=><Fields key={index} value={op}/>)}</>}</fieldset>}<button onClick={()=>{if(window.confirm('用服务端版本替换编辑器？本地内容请先保留对照。'))adopt(remote)}}>读取服务器版本</button></details>}
    {draft&&value?savedReview?<>
      <ReviewReading value={value}/>
      {draft.notices?.length>0&&<details className="review-draft-notices"><summary>整理说明</summary><PreviewDetails draft={draft}/></details>}
      <p className="review-draft-receipt">可在复盘页的记录中查看；任务和日程不受影响。</p>
    </>:<>{!review&&<p className="helper">{draft.summary} · {statusLabels[draft.status]||draft.status} {dirty?'· 有未保存修改':''}</p>}{review&&dirty&&<p className="review-draft-unsaved" role="status">有未保存修改</p>}
      <PreviewDetails draft={draft}/>
      {editable&&value.schedule&&!value.schedule.deadline&&<div className="draft-confirm-help"><p>确认前请填写截止时间，也可以明确选择以本次安排结束时间为截止。</p><button className="button secondary" disabled={busy||!previewCompletionDeadline(draft)} onClick={useCompletionDeadline}>以安排结束时间作为截止</button></div>}
      <fieldset disabled={busy||!editable} className="draft-editor-fields">
      {kind==='breakdown'?<BreakdownEditor content={value} expected={value.children.reduce((sum,c)=>sum+Number(c.duration_minutes||0),0)} onChange={change}/>:
        value.schedule?<ScheduleFields value={value.schedule} onChange={schedule=>change({schedule})}/>:
        kind==='review_record'?<><ReviewPeriod value={value}/><ReviewFields value={value} onChange={change} sidebar/></>:
        <>{(value.operations||value.actions||[]).map((op,index)=><section className="draft-operation" key={index}><h3>{op.op==='add'?'新增任务建议':kind==='planning'?'任务安排建议':op.op==='record_feedback'?'执行反馈建议':op.op==='create_goal'?'目标建议':'资料修改建议'}</h3><Fields value={op} onChange={next=>{const key=kind==='planning'?'actions':'operations';change({...value,[key]:value[key].map((old,i)=>i===index?next:old)})}}/></section>)}</>}
      </fieldset>{kind==='planning'&&draft.items.length>0&&<details open><summary>{draft.status==='applied'?'已采用安排':'候选安排 · 尚未正式采用'}</summary>{draft.items.map((item,index)=><p key={index}>{item.title} · {toDatetimeLocalValue(item.start_at).replace('T',' ')} 至 {toDatetimeLocalValue(item.end_at).replace('T',' ')}</p>)}</details>}<div className={`button-row${review?' review-draft-actions':''}`}>{review&&confirmButton}{saveButton}{!review&&confirmButton}<button className="button subtle" disabled={busy||draft.status==='applied'} onClick={()=>act('discard')}>放弃草案</button></div>
      {draft.receipt&&<p role="status">保存结果：已正式保存。{kind==='planning'?'任务与日程已刷新。':kind==='review_record'?'可在复盘记录中查看。':'可到对应页面查看。'}</p>}<p className="helper">{draft.status==='applied'?'这份草案已经保存。如需调整，请基于最新正式记录生成新的草案。':review?'保存编辑仅暂存草案，确认后才存入复盘记录，不改变任务或日程。':'保存编辑仍是草案；只有确认后才写入正式业务。旧卡片与冲突版本无法直接执行。'}</p>
    </>:loading?<p role="status">正在读取草案…</p>:<button className="button secondary" onClick={()=>setReadRetry(v=>v+1)}>重试读取草案</button>}
  </section>
}

export function DraftCard({reference,active,onOpen}){
  const [current,setCurrent]=useState(null),[error,setError]=useState('')
  useEffect(()=>{
    if(!active)return
    let alive=true
    const read=()=>getWorkspaceDraft(reference.kind,reference.id).then(next=>{if(alive)setCurrent(next)}).catch(cause=>{if(alive)setError(cause.message)})
    read();window.addEventListener('sga-drafts-changed',read);return()=>{alive=false;window.removeEventListener('sga-drafts-changed',read)}
  },[reference.kind,reference.id,active])
  return <section className="workspace-draft" data-draft-kind={reference.kind} data-draft-id={reference.id}><strong>{draftLabels[reference.kind]} · {statusLabels[current?.status]||'读取中'}</strong><p>{current?.summary||reference.summary}</p><PreviewDetails draft={current}/>{error&&<p role="alert">{error}</p>}{current&&<button className="button secondary" onClick={()=>onOpen({page:reference.kind==='review_record'?'review':reference.kind==='profile'?'profile':'schedule',kind:reference.kind,id:current.replacement_id||current.id})}>查看最新草案</button>}</section>
}
