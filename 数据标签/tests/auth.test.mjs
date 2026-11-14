import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { loadSource } from './load-source.mjs'

const { getSession, setSession, safeLoginTarget } = await loadSource('src/api/session.ts')
const { apiClient } = await loadSource('src/api/client.ts')
const { authError, refreshAuth } = await loadSource('src/api/auth.ts')
const { LoginPage } = await loadSource('src/pages/LoginPage.tsx')
const { AdminArticlesPage } = await loadSource('src/pages/AdminArticlesPage.tsx')
const { saveAdminArticle } = await loadSource('src/api/adminArticles.ts')

test('login page has user/admin entries and actual registration instead of demo login', () => {
  setSession(null)
  const markup = renderToStaticMarkup(createElement(MemoryRouter,null,createElement(LoginPage)))
  assert.match(markup,/用户登录/); assert.match(markup,/管理员登录/); assert.match(markup,/立即注册/)
  assert.match(markup,/关联当前浏览器的访客历史/)
  assert.doesNotMatch(markup,/验证码为|微信登录|GitHub登录|demo-session-token/)
})

test('redirect targets stay local and normal users cannot redirect into article maintenance', () => {
  for (const value of ['//evil.invalid','https://evil.invalid','/\\evil','/admin/articles\n']) assert.equal(safeLoginTarget(value,'user'),'/')
  assert.equal(safeLoginTarget('/admin/articles','user'),'/')
  assert.equal(safeLoginTarget('/admin/articles','admin'),'/admin/articles')
})

test('admin page does not expose data to anonymous or normal-user sessions', () => {
  setSession({id:'u1',account:'user',name:'用户',role:'user'})
  const markup = renderToStaticMarkup(createElement(MemoryRouter,null,createElement(AdminArticlesPage)))
  assert.match(markup,/正在验证管理员登录/)
  assert.doesNotMatch(markup,/新增文章|文章正文/)
  setSession(null)
})

test('authenticated article writes include CSRF and optimistic version, never a localStorage auth token', async () => {
  const adapter = apiClient.defaults.adapter
  let request
  setSession({id:'admin-1',account:'admin',name:'管理员',role:'admin'},'a'.repeat(64))
  apiClient.defaults.adapter = async config => { request=config; return {data:{id:'a1',version:3,image:''},status:200,statusText:'OK',headers:{},config} }
  try {
    await saveAdminArticle({title:'标题',category:'植物知识',excerpt:'',body:'正文',status:'draft',reviewStatus:'未审核',sourceKind:'editorial',sourceNote:'',displayOrder:1},{id:'a1',version:2})
    assert.equal(request.headers.get('X-CSRF-Token'),'a'.repeat(64))
    assert.equal(request.withCredentials,true)
    assert.equal(JSON.parse(request.data).expectedVersion,2)
    assert.equal(request.headers.has('Authorization'),false)
  } finally {apiClient.defaults.adapter=adapter;setSession(null)}
})

test('authentication errors do not pretend success', () => {
  assert.equal(authError({isAxiosError:true,response:{data:{detail:'用户名或密码错误'}}}),'用户名或密码错误')
  assert.match(authError({isAxiosError:true,response:{status:422,data:{detail:[]}}}),/12/)
  assert.equal(authError({isAxiosError:true,config:{url:'/api/v1/admin/articles'},response:{status:422,data:{detail:[{msg:'Value error, 仅可发布已审核的科普文章'}]}}}),'仅可发布已审核的科普文章')
  assert.equal(getSession().user,null)
})

test('an unavailable session endpoint does not downgrade an unknown account to a visitor cache', async () => {
  const adapter = apiClient.defaults.adapter
  apiClient.defaults.adapter = async () => { throw {isAxiosError:true} }
  try {
    await assert.rejects(refreshAuth())
    assert.equal(getSession().ready,false)
    const markup = renderToStaticMarkup(createElement(MemoryRouter,null,createElement(LoginPage)))
    assert.match(markup,/重新读取登录状态/)
  } finally {apiClient.defaults.adapter=adapter;setSession(null)}
})
