import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  LOCKED_STATE_LABEL, countWords, meetsStatementMinimum, shortTime,
} from './format.js'

test('a timestamp is rendered as UTC minutes with seconds dropped', () => {
  assert.equal(shortTime('2026-10-03T11:08:05.654365'), '2026-10-03 11:08Z')
})

test('a missing timestamp is an em dash, not null or undefined leaking out', () => {
  assert.equal(shortTime(null), '—')
  assert.equal(shortTime(undefined), '—')
  assert.equal(shortTime(''), '—')
})

test('the word count ignores leading and surrounding whitespace', () => {
  assert.equal(countWords('   a   statement   '), 2)
  assert.equal(countWords('  one two  three '), 3)
  assert.equal(countWords(''), 0)
  assert.equal(countWords('   '), 0)
  assert.equal(countWords(null), 0)
})

test('a statement is short of the gate until it reaches the minimum', () => {
  const minimum = 25
  const short = Array.from({ length: 24 }, (_, i) => `word${i}`).join(' ')
  const atLimit = Array.from({ length: minimum }, (_, i) => `word${i}`).join(' ')
  assert.equal(meetsStatementMinimum(short, minimum), false)
  assert.equal(meetsStatementMinimum(atLimit, minimum), true)
})

test('the gate defaults to the same 25 words the server enforces', () => {
  const short = Array.from({ length: 24 }, (_, i) => `word${i}`).join(' ')
  assert.equal(meetsStatementMinimum(short), false)
  assert.equal(meetsStatementMinimum(`${short} extra`), true)
})

test('the gate accepts a minimum given as a string, as query values arrive', () => {
  const statement = Array.from({ length: 30 }, (_, i) => `word${i}`).join(' ')
  assert.equal(meetsStatementMinimum(statement, '30'), true)
  assert.equal(meetsStatementMinimum(statement, '31'), false)
})

test('the locked states carry a human label for every state the API can report', () => {
  const reported = ['locked', 'pending', 'awaiting_bank', 'granted', 'rejected', 'expired']
  for (const state of reported) {
    assert.equal(typeof LOCKED_STATE_LABEL[state], 'string', `missing label: ${state}`)
    assert.ok(LOCKED_STATE_LABEL[state].length > 0)
  }
  assert.equal(LOCKED_STATE_LABEL.awaiting_bank, 'Awaiting the bank')
})
