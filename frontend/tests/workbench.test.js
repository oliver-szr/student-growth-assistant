import test from 'node:test'
import assert from 'node:assert/strict'
import { nearBottom, reviewMetrics, progressPercent } from '../src/workbench.js'
test('new messages must not displace a reader of history',()=>{assert.equal(nearBottom({scrollHeight:1000,clientHeight:400,scrollTop:100}),false);assert.equal(nearBottom({scrollHeight:1000,clientHeight:400,scrollTop:560}),true)})
test('missing facts stay unknown while confirmed zero remains zero',()=>{assert.deepEqual(reviewMetrics(null),[null,null,null]);assert.deepEqual(reviewMetrics({completed_count:0,confirmed_actual_minutes:90,planned_minutes:120}),[0,90,120])})
test('progress only renders from finite facts and keeps actual numbers separate',()=>{assert.equal(progressPercent(null,3),null);assert.equal(progressPercent(1,0),null);assert.equal(progressPercent(4,3),100);assert.equal(progressPercent(1,4),25)})
