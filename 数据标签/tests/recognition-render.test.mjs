import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { loadSource } from './load-source.mjs'

const { RecognitionResult } = await loadSource('src/components/recognition/RecognitionResult.tsx')
const { HerbLatinNames, IdentityWarning } = await loadSource('src/components/herb/HerbIdentity.tsx')
const renderResult = result => renderToStaticMarkup(createElement(MemoryRouter, null,
  createElement(RecognitionResult, { result })))

test('a conflicting top prediction and conflicting Top 5 candidate are visibly marked', () => {
  const prediction = {herb_id: 'tcmp-051', name: '冲突条目', latin_name: 'Original species', confidence: .8,
    identity_conflict: true, identity_status: '身份存在冲突', review_status: '未人工审核',
    original_latin_name: 'Original species', accepted_latin_name: 'Accepted species'}
  const markup = renderResult({prediction, top_k: [prediction]})
  assert.match(markup, /植物身份存在冲突/)
  assert.match(markup, /身份冲突 · 待核实/)
  assert.match(markup, /原始学名：Original species/)
  assert.match(markup, /图鉴规范学名：Accepted species/)
  assert.match(markup, /未人工审核/)
  assert.match(markup, /模型候选 · 待核实/)
  assert.doesNotMatch(markup, /身份已确认/)
})

test('legacy mock predictions still render as candidates when identity metadata is absent', () => {
  const prediction = {herb_id: 'h001', name: '金银花', latin_name: 'Lonicera japonica', confidence: .928}
  const markup = renderResult({prediction, top_k: [prediction]})
  assert.match(markup, /金银花/)
  assert.match(markup, /92.80%/)
  assert.match(markup, /候选 · 待核实/)
  assert.doesNotMatch(markup, /植物身份存在冲突/)
})

test('a missing accepted Latin name never promotes the original name to a normalized name', () => {
  for (const acceptedLatinName of [undefined, '', ' ']) {
    const markup = renderToStaticMarkup(createElement('dl', null, createElement(HerbLatinNames,
      {herb: {latinName: 'Legacy or conflicting name', originalLatinName: 'Original species', acceptedLatinName}})))
    assert.match(markup, /<dt>规范学名<\/dt><dd>暂无可靠资料<\/dd>/)
    assert.doesNotMatch(markup, /Legacy or conflicting name/)
  }
  const verified = renderToStaticMarkup(createElement('dl', null, createElement(HerbLatinNames,
    {herb: {originalLatinName: 'Original species', acceptedLatinName: 'Accepted species'}})))
  assert.match(verified, /<dt>规范学名<\/dt><dd>Accepted species<\/dd>/)
})

test('the shared identity warning used by home, results and detail pages explains the conflict', () => {
  const markup = renderToStaticMarkup(createElement(IdentityWarning))
  assert.match(markup, /植物身份存在冲突/)
  assert.match(markup, /需核实身份后再用于物种判断/)
})
