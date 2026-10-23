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

for (const [code, guidance] of [
  ['PAST_PLANNING_WINDOW', /所选周已经结束/],
  ['PLAN_REQUIRES_ASSISTANT', /规划工作台.*保留原有记录/],
]) {
  test(`${code} gives Chinese recovery guidance and preserves the error code`, () => {
    const detail = { code, message: 'Server explanation' }
    const error = new ApiError(422, detail)
    assert.match(error.message, guidance)
    assert.equal(error.code, code)
    assert.deepEqual(error.detail, detail)
  })
}

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
test('documented business validation preserves a specific safe Chinese reason',()=>{
  assert.match(new ApiError(409,{code:'STALE_CANDIDATE',message:'这个时间已不可用，请刷新后重新选择。'}).message,/这个时间已不可用/)
  assert.match(new ApiError(422,'已有计时正在进行，请先结束计时。').message,/先结束计时/)
  assert.doesNotMatch(new ApiError(500,{code:'FUTURE_CODE',message:'Traceback: 私密异常'}).message,/Traceback/)
  assert.doesNotMatch(new ApiError(502,{code:'AI_RESPONSE_INVALID'}).message,/补充描述/)
})
