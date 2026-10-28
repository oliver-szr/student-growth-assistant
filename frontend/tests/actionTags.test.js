import test from 'node:test'
import assert from 'node:assert/strict'
import { selectedActionTag, toggleActionTag } from '../src/actionTags.js'

test('action tags append to the message, toggle off and switch without deleting user text', () => {
  const text='我明天要写云计算ppt'
  const draft=toggleActionTag(text,'生成草案')
  assert.equal(draft,`${text} #生成草案`)
  assert.equal(selectedActionTag(draft),'生成草案')
  assert.equal(toggleActionTag(draft,'生成草案'),text)
  assert.equal(toggleActionTag(draft,'复盘'),`${text} #复盘`)
  assert.equal(toggleActionTag('','生成草案'),'#生成草案')
  assert.equal(toggleActionTag(text,'不存在'),text)
  assert.equal(toggleActionTag(`${text} ＃日程`,'查看日程'),text)
})

test('quoted tags and tags inside code are content, not the selected operation', () => {
  for(const text of ['“#生成草案”','说明 `#复盘`','```\n#查看日程\n```','解释 #复盘 的含义']) {
    assert.equal(selectedActionTag(text),null)
    assert.equal(toggleActionTag(text,'生成草案'),`${text} #生成草案`)
  }
})
