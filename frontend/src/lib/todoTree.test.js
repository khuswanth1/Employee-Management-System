import { describe, expect, it } from 'vitest'
import { applyMove, dropIndex, fmtMinutes, splitMinutes, toMinutes } from './todoTree'

const task = (id, subs = [], extra = {}) => ({ id, title: `t${id}`, status: 'todo', duration_minutes: 10, parent_id: null, subtasks: subs.map((s) => ({ ...s, parent_id: id })), ...extra })
const sub = (id, extra = {}) => ({ id, title: `s${id}`, status: 'todo', duration_minutes: 5, ...extra })
const ids = (items) => items.map((t) => t.id)

describe('durations', () => {
  it('formats minutes', () => {
    expect(fmtMinutes(0)).toBe('—'); expect(fmtMinutes(null)).toBe('—')
    expect(fmtMinutes(45)).toBe('45m'); expect(fmtMinutes(120)).toBe('2h'); expect(fmtMinutes(95)).toBe('1h 35m')
  })
  it('converts hour/minute fields', () => {
    expect(toMinutes('', '')).toBeNull(); expect(toMinutes('1', '30')).toBe(90); expect(toMinutes('', '45')).toBe(45); expect(toMinutes('2', '')).toBe(120)
    expect(splitMinutes(95)).toEqual({ h: '1', m: '35' }); expect(splitMinutes(null)).toEqual({ h: '', m: '' })
  })
})

describe('applyMove', () => {
  const base = () => [task(1, [sub(11), sub(12)]), task(2), task(3)]
  it('reorders main tasks', () => {
    expect(ids(applyMove(base(), 3, null, 0))).toEqual([3, 1, 2])
    expect(ids(applyMove(base(), 1, null, 99))).toEqual([2, 3, 1])
  })
  it('reorders subtasks inside a task', () => {
    const r = applyMove(base(), 12, 1, 0)
    expect(ids(r[0].subtasks)).toEqual([12, 11]); expect(r[0].subtasks.map((s) => s.position)).toEqual([0, 1])
  })
  it('moves a subtask to another task and recomputes the times', () => {
    const r = applyMove(base(), 11, 2, 0)
    expect(ids(r.find((t) => t.id === 2).subtasks)).toEqual([11]); expect(r.find((t) => t.id === 2).subtasks[0].parent_id).toBe(2)
    expect(r.find((t) => t.id === 1).total_minutes).toBe(15); expect(r.find((t) => t.id === 2).total_minutes).toBe(15)
  })
  it('promotes a subtask and nests a plain task', () => {
    expect(ids(applyMove(base(), 11, null, 1))).toEqual([1, 11, 2, 3])
    const r = applyMove(base(), 3, 2, 0)
    expect(ids(r)).toEqual([1, 2]); expect(ids(r[1].subtasks)).toEqual([3])
  })
  it('refuses to nest a task that has subtasks, or into itself', () => {
    const b = base()
    expect(applyMove(b, 1, 2, 0)).toBe(b); expect(applyMove(b, 2, 2, 0)).toBe(b); expect(applyMove(b, 999, null, 0)).toBe(b)
  })
})

describe('dropIndex', () => {
  const list = [{ id: 1 }, { id: 2 }, { id: 3 }]
  it('places before/after the target, ignoring the dragged item', () => {
    expect(dropIndex(list, 1, 3, false)).toBe(1) // [2, 1, 3]
    expect(dropIndex(list, 1, 3, true)).toBe(2)  // [2, 3, 1]
    expect(dropIndex(list, 3, 1, false)).toBe(0)
    expect(dropIndex(list, 9, 2, true)).toBe(2)
  })
})
