import { shanghaiTime } from './assistant.js'
export const shiftDate=(date,days)=>new Date(Date.parse(date+'T00:00:00Z')+days*86400000).toISOString().slice(0,10)
export function reviewRange(date,period){
  if(period==='day')return [date,shiftDate(date,1)]
  const day=new Date(date+'T00:00:00Z')
  if(period==='week'){const start=shiftDate(date,-((day.getUTCDay()+6)%7));return [start,shiftDate(start,7)]}
  const first=date.slice(0,7)+'-01';day.setUTCMonth(day.getUTCMonth()+1,1)
  return [first,day.toISOString().slice(0,10)]
}
// Render Shanghai wall time as UTC, avoiding FullCalendar named-zone coercion
// and browser local-zone dependence. API instants and event IDs stay unchanged.
export function calendarEvent(event){
  return {...event,start:event.allDay?event.start:shanghaiTime(event.start)+':00Z',
    end:event.end?shanghaiTime(event.end)+':00Z':undefined,extendedProps:event,
    classNames:['calendar-'+event.kind],editable:false}
}
