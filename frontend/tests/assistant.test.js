import test from 'node:test'
import assert from 'node:assert/strict'
import { calendarPosition, visibleSchedule, manualAction } from '../src/assistant.js'
import { timeRuleFormPayload } from '../src/timeRules.js'

test('Shanghai calendar positions are independent of browser timezone',()=>{
  assert.deepEqual(calendarPosition({start_at:'2026-10-08T06:00:00Z',end_at:'2026-10-08T07:35:00Z'}),{date:'2026-10-08',top:360,height:95})
})
test('candidate replaces only active task blocks and preserves courses and past items',()=>{
  const confirmed=[{ref:'task:1',start_at:'old'},{ref:'task:2',start_at:'past'}]
  const p={status:'ready',selected_refs:['task:1'],items:[{ref:'task:1',start_at:'new'}]}
  assert.deepEqual(visibleSchedule(confirmed,p),[{ref:'task:2',start_at:'past'},{ref:'task:1',start_at:'new',candidate:true}])
  assert.deepEqual(visibleSchedule(confirmed,{...p,status:'discarded'}),confirmed)
})
test('manual edit targets draft without another add and uses explicit Shanghai deadline',()=>{
  const a=manualAction({target:'draft:abc',title:'报告',minutes:'60',deadline:'2026-10-09T20:00',priority:'high'})
  assert.equal(a.op,'update');assert.equal(a.target,'draft:abc')
  assert.equal(a.fields.deadline,'2026-10-09T20:00:00+08:00')
})
test('date-specific courses retain date on editing instead of becoming weekly',()=>{
  const p=timeRuleFormPayload({kind:'course',title:'课',recurrence:'once',weekday:'',date:'2026-10-08',startTime:'14:00',endTime:'15:35'})
  assert.equal(p.recurrence,'once'); assert.equal(p.weekday,null); assert.equal(p.date,'2026-10-08')
})
test('cancelled future task is removed from candidate calendar before confirmation',()=>{
  assert.deepEqual(visibleSchedule([{ref:'task:1'}],{status:'ready',selected_refs:[],removed_refs:['task:1'],items:[]}),[])
})
