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
