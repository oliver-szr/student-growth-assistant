import test from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, confirmPlan, createCandidatePlan, getConfirmedPlan, getPlan, getTasks, createTask, readableDetail } from '../src/api.js'

test('FastAPI validation messages include readable field paths', () => {
  assert.equal(readableDetail([
    { loc: ['body', 'duration_minutes'], msg: 'Value error, duration_minutes must be a multiple of 30' },
    { loc: ['body'], msg: 'Value error, once requires date and no weekday' },
  ]), 'duration_minutes: Value error, duration_minutes must be a multiple of 30; Value error, once requires date and no weekday')
  assert.equal(readableDetail('Task not found'), 'Task not found')
  assert.equal(readableDetail({}), '')
  assert.equal(readableDetail([null]), 'Invalid value')
})

test('API rejects a real 422 response shape and exposes a network error', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({
    detail: [{ loc: ['body', 'title'], msg: 'Value error, title must not be blank' }],
  }), { status: 422 }))
  await assert.rejects(createTask({ title: ' ' }), /title: Value error, title must not be blank/)
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await assert.rejects(getTasks(), /Could not connect to the backend/)
})

test('Plan endpoints preserve the existing backend paths, methods, and bodies', async (context) => {
  const calls = []
  context.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify({ id: 7 }), { status: 200 })
  })
  await createCandidatePlan({ week_start: '2026-10-05', task_ids: [1, 2] })
  await getPlan(7)
  await getConfirmedPlan('2026-10-05')
  await confirmPlan(7)
  assert.deepEqual(calls.map(({ url }) => new URL(url).pathname + new URL(url).search), [
    '/api/plans/candidates', '/api/plans/7', '/api/plans/confirmed?week_start=2026-10-05', '/api/plans/7/confirm',
  ])
  assert.deepEqual(JSON.parse(calls[0].options.body), { week_start: '2026-10-05', task_ids: [1, 2] })
  assert.equal(calls[0].options.method, 'POST')
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json')
  assert.equal(calls[3].options.method, 'POST')
  assert.equal(calls[3].options.body, undefined)
})

for (const [status, code] of [[404, 'PLAN_NOT_FOUND'], [409, 'STALE_CANDIDATE'], [409, 'PLAN_NOT_CANDIDATE'], [409, 'UNSCHEDULABLE'], [500, 'GENERATED_SCHEDULE_INVALID']]) {
  test(`Plan error retains ${status} ${code} and its structured detail`, async (context) => {
    const detail = { code, message: 'Server explanation', unscheduled_tasks: [{ task_id: 3, reason_code: 'NO_SLOT_FOUND', message: 'No continuous slot found.' }] }
    context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail }), { status }))
    await assert.rejects(getPlan(7), (error) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.status, status)
      assert.equal(error.code, code)
      assert.equal(error.message, 'Server explanation')
      assert.deepEqual(error.detail, detail)
      return true
    })
    assert.equal(readableDetail(detail), 'Server explanation')
  })
}

test('Request timeout rejects and the next request can recover', async (context) => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  context.mock.method(globalThis, 'fetch', (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const pending = getConfirmedPlan('2026-10-05')
  const rejection = assert.rejects(pending, /The request timed out/)
  context.mock.timers.tick(15000)
  await rejection
  globalThis.fetch = async () => new Response(JSON.stringify({ id: 4 }), { status: 200 })
  assert.deepEqual(await getConfirmedPlan('2026-10-05'), { id: 4 })
})

test('Unreadable backend response is a recoverable error', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response('not JSON', { status: 500 }))
  await assert.rejects(getPlan(7), /unreadable response/)
})
