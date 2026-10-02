import test from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, createTimeRule, parseConstraint } from '../src/api.js'
import { parsingNotice, proposalDay, proposalToFormRule, timeRuleFormPayload } from '../src/timeRules.js'

const weekly = { kind: 'protected', title: 'Lab', recurrence: 'weekly', weekday: 3, date: null, start_time: '14:07', end_time: '15:23' }
const once = { ...weekly, recurrence: 'once', weekday: null, date: '2026-10-09' }

for (const result of [
  { status: 'parsed', proposal: weekly },
  { status: 'needs_clarification', message: 'Specific start and end times are required.' },
  { status: 'unsupported', message: 'Outside scope.' },
]) {
  test(`parseConstraint sends text to backend and preserves ${result.status}`, async (context) => {
    let call
    context.mock.method(globalThis, 'fetch', async (url, options) => {
      call = { url, options }
      return new Response(JSON.stringify(result), { status: 200 })
    })
    assert.deepEqual(await parseConstraint('Description'), result)
    assert.equal(new URL(call.url).pathname, '/api/constraints/parse')
    assert.equal(call.options.method, 'POST')
    assert.equal(call.options.headers['Content-Type'], 'application/json')
    assert.deepEqual(JSON.parse(call.options.body), { text: 'Description' })
  })
}

for (const [status, code] of [[503, 'AI_NOT_CONFIGURED'], [503, 'AI_UNAVAILABLE'], [502, 'AI_RESPONSE_INVALID']]) {
  test(`AI failure preserves ${code}`, async (context) => {
    context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: { code, message: 'Safe message' } }), { status }))
    await assert.rejects(parseConstraint('Rule'), (error) => error instanceof ApiError && error.status === status && error.code === code)
  })
}

test('AI request has a 25s deadline, settles without auto retry, and supports manual retry', async (context) => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  let calls = 0
  let signal
  context.mock.method(globalThis, 'fetch', (_url, options) => new Promise((_resolve, reject) => {
    calls += 1
    signal = options.signal
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const pending = parseConstraint('Rule')
  const rejection = assert.rejects(pending, /request timed out/)
  context.mock.timers.tick(20000)
  assert.equal(signal.aborted, false)
  context.mock.timers.tick(5000)
  await rejection
  assert.equal(signal.aborted, true)
  assert.equal(calls, 1)
  globalThis.fetch = async () => new Response(JSON.stringify({ status: 'parsed', proposal: weekly }), { status: 200 })
  assert.deepEqual(await parseConstraint('Rule'), { status: 'parsed', proposal: weekly })
})

test('Weekly proposal maps to the existing form and Monday=1 through Sunday=7', () => {
  assert.deepEqual(proposalToFormRule({ ...weekly, active: false, id: 9 }), weekly)
  const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
  days.forEach((day, index) => assert.equal(proposalDay({ ...weekly, weekday: index + 1 }), day))
})

test('Once proposal retains the Shanghai calendar date without timezone conversion', () => {
  assert.deepEqual(proposalToFormRule(once), once)
  assert.equal(proposalDay(once), '2026-10-09')
})

test('Review edits are applied using the existing createTimeRule payload and endpoint', async (context) => {
  const draft = proposalToFormRule(weekly)
  const payload = timeRuleFormPayload({ ...draft, title: 'Reviewed lab', weekday: '3', startTime: '14:11', endTime: '15:23' }, draft)
  assert.deepEqual(payload, { ...weekly, title: 'Reviewed lab', start_time: '14:11' })
  let path
  context.mock.method(globalThis, 'fetch', async (url, options) => {
    path = new URL(url).pathname
    assert.deepEqual(JSON.parse(options.body), payload)
    return new Response(JSON.stringify({ ...payload, id: 1, active: true }), { status: 201 })
  })
  await createTimeRule(payload)
  assert.equal(path, '/api/time-rules')
  assert.equal('active' in payload, false)
})

test('Existing form clears hidden fields in either recurrence direction and preserves seconds when editing', () => {
  const fields = { kind: 'protected', title: 'Meeting', recurrence: 'once', weekday: '3', date: '2026-10-09', startTime: '15:00', endTime: '17:00' }
  assert.equal(timeRuleFormPayload(fields).weekday, null)
  assert.equal(timeRuleFormPayload({ ...fields, recurrence: 'weekly' }).date, null)
  const original = { start_time: '15:00:30', end_time: '17:00:45' }
  assert.equal(timeRuleFormPayload(fields, original).start_time, '15:00:30')
  assert.equal(timeRuleFormPayload(fields, original).end_time, '17:00:45')
})

test('Clarification and unsupported have notices; parsed has no notice', () => {
  assert.deepEqual(parsingNotice({ status: 'needs_clarification', message: 'Give times.' }), { heading: 'More information needed', message: 'Give times.' })
  assert.equal(parsingNotice({ status: 'unsupported', message: 'Ignore' }).heading, 'Unsupported request')
  assert.equal(parsingNotice({ status: 'parsed', proposal: weekly }), null)
})
