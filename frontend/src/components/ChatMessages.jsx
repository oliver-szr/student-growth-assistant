import { useEffect, useRef, useState } from 'react'
import { nearBottom } from '../workbench.js'

export default function ChatMessages({ children, revision, className = '' }) {
  const scroll = useRef(null)
  const follow = useRef(true)
  const [unread, setUnread] = useState(false)
  function bottom() {
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight
    follow.current = true
    setUnread(false)
  }
  useEffect(() => {
    if (follow.current) bottom()
    else setUnread(true)
  }, [revision])
  return <div className="chat-history">
    <div ref={scroll} className={`chat-scroll ${className}`} aria-live="polite" onScroll={() => {
      follow.current = nearBottom(scroll.current)
      if (follow.current) setUnread(false)
    }}>{children}</div>
    {unread && <button className="button subtle new-reply" type="button" onClick={bottom}>有新回复</button>}
  </div>
}
