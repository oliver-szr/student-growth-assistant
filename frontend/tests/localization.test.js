import test from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, createTask, explainCandidate } from '../src/api.js'

test('stale candidate shows Chinese recovery guidance without losing machine-readable detail', () => {
  const detail = { code: 'STALE_CANDIDATE', message: 'Server explanation', task_ids: [3] }
  const error = new ApiError(409, detail)
  assert.match(error.message, /已过期/)
  assert.match(error.message, /重新生成/)
  assert.equal(error.code, 'STALE_CANDIDATE')
  assert.equal(error.status, 409)
  assert.deepEqual(error.detail, detail)
})

test('blank title validation identifies the field and correction in Chinese', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({
    detail: [{ loc: ['body', 'title'], type: 'value_error', msg: 'Value error, title must not be blank' }],
  }), { status: 422 }))
  await assert.rejects(createTask({ title: ' ' }), /标题.*不能为空/)
})

test('Chinese interface requests Chinese explanations by default', async (context) => {
  let sent
  context.mock.method(globalThis, 'fetch', async (_url, options) => {
    sent = JSON.parse(options.body)
    return new Response(JSON.stringify({ explanation_status: 'unavailable' }))
  })
  await explainCandidate(2)
  assert.deepEqual(sent, { language: 'zh-CN' })
})

test('unknown provider or server prose stays out of user-facing errors', () => {
  const detail = { code: 'FUTURE_CODE', message: 'Unexpected internal server text' }
  const error = new ApiError(500, detail)
  assert.match(error.message, /服务/)
  assert.doesNotMatch(error.message, /Unexpected/)
  assert.deepEqual(error.detail, detail)
})
