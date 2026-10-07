import assert from 'node:assert/strict'
import test from 'node:test'
import { loadSource } from './load-source.mjs'

const { chatSessionsReducer: reduce, chatHistory, sessionFor, GENERAL_CHAT } = await loadSource('src/utils/chatSessions.ts')
const { galleryReturnTo, returnToFromState } = await loadSource('src/utils/atlasNavigation.ts')
const { galleryError } = await loadSource('src/utils/galleryError.ts')
const { matchesHerbQuery } = await loadSource('src/utils/herbSearch.ts')

test('new plant receives no old history; an in-flight reply stays with its original plant', () => {
  let state = reduce({}, { type: 'start', key: 'tcmp-001', requestId: 1, message: '它在哪里生长？' })
  assert.deepEqual(chatHistory(sessionFor(state, 'tcmp-002')), [])
  state = reduce(state, { type: 'start', key: 'tcmp-002', requestId: 2, message: '这株植物是什么？' })
  state = reduce(state, { type: 'success', key: 'tcmp-001', requestId: 1, answer: '第一株植物的资料' })
  assert.equal(sessionFor(state, 'tcmp-001').messages[1].content, '第一株植物的资料')
  assert.deepEqual(sessionFor(state, 'tcmp-002').messages, [])
  assert.equal(sessionFor(state, 'tcmp-002').pendingQuestion, '这株植物是什么？')
  assert.equal(sessionFor(state, 'tcmp-002').requestId, 2)
  state = reduce(state, { type: 'success', key: 'tcmp-002', requestId: 2, answer: '第二株植物的资料' })
  assert.equal(chatHistory(sessionFor(state, 'tcmp-002'))[1].content, '第二株植物的资料')
  assert.deepEqual(chatHistory(sessionFor(state, GENERAL_CHAT)), [])
})

test('failed requests restore only their own draft; duplicate and stale completions are ignored', () => {
  let state = reduce({}, { type: 'start', key: 'tcmp-001', requestId: 1, message: '原问题' })
  const pending = state
  state = reduce(state, { type: 'start', key: 'tcmp-001', requestId: 2, message: '重复问题' })
  assert.equal(state, pending)
  state = reduce(state, { type: 'failure', key: 'tcmp-001', requestId: 1, error: '超时' })
  assert.equal(sessionFor(state, 'tcmp-001').question, '原问题')
  assert.deepEqual(sessionFor(state, 'tcmp-001').messages, [])
  const failed = state
  state = reduce(state, { type: 'success', key: 'tcmp-001', requestId: 1, answer: '过期回答' })
  assert.equal(state, failed)
  assert.equal(sessionFor(state, 'tcmp-002').question, '')
})

test('history respects the backend limit of six turns and 6000 characters per message', () => {
  const messages = Array.from({ length: 16 }, (_, index) => ({role: index % 2 ? 'assistant' : 'user', content: String(index) + '字'.repeat(6500)}))
  const history = chatHistory({ messages, question: '', pendingQuestion: '', error: '' })
  assert.equal(history.length, 12)
  assert.ok(history[0].content.startsWith('4'))
  assert.ok(history.every(message => message.content.length === 6000))
  assert.equal(messages[0].content.length, 6501)
})

test('gallery return preserves filters and page across related details', () => {
  const original = '/herbs?q=%E9%87%91%E9%93%B6%E8%8A%B1&family=Caprifoliaceae&page=3&sort=name'
  assert.equal(galleryReturnTo(original), original)
  const relatedState = { galleryReturnTo: returnToFromState({ galleryReturnTo: original }) }
  assert.equal(returnToFromState(relatedState), original)
})

test('gallery return rejects external, unrelated, malformed and protocol-relative URLs', () => {
  for (const value of [undefined, null, {}, '//example.org/herbs', 'https://example.org/herbs', 'https://gallery.invalid/herbs', '/login', '/herbs/001', '/herbs#bad', '/herbs\\evil', '/herbs\n', '/herbs/../login']) {
    assert.equal(galleryReturnTo(value), '/herbs', String(value))
  }
  assert.equal(returnToFromState({ galleryReturnTo: 'javascript:alert(1)' }), '/herbs')
})

test('invalid parameters, timeout, offline and server errors have distinct actionable messages', () => {
  const axiosError = properties => ({isAxiosError: true, ...properties})
  assert.match(galleryError(axiosError({response: {status: 422}})), /参数无效/)
  assert.match(galleryError(axiosError({code: 'ECONNABORTED'})), /超时/)
  assert.match(galleryError(axiosError({code: 'ERR_NETWORK'})), /无法连接/)
  assert.match(galleryError(axiosError({response: {status: 500}})), /服务暂时出现错误/)
  assert.doesNotMatch(galleryError(axiosError({response: {status: 422}})), /服务已启动/)
})

test('offline gallery searches include effects, aliases, Latin names and material names', () => {
  const herb = {name:'忍冬', latinName:'Lonicera japonica', aliases:['金银花'], effects:['清热解毒'], materials:[{'药材名称':'忍冬藤'}]}
  for (const query of ['清热解毒','金银花','LONICERA','忍冬藤','  忍冬  ','']) assert.equal(matchesHerbQuery(herb,query), true, query)
  assert.equal(matchesHerbQuery(herb,'不存在的功效'), false)
  assert.equal(matchesHerbQuery({...herb,materials:undefined},'清热解毒'), true)
})
