import {useEffect,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import {getConversationSummaries,createConversationSummary,getSummaryRequest} from '../api.js'
import EditRecovery,{useEditRecovery} from './EditRecovery.jsx'

export default function ConversationSummary({workspace,id,active,onLocate,unavailable,triggerTarget}){
  const [open,setOpen]=useState(false),[rows,setRows]=useState([]),[request,setRequest]=useState(null),[operation,setOperation]=useState(null)
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0),alive=useRef(true)
  useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[])
  const recovery=useEditRecovery({workspace,resource:`summary-request:${id}`,base:id?`summary-v1:${id}`:undefined,value:{request},dirty:Boolean(request),automatic:true,restore:value=>{setRequest(value.request);setOpen(true)}})
  useEffect(()=>{
    if(!active||!open||unavailable)return
    let valid=true;getConversationSummaries(id).then(page=>{if(valid)setRows(page.items)}).catch(cause=>{if(valid)setError(cause.message)})
    return()=>{valid=false}
  },[id,active,open,revision,unavailable])
  useEffect(()=>{
    if(!request||!active||!open||unavailable)return
    let valid=true,timer
    async function read(){
      try{const result=await getSummaryRequest(id,request.client_request_id);if(!valid)return;setOperation(result)
        if(result.status==='running')timer=setTimeout(read,1200)
        else if(result.status==='completed'){setRequest(null);setRevision(v=>v+1)}
      }catch(cause){if(valid&&cause.status!==404)setError(cause.message)}
    }
    read();return()=>{valid=false;clearTimeout(timer)}
  },[request?.client_request_id,active,open,id,unavailable])
  async function generate(){
    if(busy)return;setBusy(true);setError('')
    const payload=request||{client_request_id:crypto.randomUUID()};setRequest(payload)
    try{const result=await createConversationSummary(id,{...payload,...(request&&operation&&['failed','interrupted','cancelled'].includes(operation.status)?{retry_attempt:operation.attempt}:{})});if(alive.current){setOperation(result);if(result.status==='completed'){setRequest(null);setRevision(v=>v+1)}}}
    catch(cause){if(alive.current){setError(cause.message);getSummaryRequest(id,payload.client_request_id).then(result=>{if(alive.current){setOperation(result);if(result.status==='completed'){setRequest(null);setRevision(v=>v+1);setError('原请求已保存小结，已核对结果。')}}}).catch(()=>{})}}
    finally{if(alive.current)setBusy(false)}
  }
  const trigger=<button className="button subtle conversation-summary-button" aria-expanded={open} aria-controls={open?`conversation-summary-${id}`:undefined} disabled={unavailable} onClick={()=>setOpen(!open)}>查看会话小结</button>
  return <>{triggerTarget?createPortal(trigger,triggerTarget):trigger}
    {open&&<section id={`conversation-summary-${id}`} className="summary-content conversation-summary" aria-label="会话小结"><EditRecovery recovery={recovery} label="小结请求"/><p className="helper">主动生成才会调用 AI。只整理有界历史，不创建任务、复盘或长期记忆。</p>
      {error&&<p role="alert" className="error-box">{error}</p>}{operation?.status==='running'&&<p role="status">小结生成中，可离开此处，返回后查询同一请求。</p>}
      <button className="button secondary" disabled={busy||operation?.status==='running'} onClick={generate}>{request?'核对并重试原请求':rows.length?'重新生成会话小结':'生成会话小结'}</button>
      {!rows.length&&!busy&&<p>尚未生成小结。</p>}
      {rows.map(row=><article key={row.id}><h3>会话小结 v{row.version}</h3><small>{new Date(row.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</small><p className="helper">{row.coverage.note} 本次 {row.coverage.message_count} 条。</p>
        {Object.entries({themes:'主题',conclusions:'讨论结论',questions:'未决定事项',followups:'可选后续'}).map(([key,label])=>row.summary[key].length>0&&<section key={key}><h4>{label}</h4>{row.summary[key].map((item,index)=><div key={index}><p>{item.text}</p>{row.source.available?item.message_ids.map(mid=><button className="button subtle" key={mid} onClick={()=>{setOpen(false);onLocate?.(mid)}}>回到原消息</button>):<p role="status">原消息来源不可用。</p>}</div>)}</section>)}
      </article>)}
    </section>}
  </>
}
