import test from 'node:test'
import assert from 'node:assert/strict'
import { explainCandidate } from '../src/api.js'
import { createExplanationSession, diffGroups } from '../src/explanations.js'

const plan = { id: 2, based_on_plan_id: 1, status: 'candidate' }
const task = { task_id: 3, title: 'Read paper', start_at: '2026-10-05T00:00:00Z', end_at: '2026-10-05T01:00:00Z' }
const result = { diff: { added: [task], removed: [task], unchanged: [task], moved: [{ ...task, from_start: task.start_at, from_end: task.end_at, to_start: '2026-10-05T02:00:00Z', to_end: '2026-10-05T03:00:00Z' }] }, explanation: null, explanation_status: 'unavailable' }

test('Explanation wrapper posts language and retains unavailable diff', async (context) => {
  context.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(new URL(url).pathname, '/api/plans/2/explanation')
    assert.equal(options.method, 'POST')
    assert.deepEqual(JSON.parse(options.body), { language: 'zh-CN' })
    return new Response(JSON.stringify(result))
  })
  assert.deepEqual(await explainCandidate(2, 'zh-CN'), result)
})

test('Explanation wrapper waits for backend 20-second deadline and stops at 25 seconds', async (context) => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  let aborted = false
  context.mock.method(globalThis, 'fetch', (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => { aborted = true; reject(new DOMException('Aborted', 'AbortError')) })
  }))
  const rejection = assert.rejects(explainCandidate(2), /timed out/)
  context.mock.timers.tick(20000)
  assert.equal(aborted, false)
  context.mock.timers.tick(5000)
  await rejection
})

test('Diff mapping preserves four categories, IDs, snapshot titles and Shanghai times', () => {
  const groups = diffGroups(result.diff)
  assert.deepEqual(groups.map((group) => group.key), ['added', 'moved', 'removed', 'unchanged'])
  assert.equal(groups[2].label, 'Not included in candidate')
  assert.equal(groups[0].items[0].title, 'Read paper')
  assert.equal(groups[0].items[0].task_id, 3)
  assert.equal(groups[0].items[0].description, '2026-10-05 08:00 → 2026-10-05 09:00')
  assert.match(groups[1].items[0].description, /From .*08:00.* to .*10:00/)
})

test('First candidate and non-candidate never request AI', async () => {
  const request = () => { throw new Error('must not call') }
  for (const candidate of [{ ...plan, based_on_plan_id: null }, { ...plan, status: 'confirmed' }]) {
    await createExplanationSession(candidate, request, () => assert.fail()).start()
  }
})

test('Only explicit start requests explanation; duplicate clicks are ignored; unavailable keeps diff', async () => {
  let calls = 0, resolve
  const states = []
  const session = createExplanationSession(plan, () => { calls++; return new Promise((done) => { resolve = done }) }, (state) => states.push(state))
  assert.equal(calls, 0)
  const pending = session.start()
  await session.start()
  assert.equal(calls, 1)
  assert.equal(states.at(-1).pending, true)
  resolve(result)
  await pending
  assert.equal(states.at(-1).pending, false)
  assert.deepEqual(states.at(-1).result.diff, result.diff)
})

test('Candidate replacement/unmount ignores late responses and new session starts empty', async () => {
  let resolve
  const oldStates = [], newStates = []
  const oldSession = createExplanationSession(plan, () => new Promise((done) => { resolve = done }), (state) => oldStates.push(state))
  const pending = oldSession.start()
  oldSession.close()
  const next = createExplanationSession({ ...plan, id: 4 }, async (id) => { assert.equal(id, 4); return result }, (state) => newStates.push(state))
  resolve(result)
  await pending
  assert.equal(oldStates.length, 1)
  assert.equal(newStates.length, 0)
  await next.start()
  assert.equal(newStates[0].result, null)
})

test('Transport failure keeps previous deterministic diff and allows explicit retry', async () => {
  let calls = 0
  const states = []
  const session = createExplanationSession(plan, async () => {
    if (++calls === 2) throw new Error('Network unavailable')
    return result
  }, (state) => states.push(state))
  await session.start()
  await session.start()
  assert.deepEqual(states.at(-1).result, result)
  assert.equal(states.at(-1).error, 'Network unavailable')
  assert.equal(states.at(-1).pending, false)
  await session.start()
  assert.equal(states.at(-1).error, '')
})

test('Disposed session ignores a late rejection and cannot start another request', async () => {
  let reject, calls = 0
  const states = []
  const session = createExplanationSession(plan, () => {
    calls++
    return new Promise((_resolve, fail) => { reject = fail })
  }, (state) => states.push(state))
  const pending = session.start()
  session.close()
  reject(new Error('Late error for old candidate'))
  await pending
  await session.start()
  assert.equal(states.length, 1)
  assert.equal(calls, 1)
})
