// Editors stay mounted across navigation. A send must settle valid local edits
// before asking AI to read/modify a draft. No business facts live in this map.
const editors=new Map()
export function registerEditor(key,editor){editors.set(key,editor);return()=>{if(editors.get(key)===editor)editors.delete(key)}}
export function hasUnsavedDraft(){return [...editors.values()].some(editor=>editor.dirty())}
export async function coordinateDrafts(){
  const refs=[]
  for(const editor of editors.values()){
    if(editor.dirty())await editor.save()
    const ref=await editor.reference?.()
    if(ref)refs.push(ref)
  }
  return refs
}

export const editableDraft=draft=>draft?.status==='ready'||Boolean(draft?.content?.schedule)&&['needs_input','conflict','no_plan'].includes(draft?.status)
// Dirty edits may resolve needs_input. The server must recalculate and return
// ready before confirmation; this only enables submitting the current editor.
export const canConfirmDraft=(draft,dirty)=>Boolean(editableDraft(draft)&&(dirty||draft.status==='ready'&&!draft.unresolved?.length))
export function previewCompletionDeadline(draft){
  if(!draft?.schedule_target)return null
  const items=(draft.items||[]).filter(item=>item.ref===draft.schedule_target&&Number.isFinite(Date.parse(item.end_at)))
  return items.reduce((latest,item)=>!latest||Date.parse(item.end_at)>Date.parse(latest)?item.end_at:latest,null)
}
