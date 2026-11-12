import assert from 'node:assert/strict'
import test from 'node:test'
import { looksLikeEmail, matchesSearch } from './search.js'

test('an empty search matches everything', () => {
  assert.equal(matchesSearch('', 'CS101'), true)
  assert.equal(matchesSearch('   ', 'CS101'), true)
  assert.equal(matchesSearch(undefined, 'CS101'), true)
})

test('search is case-insensitive and every word must match some value', () => {
  assert.equal(matchesSearch('cs1', 'CS101', 'Intro'), true)
  assert.equal(matchesSearch('intro cs', 'CS101', 'Intro to Programming'), true)
  assert.equal(matchesSearch('intro math', 'CS101', 'Intro to Programming'), false)
  assert.equal(matchesSearch('apu2', 'CS101', null, 'APU1 · APU2'), true)
})

test('email shape check', () => {
  assert.equal(looksLikeEmail('a.b@example.com'), true)
  assert.equal(looksLikeEmail(' a@b.co '), true)
  assert.equal(looksLikeEmail('no-at-sign.com'), false)
  assert.equal(looksLikeEmail('a@b'), false)
  assert.equal(looksLikeEmail('a b@c.com'), false)
})
