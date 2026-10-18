import test from 'node:test'
import assert from 'node:assert/strict'
import { goalPayload } from '../src/goals.js'

test('editing an API goal sends editable fields without response metadata', () => {
  const response = { id: 7, version: 3, created_at: '2026-10-12T10:00:00Z', updated_at: '2026-10-14T10:00:00Z', title: '课程交付', motivation: '英文答辩', goal_type: 'stage', priority: '1', metric_kind: 'deliverable', weekly_target: '2', unit_label: '项', due_date: '2026-10-25', status: 'paused' }
  assert.deepEqual(goalPayload(response), { title: '课程交付', motivation: '英文答辩', goal_type: 'stage', priority: 1, metric_kind: 'deliverable', weekly_target: 2, unit_label: '项', due_date: '2026-10-25', status: 'paused' })
  assert.equal(response.version, 3)
})

test('creating a goal retains defaults and allows clearing the optional date', () => {
  const form = { title: '学习目标', priority: '2', metric_kind: 'count', weekly_target: '1', unit_label: '次', due_date: '' }
  assert.deepEqual(goalPayload(form), { title: '学习目标', motivation: '', goal_type: 'long_term', priority: 2, metric_kind: 'count', weekly_target: 1, unit_label: '次', due_date: null, status: 'active' })
})
