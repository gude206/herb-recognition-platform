import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { loadSource } from './load-source.mjs'

const { apiClient } = await loadSource('src/api/client.ts')
const { getArticles, getArticle, knowledgeError } = await loadSource('src/api/knowledge.ts')
const { KnowledgePage } = await loadSource('src/pages/KnowledgePage.tsx')

test('article APIs use backend data by default and resolve server cover URLs', async () => {
  const original = apiClient.defaults.adapter
  const seen = []
  apiClient.defaults.adapter = async config => {
    seen.push(config.url)
    const article = { id:'a1', title:'数据库文章', category:'本草故事', excerpt:'摘要', body:'数据库正文',
      image:'/api/v1/articles/a1/cover', reads:'0', sourceKind:'editorial', reviewStatus:'已审核' }
    return { data: config.url === '/api/v1/articles' ? [article] : article, status:200, statusText:'OK', headers:{}, config }
  }
  try {
    const articles = await getArticles()
    const detail = await getArticle('a1')
    assert.equal(articles[0].title, '数据库文章')
    assert.equal(detail.body, '数据库正文')
    assert.equal(detail.image, 'http://localhost:8000/api/v1/articles/a1/cover')
    assert.deepEqual(seen, ['/api/v1/articles','/api/v1/articles/a1'])
  } finally { apiClient.defaults.adapter = original }
})

test('initial empty article state renders loading without fictional articles or counts', () => {
  const markup = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(KnowledgePage)))
  assert.match(markup, /正在加载科普文章/)
  assert.doesNotMatch(markup, /12\.8万|金银花的本草故事/)
})

test('article load failures distinguish backend errors, timeout and network failure', () => {
  assert.equal(knowledgeError({ isAxiosError:true, response:{ data:{ detail:'数据库未就绪' } } }), '数据库未就绪')
  assert.match(knowledgeError({ isAxiosError:true, code:'ECONNABORTED' }), /超时/)
  assert.match(knowledgeError({ isAxiosError:true }), /无法连接/)
})
