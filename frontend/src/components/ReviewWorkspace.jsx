import {useEffect,useRef,useState} from 'react'
import {getReviewFacts,getReviewRecords,getReviewRecord,saveReviewRecord} from '../api.js'
import {reviewRange,shiftDate} from '../calendar.js'
import {ReviewFields} from './WorkspaceDraft.jsx'
import EditRecovery,{useEditRecovery} from './EditRecovery.jsx'
import {tabKeyboard,recordedTime} from '../workbench.js'

export default function ReviewWorkspace({workspace,today,active,refreshVersion,onDiscuss,onSaved,onOpenTask,resource}){
  const [tab,setTab]=useState('facts'),[period,setPeriod]=useState('week'),[date,setDate]=useState(today),[facts,setFacts]=useState(null),[filter,setFilter]=useState('all'),[sourceIds,setSourceIds]=useState(null),[group,setGroup]=useState('day')
  const [rows,setRows]=useState([]),[next,setNext]=useState(null),[query,setQuery]=useState(''),[search,setSearch]=useState(''),[recordPeriod,setRecordPeriod]=useState(''),[recordStart,setRecordStart]=useState(''),[recordEnd,setRecordEnd]=useState('')
  const [editor,setEditor]=useState(null),[baseline,setBaseline]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[changed,setChanged]=useState(0),[remote,setRemote]=useState(null)
  const requestId=useRef(null),generation=useRef(0)
  const [factsLoading,setFactsLoading]=useState(true),[factsError,setFactsError]=useState(''),[listLoading,setListLoading]=useState(true),[listError,setListError]=useState(''),[moreLoading,setMoreLoading]=useState(false),listGeneration=useRef(0)
  const [start,end]=reviewRange(date,period)
  const [editorId,setEditorId]=useState(null)
  const selectionRecovery=useEditRecovery({workspace,resource:'review-editor-selection',base:today?'review-editor-v1':undefined,value:{id:editorId},dirty:Boolean(editorId),automatic:true,restore:value=>{if(Number.isSafeInteger(value.id)&&value.id>0)setEditorId(value.id)}})
  useEffect(()=>{
    if(!editorId)return
    let valid=true
    getReviewRecord(editorId).then(row=>{if(valid){setBaseline({id:row.id,version:row.version});setEditor(row)}}).catch(cause=>{if(valid)setError(cause.message)})
    return()=>{valid=false}
  },[editorId])
  const uiRecovery=useEditRecovery({workspace,resource:'review-view',base:today?'review-view-v1':undefined,value:{tab,period,date},dirty:true,automatic:true,restore:value=>{if(['facts','records'].includes(value.tab))setTab(value.tab);if(['day','week','month'].includes(value.period))setPeriod(value.period);if(/^20\d\d-\d\d-\d\d$/.test(value.date))setDate(value.date)}})
  const recovery=useEditRecovery({workspace,resource:`review-record-editor:${editor?.id||'new'}`,base:editor?.id?(baseline?JSON.stringify(baseline):undefined):facts?'manual-new':undefined,
    value:{editor},dirty:Boolean(editor),restore:saved=>setEditor(saved.editor)})
  useEffect(()=>{
    if(!active||tab!=='facts')return
    const token=++generation.current;setFactsError('');setFactsLoading(true);setFacts(null);setSourceIds(null)
    getReviewFacts(start,end).then(value=>{if(token===generation.current)setFacts(value)}).catch(cause=>{if(token===generation.current)setFactsError(cause.message)}).finally(()=>{if(token===generation.current)setFactsLoading(false)})
    return()=>{generation.current++}
  },[active,tab,start,end,refreshVersion,changed])
  useEffect(()=>{
    if(!active||tab!=='records')return
    const token=++listGeneration.current;setListLoading(true);setListError('');setMoreLoading(false)
    getReviewRecords({q:search,period:recordPeriod,start:recordStart,end:recordEnd}).then(value=>{if(token===listGeneration.current){setRows(value.items);setNext(value.next_offset)}}).catch(cause=>{if(token===listGeneration.current)setListError(cause.message)}).finally(()=>{if(token===listGeneration.current)setListLoading(false)})
    return()=>{listGeneration.current++}
  },[active,tab,search,recordPeriod,recordStart,recordEnd,changed,refreshVersion])
  function blank(){
    if(editor){setError('当前编辑尚未关闭，请先保存或保留本地内容。');return}
    setBaseline('manual-new');requestId.current=crypto.randomUUID()
    setEditor({period,start_date:start,end_date:end,title:'',summary:'',conclusion:'',next_steps:'',requestId:requestId.current});setRemote(null)
  }
  async function more(){
    if(moreLoading||listLoading||next===null)return
    const token=listGeneration.current;setMoreLoading(true);setListError('')
    try{const page=await getReviewRecords({q:search,period:recordPeriod,start:recordStart,end:recordEnd,offset:next});if(token===listGeneration.current){setRows(old=>[...old,...page.items]);setNext(page.next_offset)}}
    catch(cause){if(token===listGeneration.current)setListError(cause.message)}finally{if(token===listGeneration.current)setMoreLoading(false)}
  }
  async function open(id){
    if(editor){setError('当前有编辑内容，请先处理再打开另一条记录。');return}
    try{const row=await getReviewRecord(id);setBaseline({id:row.id,version:row.version});setEditor(row);setEditorId(id);setRemote(null)}catch(cause){setError(cause.message)}
  }
  async function save(event){
    event.preventDefault();if(busy)return;setBusy(true);setError('')
    const content=Object.fromEntries(['period','start_date','end_date','title','summary','conclusion','next_steps'].map(k=>[k,editor[k]]))
    try{
      const payload=editor.id?{...content,expected_version:baseline.version}:{...content,client_request_id:editor.requestId||(requestId.current||=(crypto.randomUUID()))}
      await saveReviewRecord(payload,editor.id);setEditor(null);setEditorId(null);setBaseline(null);requestId.current=null;setChanged(v=>v+1);onSaved?.();setTab('records')
    }catch(cause){setError(cause.message);if(editor.id)getReviewRecord(editor.id).then(setRemote).catch(()=>{})}finally{setBusy(false)}
  }
  const matching=(facts?.sources||[]).filter(item=>(filter==='all'||item.states.includes(filter))&&(!sourceIds||sourceIds.includes(item.task_id)))
  const monthStep=direction=>{const value=new Date(date+'T12:00:00Z');value.setUTCDate(1);value.setUTCMonth(value.getUTCMonth()+direction);return value.toISOString().slice(0,10)}
  return <section className="review-workspace" aria-label="回顾与复盘记录">
    <EditRecovery recovery={selectionRecovery} label="记录选择"/><EditRecovery recovery={uiRecovery} label="回顾界面"/><EditRecovery recovery={recovery} label="复盘记录编辑"/>
    <div role="tablist" aria-label="复盘内容" onKeyDown={tabKeyboard}>{[['facts','回顾'],['records','复盘记录']].map(([key,label])=><button key={key} id={'review-tab-'+key} aria-controls={'review-panel-'+key} className="button secondary" role="tab" tabIndex={tab===key?0:-1} aria-selected={tab===key} onClick={()=>setTab(key)}>{label}</button>)}</div>
    {error&&<p className="error-box" role="alert">{error}</p>}
    <div id="review-panel-facts" role="tabpanel" aria-labelledby="review-tab-facts" hidden={tab!=='facts'} inert={tab!=='facts'}>
      <div className="calendar-toolbar review-range-toolbar"><div role="group" aria-label="回顾周期">{[['day','日'],['week','周'],['month','月']].map(([key,label])=><button className="button subtle" aria-pressed={period===key} key={key} onClick={()=>{setPeriod(key);setSourceIds(null)}}>{label}</button>)}</div>
      <div className="review-date-navigation"><button className="button subtle" aria-label="回顾上一段" onClick={()=>setDate(period==='month'?monthStep(-1):shiftDate(date,period==='week'?-7:-1))}>‹</button><label><span className="visually-hidden">回顾日期</span><input type="date" value={date} min="2000-01-01" max="2100-12-31" onChange={e=>{if(e.target.value)setDate(e.target.value)}}/></label><button className="button subtle" aria-label="回顾下一段" onClick={()=>setDate(period==='month'?monthStep(1):shiftDate(date,period==='week'?7:1))}>›</button></div><button className="button subtle" onClick={()=>setDate(today)}>回到当前</button></div>
      <p>{start} 至 {shiftDate(end,-1)}</p>
      {factsError?<p className="error-box" role="alert">{factsError}<button className="button subtle" onClick={()=>setChanged(v=>v+1)}>重试回顾事实</button></p>:facts?<><div className="review-metrics">{[['completed','已确认完成',facts.completed_count+' 项'],['recorded','已记录投入',recordedTime(facts.known_minutes,facts.unknown_count,facts.feedback_ids.length)],['pending','待反馈安排',facts.pending_count+' 项']].map(([key,label,value])=><button className="metric-card" key={key} onClick={()=>{setFilter(key==='recorded'?'all':key);setSourceIds(key==='recorded'?facts.task_ids:null)}}><span>{label}</span><strong className={key==='recorded'&&!facts.feedback_ids.length?'metric-empty':undefined}>{value}</strong></button>)}</div>
        <details className="review-definitions"><summary>统计口径{facts.unknown_count>0?` · ${facts.unknown_count} 条反馈耗时未知`:''}</summary><p className="helper">{facts.note}</p></details>
        <div className="section-heading"><h3>时间花在哪里</h3><div className="button-row"><button className="button subtle" aria-pressed={group==='day'} onClick={()=>setGroup('day')}>按天</button><button className="button subtle" aria-pressed={group==='category'} onClick={()=>setGroup('category')}>按类别</button></div></div>
        <div className="time-distribution">{(group==='day'?facts.by_day:facts.by_category).map(item=><button className="time-bar" key={item.date||item.key} onClick={()=>{setSourceIds(item.task_ids);setFilter('all')}}><span>{item.date||item.name}</span><meter aria-label="已知投入分钟" min="0" max={Math.max(1,facts.known_minutes)} value={item.known_minutes}/><span>{recordedTime(item.known_minutes,item.unknown_count)}</span></button>)}</div>
        <div className="button-row" aria-label="回顾事项筛选">{[['all','全部'],['completed','已完成'],['partial','部分完成'],['pending','待反馈']].map(([key,label])=><button className="button subtle" aria-pressed={filter===key} key={key} onClick={()=>{setFilter(key);setSourceIds(null)}}>{label}</button>)}</div>
        {!matching.length?<p className="growth-empty">目前没有符合范围的记录。</p>:matching.map(item=><article className="review-source" key={item.task_id}><strong>{item.title}</strong><span>{recordedTime(item.known_minutes,item.unknown_count,item.feedback_ids.length)}</span><details><summary>查看来源</summary><p>{item.feedback_ids.length}条有效反馈，其中{item.completion_feedback_ids.length}条为完成记录。待反馈安排不计为未完成。</p></details><button className="button subtle" onClick={()=>onOpenTask?.(item.task_id)}>查看任务与反馈</button></article>)}
        {facts.goals.length>0&&<section><h3>有关联记录的目标进展</h3>{facts.goals.map(goal=><p key={goal.id}>{goal.title}：{goal.metric_kind==='time'?recordedTime(goal.value,goal.unknown_count):`${goal.value} ${goal.unit}`} · {goal.note}</p>)}</section>}
      </>:factsLoading&&<p role="status">正在读取事实…</p>}
      <div className="button-row"><button className="button secondary" onClick={()=>onDiscuss?.({start,end,period})}>和 AI 复盘</button><button className="button secondary" onClick={blank}>自己写几句</button></div>
    </div>
    <div id="review-panel-records" role="tabpanel" aria-labelledby="review-tab-records" hidden={tab!=='records'} inert={tab!=='records'}>
      <form className="calendar-toolbar" onSubmit={e=>{e.preventDefault();setSearch(query)}}><label>搜索复盘记录<input type="search" value={query} onChange={e=>setQuery(e.target.value)}/></label><button className="button subtle">搜索记录</button><label>记录周期<select value={recordPeriod} onChange={e=>setRecordPeriod(e.target.value)}><option value="">全部</option><option value="day">日</option><option value="week">周</option><option value="month">月</option></select></label><label>记录范围起<input type="date" value={recordStart} onChange={e=>setRecordStart(e.target.value)}/></label><label>记录范围止<input type="date" value={recordEnd} onChange={e=>setRecordEnd(e.target.value)}/></label></form>
      {listLoading?<p role="status">正在读取复盘记录…</p>:listError?<p className="error-box" role="alert">{listError}<button className="button subtle" onClick={()=>setChanged(v=>v+1)}>重试复盘记录</button></p>:!rows.length&&<p className="growth-empty">尚无符合条件的正式复盘记录。</p>}
      {!listLoading&&!listError&&rows.map(row=><article className="review-record" key={row.id}><h3>{row.title}</h3><p>{row.start_date} 至 {shiftDate(row.end_date,-1)}</p><p>{row.summary}</p><button className="button secondary" onClick={()=>open(row.id)}>查看或编辑记录</button></article>)}
      {!listLoading&&!listError&&next!==null&&<button className="button subtle" disabled={moreLoading} onClick={more}>{moreLoading?'正在读取…':'更多复盘记录'}</button>}
    </div>
    {editor&&<form className="review-record-editor growth-form" onSubmit={save} aria-label="复盘记录编辑器"><h3>{editor.id?'编辑复盘记录':'自己写几句'}</h3><p>{editor.start_date} 至 {editor.end_date}</p><ReviewFields value={editor} onChange={setEditor}/>
      {remote&&<details open className="recovery-note"><summary>最新记录对照</summary><h4>{remote.title}</h4><p>{remote.summary}</p><p>{remote.conclusion}</p><p>{remote.next_steps}</p><button type="button" onClick={()=>{if(window.confirm('用服务器最新内容替换编辑器？请先保留需要的本地文字。')){setBaseline({id:remote.id,version:remote.version});setEditor(remote);setRemote(null)}}}>载入最新记录</button></details>}
      {editor.facts&&<details><summary>保存时的事实与来源</summary><p>已确认完成 {editor.facts.completed_count} 项；{recordedTime(editor.facts.known_minutes,editor.facts.unknown_count,editor.facts.feedback_ids?.length)}。</p>{editor.sources?.conversation_id&&<p>此记录关联已保存的讨论原文。</p>}{editor.history?.map((entry,index)=><details key={index}><summary>第{index+1}次修改</summary><p>{entry.title}</p><p>{entry.summary}</p><p>{entry.conclusion}</p></details>)}</details>}
      <div className="button-row"><button className="button primary" disabled={busy}>明确保存复盘记录</button><button className="button subtle" type="button" onClick={()=>{if(window.confirm('放弃本次未提交编辑？')){setEditor(null);setEditorId(null);setBaseline(null)}}}>放弃本次编辑</button></div><p className="helper">保存复盘只保存文字和当时事实，不改变任务或日程。未提交内容可从本标签页缓存恢复。</p>
    </form>}
  </section>
}
