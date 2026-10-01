import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { currentShanghaiMonday, displayDeadline, mondayOfDate } from '../src/datetime.js'
import { groupPlanItems, planTimeRange, sameTaskSelection } from '../src/planning.js'

for (const [selected, candidate, expected] of [
  [[1, 2], [1, 2], true],
  [[1, 2], [2, 1], true],
  [[1, 2], [1, 2, 3], false],
  [[1, 2], [1, 3], false],
  [[], [], true],
]) {
  test(`Task selection ${JSON.stringify(selected)} compared with ${JSON.stringify(candidate)} is ${expected}`, () => {
    assert.equal(sameTaskSelection(selected, candidate), expected)
  })
}

test('Task selection comparison does not mutate either input array', () => {
  const selected = Object.freeze([2, 1])
  const candidate = Object.freeze([1, 2])
  assert.equal(sameTaskSelection(selected, candidate), true)
  assert.deepEqual(selected, [2, 1])
  assert.deepEqual(candidate, [1, 2])
})

test('Candidate selection mismatch clears when the original task set is restored', () => {
  const candidatePlan = { task_ids: [1, 2] }
  assert.equal(!sameTaskSelection([1, 2, 3], candidatePlan.task_ids), true)
  assert.equal(!sameTaskSelection([2, 1], candidatePlan.task_ids), false)
})

test('Week dates normalize to Monday across month, year, and leap-day boundaries', () => {
  for (const [date, expected] of [
    ['2026-10-05', '2026-10-05'], ['2026-10-08', '2026-10-05'], ['2026-10-11', '2026-10-05'],
    ['2026-10-01', '2026-09-28'], ['2027-01-01', '2026-12-28'], ['2028-02-29', '2028-02-28'],
    ['0001-01-01', '0001-01-01'],
  ]) assert.equal(mondayOfDate(date), expected)
})

test('Invalid calendar dates cannot become a week_start', () => {
  for (const date of ['', 'invalid', '2026-02-29', '2026-13-01', '2026-04-31', '0000-01-01']) {
    assert.throws(() => mondayOfDate(date), /Choose a valid week date/)
  }
})

test('Default week changes at Shanghai Monday midnight, independent of UTC date', () => {
  assert.equal(currentShanghaiMonday(new Date('2026-10-04T15:59:59Z')), '2026-09-28')
  assert.equal(currentShanghaiMonday(new Date('2026-10-04T16:00:00Z')), '2026-10-05')
})

test('Plan grouping uses Shanghai date and preserves API item order and snapshots', () => {
  const items = [
    { id: 9, kind: 'course', title_snapshot: 'Course snapshot', start_at: '2026-10-05T00:00:00Z', end_at: '2026-10-05T01:15:00Z' },
    { id: 4, kind: 'task', title_snapshot: 'Task snapshot', start_at: '2026-10-05T02:00:00Z', end_at: '2026-10-05T03:30:00Z' },
    { id: 2, kind: 'course', title_snapshot: 'Early course', start_at: '2026-10-05T17:00:00Z', end_at: '2026-10-05T18:00:00Z' },
  ]
  const before = structuredClone(items)
  const groups = groupPlanItems(items)
  assert.deepEqual(groups.map((group) => group.date), ['2026-10-05', '2026-10-06'])
  assert.deepEqual(groups[0].items.map((item) => item.id), [9, 4])
  assert.equal(groups[1].items[0].title_snapshot, 'Early course')
  assert.equal(planTimeRange(items[0]), '08:00–09:15')
  assert.equal(planTimeRange(items[1]), '10:00–11:30')
  assert.equal(planTimeRange(items[2]), '01:00–02:00')
  assert.equal(displayDeadline(items[1].start_at), '2026-10-05 10:00')
  assert.deepEqual(items, before)
  assert.deepEqual(groupPlanItems([]), [])
})

test('Week and plan display agree in browsers with different local timezones', () => {
  const datetimeUrl = new URL('../src/datetime.js', import.meta.url).href
  const planningUrl = new URL('../src/planning.js', import.meta.url).href
  const script = `
    import { currentShanghaiMonday, mondayOfDate } from ${JSON.stringify(datetimeUrl)};
    import { groupPlanItems, planTimeRange } from ${JSON.stringify(planningUrl)};
    const item = { id: 1, start_at: '2026-10-05T17:00:00Z', end_at: '2026-10-05T18:00:00Z' };
    console.log(JSON.stringify([mondayOfDate('2026-10-08'), currentShanghaiMonday(new Date('2026-10-04T16:00:00Z')), groupPlanItems([item])[0].date, planTimeRange(item)]));
  `
  for (const timezone of ['UTC', 'America/Los_Angeles', 'Pacific/Kiritimati']) {
    const result = execFileSync(process.execPath, ['--input-type=module', '-e', script], { env: { ...process.env, TZ: timezone }, encoding: 'utf8' })
    assert.deepEqual(JSON.parse(result), ['2026-10-05', '2026-10-05', '2026-10-06', '01:00–02:00'])
  }
})
