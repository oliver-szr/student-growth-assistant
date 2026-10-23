import test from 'node:test'
import assert from 'node:assert/strict'
import { changeCounts, changeSummary } from '../src/uiCopy.js'
test('split segments count one task and distinct kinds are truthful',()=>{
 assert.deepEqual(changeCounts([{ref:'task:1',kind:'added'},{ref:'task:1',kind:'added'},{ref:'task:2',kind:'moved'},{ref:'task:3',kind:'removed'}]),{added:1,moved:1,removed:1})
 assert.equal(changeSummary([]),'保留现有安排')
 assert.equal(changeSummary([{ref:'task:1',kind:'added'}]),'新增安排 1 项')
})
