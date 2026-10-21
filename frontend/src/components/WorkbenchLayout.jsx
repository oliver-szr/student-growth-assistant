import { useEffect, useRef, useState } from 'react'

export default function WorkbenchLayout({ chat, children, view: controlledView, onViewChange, resultLabel = '结果', renderLayout, conversation }) {
  const [localView, setLocalView] = useState('chat')
  const [fits, setFits] = useState(false)
  const sidebar = useRef(null)
  const view = controlledView ?? localView
  const change = onViewChange ?? setLocalView
  useEffect(() => {
    if (renderLayout) return
    const measure = () => setFits(sidebar.current?.getBoundingClientRect().height <= window.innerHeight - 32)
    const observer = new ResizeObserver(measure)
    if (sidebar.current) observer.observe(sidebar.current)
    window.addEventListener('resize', measure)
    measure()
    return () => { observer.disconnect(); window.removeEventListener('resize', measure) }
  }, [Boolean(renderLayout)])
  if (renderLayout) return renderLayout({ chat, children, conversation })
  return <>
    <div className="workbench-switch" role="group" aria-label="切换工作台视图">
      <button type="button" aria-pressed={view === 'chat'} onClick={() => change('chat')}>聊天</button>
      <button type="button" aria-pressed={view === 'result'} onClick={() => change('result')}>{resultLabel}</button>
    </div>
    <div className="workbench-grid" data-view={view}>
      <div ref={sidebar} className={`workbench-chat-column ${fits ? 'can-stick' : ''}`}>{chat}</div>
      <div className="workbench-result-column">{children}</div>
    </div>
  </>
}
