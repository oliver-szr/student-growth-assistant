import React from 'react'

function inline(text, keyPrefix) {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>
    return <React.Fragment key={`${keyPrefix}-${index}`}>{part}</React.Fragment>
  })
}

/** Render only simple text, bold, and lists. Never interprets HTML or links. */
export default function SafeMessage({ text = '' }) {
  const blocks = []
  let paragraph = []
  let list = []
  let listKind = ''

  const flushParagraph = () => {
    if (paragraph.length) blocks.push(<p key={`p-${blocks.length}`}>{paragraph.map((line, i) => <React.Fragment key={i}>{i > 0 && <br />}{inline(line, `p-${i}`)}</React.Fragment>)}</p>)
    paragraph = []
  }
  const flushList = () => {
    if (!list.length) return
    const Tag = listKind === 'ordered' ? 'ol' : 'ul'
    blocks.push(<Tag key={`l-${blocks.length}`}>{list.map((line, i) => <li key={i}>{inline(line, `l-${i}`)}</li>)}</Tag>)
    list = []; listKind = ''
  }

  for (const line of String(text).split(/\r?\n/)) {
    const unordered = line.match(/^\s*[-•]\s+(.*)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (unordered || ordered) {
      flushParagraph()
      const kind = ordered ? 'ordered' : 'unordered'
      if (listKind && listKind !== kind) flushList()
      listKind = kind
      list.push((unordered || ordered)[1])
    } else {
      flushList()
      if (!line.trim()) flushParagraph()
      else paragraph.push(line)
    }
  }
  flushList(); flushParagraph()
  return <div className="safe-message">{blocks}</div>
}
