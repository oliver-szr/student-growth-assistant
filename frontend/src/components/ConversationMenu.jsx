import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export function menuPosition(anchor, size, viewport) {
  const width = Math.min(size.width, Math.max(0, viewport.width - 16))
  const height = Math.min(size.height, Math.max(0, viewport.height - 16))
  const below = anchor.bottom + 6
  return {
    left: Math.max(8, Math.min(anchor.right - width, viewport.width - width - 8)),
    top: Math.max(8, Math.min(below + height <= viewport.height - 8 ? below : anchor.top - height - 6, viewport.height - height - 8)),
    maxHeight: Math.max(0, viewport.height - 16),
  }
}

export function ConversationRow({ row, selected, expanded, disabled, onOpen, onMenu }) {
  return <article className="conversation-row" data-conversation-id={row.id} data-selected={selected || undefined}>
    <button type="button" className="conversation-title" title={row.title} aria-current={selected ? 'true' : undefined} onClick={onOpen}>{row.title}</button>
    <button type="button" id={`conversation-more-${row.id}`} className="conversation-more" aria-label={`会话“${row.title}”的更多操作`} aria-haspopup="menu" aria-expanded={expanded} aria-controls={expanded ? 'conversation-menu' : undefined} disabled={disabled}
      onClick={event => { event.stopPropagation(); onMenu(event.currentTarget) }}
      onKeyDown={event => { if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); onMenu(event.currentTarget, event.key === 'ArrowUp') } }}>···</button>
  </article>
}

// One portal for the whole list; never clipped by the sidebar's scroll box.
export default function ConversationMenu({ anchor, items, last = false, onClose }) {
  const menu = useRef(null), close = useRef(onClose)
  close.current = onClose
  const [position, setPosition] = useState(null)
  useLayoutEffect(() => {
    const element = menu.current
    setPosition(menuPosition(anchor.getBoundingClientRect(), element.getBoundingClientRect(), { width: innerWidth, height: innerHeight }))
    const buttons = element.querySelectorAll('button:not(:disabled)')
    buttons[last ? buttons.length - 1 : 0]?.focus({ preventScroll: true })
  }, [anchor, last])
  useEffect(() => {
    const outside = event => { if (!menu.current?.contains(event.target) && !anchor.contains(event.target)) close.current(false) }
    const escape = event => { if (event.key === 'Escape') { event.preventDefault(); close.current(true) } }
    const scroll = event => { if (!menu.current?.contains(event.target)) close.current(true) }
    const resize = () => close.current(true)
    document.addEventListener('pointerdown', outside, true)
    document.addEventListener('focusin', outside)
    document.addEventListener('keydown', escape)
    window.addEventListener('scroll', scroll, true)
    window.addEventListener('resize', resize)
    window.visualViewport?.addEventListener('resize', resize)
    return () => {
      document.removeEventListener('pointerdown', outside, true)
      document.removeEventListener('focusin', outside)
      document.removeEventListener('keydown', escape)
      window.removeEventListener('scroll', scroll, true)
      window.removeEventListener('resize', resize)
      window.visualViewport?.removeEventListener('resize', resize)
    }
  }, [anchor])
  function keyDown(event) {
    const buttons = [...menu.current.querySelectorAll('button:not(:disabled)')]
    const index = buttons.indexOf(document.activeElement)
    const next = event.key === 'ArrowDown' ? (index + 1) % buttons.length : event.key === 'ArrowUp' ? (index - 1 + buttons.length) % buttons.length
      : event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : null
    if (next !== null) { event.preventDefault(); buttons[next]?.focus(); return }
    if (event.key === 'Tab') {
      event.preventDefault()
      const focusable = [...document.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]')]
        .filter(element => !element.closest('[hidden],[inert],.conversation-menu') && element.getClientRects().length)
      const target = focusable[focusable.indexOf(anchor) + (event.shiftKey ? -1 : 1)]
      close.current(true)
      target?.focus({ preventScroll: true })
    }
  }
  return createPortal(<div ref={menu} id="conversation-menu" role="menu" aria-label="会话操作菜单" className="conversation-menu" style={position || { left: 0, top: 0, opacity: 0 }} onKeyDown={keyDown}>
    {items.map(item => <button key={item.key} type="button" role="menuitem" tabIndex={-1} className={item.danger ? 'danger' : item.match ? 'conversation-match' : undefined} disabled={item.disabled}
      onClick={() => { close.current(true); item.select() }}>{item.label}</button>)}
  </div>, document.body)
}
