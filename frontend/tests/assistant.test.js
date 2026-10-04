import test from 'node:test'
import assert from 'node:assert/strict'
import { calendarPosition, visibleSchedule, manualAction, focusCards } from '../src/assistant.js'
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
  const a=manualAction({target:'draft:abc',title:'报告',minutes:'60',deadline:'2026-10-09T20:00',priority:'high',task_type:'writing'})
  assert.equal(a.op,'update');assert.equal(a.target,'draft:abc')
  assert.equal(a.fields.deadline,'2026-10-09T20:00:00+08:00')
  assert.equal(a.fields.task_type,'writing')
})
test('date-specific courses retain date on editing instead of becoming weekly',()=>{
  const p=timeRuleFormPayload({kind:'course',title:'课',recurrence:'once',weekday:'',date:'2026-10-08',startTime:'14:00',endTime:'15:35'})
  assert.equal(p.recurrence,'once'); assert.equal(p.weekday,null); assert.equal(p.date,'2026-10-08')
})
test('cancelled future task is removed from candidate calendar before confirmation',()=>{
  assert.deepEqual(visibleSchedule([{ref:'task:1'}],{status:'ready',selected_refs:[],removed_refs:['task:1'],items:[]}),[])
})
test('focus cards preserve backend priority order, label urgency, and show at most three tasks',()=>{
  const items=['overdue','critical','urgent','at_risk'].map((urgency,index)=>({task_id:index+1,title:`任务${index+1}`,urgency,importance:index===0?'high':'normal',reason:'按截止时间与空档计算'}))
  assert.deepEqual(focusCards(items).map(({title,urgency_label,importance_label})=>({title,urgency_label,importance_label})),[
    {title:'任务1',urgency_label:'已逾期',importance_label:'高'},
    {title:'任务2',urgency_label:'很紧急',importance_label:'普通'},
    {title:'任务3',urgency_label:'近期截止',importance_label:'普通'},
  ])
  assert.equal(focusCards([{urgency:'scheduled'}])[0].urgency_label,'可安排')
  assert.deepEqual(focusCards([{urgency:'soon'},{urgency:'normal'}]).map(item=>item.urgency_label),['7天内截止','截止较远'])
})
