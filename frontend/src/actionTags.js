export const actionTags = [
  { label: '生成草案', description: '先生成可编辑草案，缺失信息使用默认值' },
  { label: '查看日程', description: '查询已保存的日程' },
  { label: '复盘', description: '生成可编辑复盘' },
]

const tagSuffix = /(?:^|\s)[#＃](生成草案|查看日程|日程|复盘)\s*$/u
export function selectedActionTag(text) {
  const active = text.replace(/```[\s\S]*?```|`[^`]*`|“[^”]*”|「[^」]*」|‘[^’]*’|"[^"\n]*"/gu, '').trim()
  const label = active.match(tagSuffix)?.[1]
  return label === '日程' ? '查看日程' : label || null
}

export function toggleActionTag(text, label) {
  if (!actionTags.some(tag => tag.label === label)) return text
  const selected = selectedActionTag(text)
  const base = selected ? text.replace(tagSuffix, '').trimEnd() : text.trimEnd()
  return selected === label ? base : `${base}${base ? ' ' : ''}#${label}`
}
