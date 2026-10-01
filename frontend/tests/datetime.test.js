import test from 'node:test'
import assert from 'node:assert/strict'
import { toBackendDeadline, toDatetimeLocalValue } from '../src/datetime.js'

test('Shanghai datetime-local round trip through a UTC API response', () => {
  assert.equal(toBackendDeadline('2026-10-05T22:00'), '2026-10-05T22:00:00+08:00')
  assert.equal(toDatetimeLocalValue('2026-10-05T14:00:00Z'), '2026-10-05T22:00')
})

test('UTC response crosses midnight in Shanghai without using local timezone', () => {
  assert.equal(toDatetimeLocalValue('2026-10-05T17:30:00+00:00'), '2026-10-06T01:30')
})

test('offset-aware responses are converted and naive or invalid values are rejected', () => {
  assert.equal(toDatetimeLocalValue('2026-10-05T22:00:00+08:00'), '2026-10-05T22:00')
  assert.equal(toDatetimeLocalValue('2026-10-05T07:00:00-07:00'), '2026-10-05T22:00')
  assert.equal(toDatetimeLocalValue('2026-10-05T14:00:00'), '')
  assert.equal(toDatetimeLocalValue('invalid'), '')
  assert.equal(toDatetimeLocalValue(null), '')
  assert.throws(() => toBackendDeadline(''), /Choose a deadline/)
})

test('editing other fields preserves the precise deadline; changing it sends Shanghai minutes', () => {
  const original = '2026-10-05T14:00:45.123456Z'
  assert.equal(toBackendDeadline('2026-10-05T22:00', original), original)
  assert.equal(toBackendDeadline('2026-10-05T22:30', original), '2026-10-05T22:30:00+08:00')
})
