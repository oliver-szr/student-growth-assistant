import { useLayoutEffect, useRef, useState } from 'react'
import { nearBottom } from '../workbench.js'

export default function ChatMessages({ children, revision, className = '',storageKey }) {
  const scroll = useRef(null)
  const follow = useRef(true)
  const [unread, setUnread] = useState(false)
  const initialized=useRef(false),previous=useRef(null)
  const anchor=useRef(null)
  function position(el){
    const top=el.getBoundingClientRect().top
    const item=[...el.querySelectorAll('article[id]')].find(row=>row.getBoundingClientRect().bottom>top)
    return item?{id:item.id,offset:item.getBoundingClientRect().top-top}:null
  }
  function align(el,saved){
    const item=saved&&document.getElementById(saved.id)
    if(!item||!el.contains(item))return false
    el.scrollTop+=item.getBoundingClientRect().top-el.getBoundingClientRect().top-saved.offset
    return true
  }
  function bottom() {
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight
    follow.current = true
    setUnread(false)
  }
  useLayoutEffect(() => {
    const el=scroll.current;if(!el)return
    const first=el.querySelector('article[id]')?.id
    if(!initialized.current&&first){
      initialized.current=true
      try{const saved=storageKey&&JSON.parse(sessionStorage.getItem(storageKey));if(saved&&Number.isFinite(saved.top)){if(!align(el,saved.anchor))el.scrollTop=saved.top;follow.current=nearBottom(el)}}catch{/* editing recovery separately reports unavailable storage */}
    }
    const old=previous.current
    if(old?.first&&old.first!==first&&!follow.current&&Number(first?.split('-').at(-1))<Number(old.first.split('-').at(-1))){if(!align(el,anchor.current))el.scrollTop+=Math.max(0,el.scrollHeight-old.height)}
    else if(follow.current)bottom()
    else setUnread(true)
    previous.current={first,height:el.scrollHeight}
    anchor.current=position(el)
  }, [revision])
  return <div className="chat-history">
    <div ref={scroll} className={`chat-scroll ${className}`} aria-live="polite" onScroll={() => {
      follow.current = nearBottom(scroll.current)
      anchor.current=position(scroll.current)
      if (follow.current) setUnread(false)
      if(storageKey&&initialized.current)try{sessionStorage.setItem(storageKey,JSON.stringify({top:scroll.current.scrollTop,anchor:anchor.current,first_id:Number(anchor.current?.id.split('-').at(-1))||null}))}catch{/* optional scroll preference */}
    }}>{children}</div>
    {unread && <button className="button subtle new-reply" type="button" onClick={bottom}>有新回复</button>}
  </div>
}
