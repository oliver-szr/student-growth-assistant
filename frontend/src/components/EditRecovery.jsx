import { useEffect, useRef, useState } from 'react'
import { editKey, readEdit, writeEdit, compatibleEdit } from '../workbench.js'

// The caller provides only editable fields, never a response snapshot or credentials.
export function useEditRecovery({ workspace, resource, base, value, dirty, restore, automatic = false }) {
  const key = editKey(workspace, resource)
  const [saved, setSaved] = useState(null), [warning, setWarning] = useState('')
  const [readyKey, setReadyKey] = useState(null)
  const initialized = useRef(null), originalBase = useRef(base), latest = useRef(null)
  latest.current = { value, dirty, base, restore }
  const encoded = JSON.stringify(value)
  useEffect(() => {
    if (!key || base === undefined || initialized.current === key) return
    initialized.current = key
    originalBase.current = base
    try {
      const previous = readEdit(window.sessionStorage, key)
      if(previous && !compatibleEdit(previous.value,latest.current.value)) throw new Error('invalid edit value')
      if (previous && automatic && previous.base === base) latest.current.restore(previous.value)
      else setSaved(previous)
    } catch {
      setWarning('浏览器无法读取编辑缓存；编辑仍可用，刷新恢复可能不可用。')
      // Preserve unreadable/older content until the user explicitly removes this key.
      setSaved({ base: 'unreadable-cache', value: { 提示: '原缓存无法解析，尚未覆盖。' } })
    }
    setReadyKey(key)
  }, [key, base, automatic])
  useEffect(() => {
    if (!key || readyKey !== key || base === undefined || saved) return
    try {
      if (dirty) writeEdit(window.sessionStorage, key, originalBase.current, value)
      else { window.sessionStorage.removeItem(key); originalBase.current = base }
    } catch { setWarning('浏览器无法保存编辑缓存；请在离开前处理编辑，刷新后可能丢失。') }
  }, [key, readyKey, base, encoded, dirty, saved])
  // Re-evaluate against fresh server data before offering restoration.
  const conflict = saved && saved.base !== base
  return {
    saved, warning, conflict,
    // Editors may wait for this before accepting input, so automatic restoration
    // cannot race the user's first keystroke after the server baseline loads.
    ready: !key || (base !== undefined && readyKey === key),
    restore() {
      if (!saved || conflict) return
      try {
        latest.current.restore(saved.value)
        originalBase.current = base
        setSaved(null)
      } catch { setWarning('这份缓存不适用于当前表单，已保留，未恢复。') }
    },
    discard() {
      try { window.sessionStorage.removeItem(key) } catch { setWarning('无法移除当前编辑缓存。') }
      originalBase.current = base
      setSaved(null)
    },
  }
}

export default function EditRecovery({ recovery, label = '编辑' }) {
  return <>{recovery.warning && <p className="recovery-note" role="status">{recovery.warning}</p>}
    {recovery.saved && <section className="recovery-note" aria-label={`${label}恢复`}>
      <p>{recovery.conflict ? '服务端资料已变化，本地内容保留供对照，不会覆盖当前表单。' : `发现本标签页的${label}。恢复只填入编辑器，不会自动提交；请核对后再保存。`}</p>
      <details><summary>查看本地内容</summary><pre>{JSON.stringify(recovery.saved.value, null, 2)}</pre></details>
      {!recovery.conflict && <button type="button" className="button secondary" onClick={recovery.restore}>恢复到编辑器</button>}
      <button type="button" className="button subtle" onClick={recovery.discard}>移除这份缓存</button>
    </section>}
  </>
}
