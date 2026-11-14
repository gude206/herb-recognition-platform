import { apiClient } from './client'
import { getSession, setSession } from './session'
import type { AccountUser } from './session'
import type { HistoryPage } from './history'
import type { ChatConversation } from '../utils/chatConversations'

export interface UserProfile {
  user: AccountUser
  bio: string
  created_at: string
  stats: { conversations: number; recognitions: number }
}

function acceptUser(user: AccountUser) {
  const session = getSession()
  if (session.user?.id === user.id) setSession(user, session.csrfToken)
}
export async function loadProfile(signal?: AbortSignal): Promise<UserProfile> {
  return (await apiClient.get('/api/v1/auth/me/profile', { signal })).data
}
export async function saveProfile(name: string, bio: string): Promise<UserProfile> {
  const { data } = await apiClient.patch<UserProfile>('/api/v1/auth/me/profile', { name, bio })
  acceptUser(data.user)
  return data
}
export async function changeAvatar(file?: File): Promise<AccountUser> {
  const endpoint = '/api/v1/auth/me/avatar'
  const form = new FormData()
  if (file) form.append('file', file)
  const { data } = file
    ? await apiClient.put<{ user: AccountUser }>(endpoint, form)
    : await apiClient.delete<{ user: AccountUser }>(endpoint)
  acceptUser(data.user)
  return data.user
}
export async function loadProfileConversations(query: string, page: number, signal?: AbortSignal): Promise<HistoryPage<ChatConversation>> {
  return (await apiClient.get('/api/v1/history/conversations', { params: { q: query, page, page_size: 8 }, signal })).data
}

export function avatarFileError(file: File): string {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return '请选择 JPG、PNG 或 WEBP 图片。'
  if (file.size > 2 * 1024 * 1024) return '头像不能超过 2MB。'
  return ''
}
