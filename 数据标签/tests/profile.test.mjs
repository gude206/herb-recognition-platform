import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { loadSource } from './load-source.mjs'

const { setSession, getSession, safeLoginTarget } = await loadSource('src/api/session.ts')
const { apiClient } = await loadSource('src/api/client.ts')
const { Header } = await loadSource('src/components/common/Header.tsx')
const { ProfilePage } = await loadSource('src/pages/ProfilePage.tsx')
const { avatarFileError, changeAvatar, saveProfile } = await loadSource('src/api/profile.ts')
const render = component => renderToStaticMarkup(createElement(MemoryRouter, null, createElement(component)))
const user = { id: 'profile-user', account: 'member', name: '小叶', role: 'user' }

test('signed-in header shows an avatar entry and account name linking to personal center', () => {
  setSession(user)
  const markup = render(Header)
  assert.match(markup, /href="\/profile"/)
  assert.match(markup, /小叶的头像/)
  assert.match(markup, /default-avatar/)
  assert.doesNotMatch(markup, /header-login/)
  setSession(null)
  assert.match(render(Header), /用户登录/)
})

test('personal center requires login and exposes editable profile and private history when signed in', () => {
  setSession(null)
  let markup = render(ProfilePage)
  assert.match(markup, /前往登录/)
  assert.doesNotMatch(markup, /更换头像|搜索我的记录/)
  setSession(user)
  markup = render(ProfilePage)
  for (const label of ['更换头像', 'AI 对话记录', '图片识别记录', '搜索我的记录', '仅当前账号可见']) assert.ok(markup.includes(label), label)
  assert.equal(safeLoginTarget('/profile', 'user'), '/profile')
  setSession(null)
})

test('avatar type and size are checked before upload', () => {
  assert.equal(avatarFileError({ type: 'image/png', size: 2048 }), '')
  assert.match(avatarFileError({ type: 'image/svg+xml', size: 20 }), /JPG/)
  assert.match(avatarFileError({ type: 'image/jpeg', size: 2 * 1024 * 1024 + 1 }), /2MB/)
})

test('profile and avatar writes use session CSRF and update visible account state', async () => {
  const original = apiClient.defaults.adapter
  const requests = []
  setSession(user, 'b'.repeat(64))
  apiClient.defaults.adapter = async config => {
    requests.push(config)
    const updated = config.method === 'patch' ? { ...user, name: '本草爱好者' } : { ...getSession().user, avatar_url: '/api/v1/auth/me/avatar?v=1&u=profile-user' }
    return { data: { user: updated, bio: '观察植物' }, status: 200, statusText: 'OK', headers: {}, config }
  }
  try {
    await saveProfile('本草爱好者', '观察植物')
    assert.equal(getSession().user.name, '本草爱好者')
    await changeAvatar(new File(['image'], 'photo.png', { type: 'image/png' }))
    assert.match(getSession().user.avatar_url, /v=1/)
    assert.equal(requests[1].data.get('file').name, 'photo.png')
    await changeAvatar()
    assert.equal(requests[2].method, 'delete')
    for (const request of requests) { assert.equal(request.withCredentials, true); assert.equal(request.headers.get('X-CSRF-Token'), 'b'.repeat(64)) }
  } finally { apiClient.defaults.adapter = original; setSession(null) }
})
