import { isAxiosError } from 'axios'
import { apiClient } from './client'
import { rotateHistoryToken } from './historyIdentity'
import { getSession, setSession, setSessionUnavailable } from './session'
import type { AccountUser } from './session'
import { CHAT_STORAGE_KEY, parseChatArchive } from '../utils/chatConversations'
import { importChatCache } from './history'

interface AuthResponse { authenticated: boolean; user: AccountUser | null; csrf_token: string | null; claimed?: {claimed: boolean; conversations: number; recognitions: number} }
export interface LoginPayload { account: string; password: string; role: 'user' | 'admin'; remember: boolean; claim_guest_history: boolean }
export interface RegisterPayload { account: string; name: string; password: string; claim_guest_history: boolean }
let initialization: Promise<void> | undefined

export function authError(error: unknown) {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (error.response?.status === 422 && error.config?.url?.startsWith('/api/v1/auth/me/')) return '请检查资料格式：昵称不能为空且不超过 80 字，简介不超过 300 字；头像须为有效图片。'
    if (error.response?.status === 422 && error.config?.url?.startsWith('/api/v1/admin/') && Array.isArray(detail)) {
      return detail.map(item => typeof item?.msg === 'string' ? item.msg.replace(/^Value error, /, '') : '').filter(Boolean).join('；') || '请检查文章内容与发布条件。'
    }
    if (error.response?.status === 422) return '请检查用户名和密码格式，注册密码至少需要 12 位。'
    if (!error.response) return '无法连接登录服务，请检查后端和 MySQL 是否启动。'
  }
  return '认证操作失败，请稍后重试。'
}

export function initializeAuth(): Promise<void> {
  if (!initialization) initialization = refreshAuth().catch(() => {})
  return initialization
}

export function refreshAuth(): Promise<void> {
  return apiClient.get<AuthResponse>('/api/v1/auth/me').then(({data}) => {
    setSession(data.user, data.csrf_token || '')
    try { localStorage.removeItem('herb-token'); localStorage.removeItem('herb-user') } catch { /* Old demo fields are optional. */ }
  }).catch(error => {
    // Unknown cookie state must not cause account history to be stored as a visitor cache.
    setSessionUnavailable(authError(error))
    throw error
  })
}

async function prepareGuestCache(claim: boolean) {
  if (!claim || getSession().user) return
  try {
    const archive = parseChatArchive(localStorage.getItem(CHAT_STORAGE_KEY))
    if (archive) await importChatCache(archive)
  } catch { /* Server-owned guest history can still be associated. */ }
}

function acceptSession(data: AuthResponse) {
  setSession(data.user, data.csrf_token || '')
  if (data.claimed?.claimed) {
    rotateHistoryToken()
    try { localStorage.removeItem(CHAT_STORAGE_KEY) } catch { /* Server migration is already complete. */ }
  }
  return data
}

export async function login(payload: LoginPayload) {
  await refreshAuth()
  await prepareGuestCache(payload.claim_guest_history)
  return acceptSession((await apiClient.post<AuthResponse>('/api/v1/auth/login', payload)).data)
}

export async function register(payload: RegisterPayload) {
  await refreshAuth()
  await prepareGuestCache(payload.claim_guest_history)
  return acceptSession((await apiClient.post<AuthResponse>('/api/v1/auth/register', payload)).data)
}

export async function logout() {
  await apiClient.post('/api/v1/auth/logout')
  const user = getSession().user
  if (user) { try { sessionStorage.removeItem(CHAT_STORAGE_KEY + ':account:' + user.id) } catch { /* No retained draft storage. */ } }
  setSession(null)
  initialization = undefined
}
