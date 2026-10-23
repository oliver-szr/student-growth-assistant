import {useEffect,useRef,useState} from 'react'
import {getMemories,getMemory,createMemory,editMemory,actMemory} from '../api.js'
import EditRecovery,{useEditRecovery} from './EditRecovery.jsx'

const scopes={general:'一般交流',study:'学习讨论',planning:'安排建议',review:'回顾讨论',profile:'个人资料'}
const statuses={suggested:'待确认',confirmed:'已确认',disabled:'已停用',deleted:'已移除'}
export function MemoryCard({id,active,onOpen}){
  const [row,setRow]=useState(null),[error,setError]=useState('')
  useEffect(()=>{if(!active)return;let valid=true;getMemory(id).then(value=>{if(valid){setRow(value);setError('')}}).catch(cause=>{if(valid){setRow(null);setError(cause.message)}});return()=>{valid=false}},[id,active])
  return <section className="workspace-draft" aria-label="记忆建议"><strong>长期记忆 · {error?'当前不可用':statuses[row?.status]||'读取中'}</strong>{row&&<p>{row.text}</p>}{error&&<p role="status">{error}</p>}{row&&<button className="button secondary" onClick={()=>onOpen?.({page:'profile',kind:'memory',id})}>审核或管理记忆</button>}<p className="helper">待确认内容不参与长期参考，不改变正式时间规则。</p></section>
}
export default function MemoryPanel({workspace,active,resource,onSource,onPreferences}){
  const [rows,setRows]=useState([]),[next,setNext]=useState(null),[filter,setFilter]=useState('all'),[q,setQ]=useState(''),[search,setSearch]=useState('')
  const [editor,setEditor]=useState(null),[base,setBase]=useState(null),[dirty,setDirty]=useState(false),[remote,setRemote]=useState(null)
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[revision,setRevision]=useState(0)
  const [listLoading,setListLoading]=useState(true),[listError,setListError]=useState(''),[loadingMore,setLoadingMore]=useState(false),listGeneration=useRef(0)
  const [selection,setSelection]=useState(null),mounted=useRef(true),handled=useRef(null)
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
  const selectedRecovery=useEditRecovery({workspace,resource:'memory-selection',base:workspace?'memory-v1':undefined,value:{selection},dirty:Boolean(selection),automatic:true,restore:value=>{if(Number.isSafeInteger(value.selection)&&value.selection>0)setSelection(value.selection)}})
  const recovery=useEditRecovery({workspace,resource:`memory-editor:${selection||'new'}`,base:selection?base?.version:workspace?'manual-memory-v1':undefined,
    value:{editor},dirty,restore:value=>{setEditor(value.editor);setDirty(true)}})
  useEffect(()=>{
    if(!active)return
    const token=++listGeneration.current;setListLoading(true);setListError('');setLoadingMore(false)
    getMemories({status:filter,q:search}).then(page=>{if(token===listGeneration.current){setRows(page.items);setNext(page.next_offset)}}).catch(cause=>{if(token===listGeneration.current)setListError(cause.message)}).finally(()=>{if(token===listGeneration.current)setListLoading(false)})
    return()=>{listGeneration.current++}
  },[active,filter,search,revision])
  useEffect(()=>{
    if(!selection)return
    let valid=true;getMemory(selection).then(row=>{if(valid){setBase(row);setEditor(row);setDirty(false)}}).catch(cause=>{if(valid)setError(cause.message)})
    return()=>{valid=false}
  },[selection])
  useEffect(()=>{
    if(resource?.kind!=='memory'||handled.current===resource.requestKey)return
    handled.current=resource.requestKey
    if(dirty){setError('当前记忆有未保存编辑，请先保存或处理。');return}
    setBase(null);setEditor(null);setSelection(resource.id)
  },[resource?.requestKey])
  function changed(value){setEditor(value);setDirty(true);setError('')}
  async function more(){
    if(loadingMore||listLoading||next===null)return
    const token=listGeneration.current;setLoadingMore(true);setListError('')
    try{const page=await getMemories({q:search,status:filter,offset:next});if(token===listGeneration.current){setRows(old=>[...old,...page.items]);setNext(page.next_offset)}}
    catch(cause){if(token===listGeneration.current)setListError(cause.message)}finally{if(token===listGeneration.current)setLoadingMore(false)}
  }
  async function save(event){
    event.preventDefault();if(busy||!editor)return;setBusy(true);setError('')
    try{
      const content={text:editor.text,scope:editor.scope}
      const row=selection?await editMemory(selection,{...content,expected_version:base.version}):await createMemory({...content,client_request_id:editor.requestId})
      if(!mounted.current)return
      recovery.discard()
      setBase(row);setEditor(null);setSelection(null);setDirty(false);setRevision(v=>v+1);setNotice('记忆已保存；不会修改任务、目标或排程。')
    }catch(cause){if(mounted.current){setError(cause.message);if(selection)getMemory(selection).then(setRemote).catch(()=>{})}}finally{if(mounted.current)setBusy(false)}
  }
  async function act(row,action){
    if(busy)return
    if(dirty){setError('有未提交编辑，请先处理，避免状态操作覆盖输入。');return}
    setBusy(true);setError('')
    try{const updated=await actMemory(row.id,{expected_version:row.version,action});if(mounted.current){if(selection===row.id){setBase(updated);setEditor(action==='delete'?null:updated);if(action==='delete')setSelection(null)}setRevision(v=>v+1);setNotice(action==='delete'?'已从活动检索中移除；历史聊天和已有备份可能保留原文。':'记忆状态已更新。')}}
    catch(cause){if(mounted.current)setError(cause.message)}finally{if(mounted.current)setBusy(false)}
  }
  return <section className="memory-panel" aria-label="长期记忆管理">
    <h3>记忆</h3><p className="helper">只有你确认的有效记忆才供后续相关交流参考。记忆不替代正式任务、目标或时间约束，请勿填写密码和密钥。</p>
    <EditRecovery recovery={selectedRecovery} label="记忆选择"/><EditRecovery recovery={recovery} label="记忆编辑"/>
    {error&&<p className="error-box" role="alert">{error}{error.includes('排程约束')&&<button type="button" className="button subtle" onClick={onPreferences}>查看正式偏好</button>}</p>}{notice&&<p role="status">{notice}</p>}
    <form className="calendar-toolbar" onSubmit={e=>{e.preventDefault();setSearch(q)}}><label>搜索记忆<input type="search" value={q} maxLength={100} onChange={e=>setQ(e.target.value)}/></label><button className="button subtle">搜索</button><label>记忆状态<select value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">全部</option>{Object.entries(statuses).filter(([key])=>key!=='deleted').map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label></form>
    <button className="button secondary" disabled={busy} onClick={()=>{if(dirty){setError('请先处理当前编辑。');return}setSelection(null);setBase(null);setEditor({text:'',scope:'general',requestId:crypto.randomUUID()});setDirty(true)}}>主动新增记忆</button>
    {editor&&<form className="growth-form memory-editor" onSubmit={save} aria-label="记忆编辑器"><h4>{selection?'编辑记忆':'新增长期记忆'}</h4><label>记忆内容<textarea aria-label="记忆内容" required maxLength={1200} value={editor.text} onChange={e=>changed({...editor,text:e.target.value})}/></label><label>适用范围<select aria-label="适用范围" value={editor.scope} onChange={e=>changed({...editor,scope:e.target.value})}>{Object.entries(scopes).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
      {remote&&<details open><summary>服务器最新记忆，本地文字仍保留</summary><p>{remote.text}</p><button type="button" onClick={()=>{if(window.confirm('使用服务器内容替换当前编辑？请先保留本地文字。')){setBase(remote);setEditor(remote);setDirty(false);setRemote(null)}}}>读取最新记忆</button></details>}
      <div className="button-row"><button className="button primary" disabled={busy}>{selection?'保存记忆修改':'明确保存记忆'}</button><button className="button subtle" type="button" onClick={()=>{if(!dirty||window.confirm('放弃未提交的记忆编辑？')){recovery.discard();setEditor(null);setSelection(null);setDirty(false)}}}>关闭编辑</button></div>
    </form>}
    {listLoading?<p role="status">正在读取记忆…</p>:listError?<p className="error-box" role="alert">{listError}<button type="button" className="button subtle" onClick={()=>setRevision(v=>v+1)}>重试记忆列表</button></p>:!rows.length&&<p className="growth-empty">暂无符合条件的记忆。</p>}
    {!listLoading&&!listError&&rows.map(row=><article className="memory-card" key={row.id}><span>{statuses[row.status]} · {scopes[row.scope]}</span><p>{row.text}</p><small>更新于 {new Date(row.updated_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</small>
      <div className="button-row"><button className="button subtle" disabled={busy||dirty} onClick={()=>{setRemote(null);if(selection===row.id){setBase(row);setEditor(row)}else{setBase(null);setEditor(null);setSelection(row.id)}}}>编辑记忆</button>
      {row.status==='suggested'&&<button className="button primary" disabled={busy} onClick={()=>act(row,'confirm')}>确认保存记忆</button>}
      {row.status==='confirmed'&&<button className="button subtle" disabled={busy} onClick={()=>act(row,'disable')}>停用记忆</button>}{row.status==='disabled'&&<button className="button subtle" disabled={busy} onClick={()=>act(row,'enable')}>重新启用</button>}
      <button className="button subtle" disabled={busy} onClick={()=>{if(window.confirm('从正常记忆检索中移除？历史聊天、正式记录和既有备份不会随之销毁。'))act(row,'delete')}}>删除记忆</button>
      {row.source.kind==='conversation'&&(row.source.available?<button className="button subtle" onClick={()=>onSource?.(row.source.conversation_id,row.source.message_ids[0])}>查看记忆来源</button>:<span role="status">来源会话已不可访问；独立确认的记忆仍可管理。</span>)}{row.source.kind==='manual'&&<span>你主动填写</span>}</div>
    </article>)}
    {!listLoading&&!listError&&next!==null&&<button className="button subtle" disabled={loadingMore} onClick={more}>{loadingMore?'正在读取…':'更多记忆'}</button>}
  </section>
}
