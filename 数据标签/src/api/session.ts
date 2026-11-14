import { useSyncExternalStore } from 'react'

export interface AccountUser { id: string; account: string; name: string; role: 'user' | 'admin'; avatar_url?: string | null }
export interface AccountSession { ready: boolean; user: AccountUser | null; csrfToken: string; error: string }
let session: AccountSession = { ready: false, user: null, csrfToken: '', error: '' }
const listeners = new Set<() => void>()

export function getSession() { return session }
export function setSession(user: AccountUser | null, csrfToken = '') {
  session = { ready: true, user, csrfToken, error: '' }
  listeners.forEach(listener => listener())
}
export function setSessionUnavailable(error: string) {
  session = { ready: false, user: null, csrfToken: '', error }
  listeners.forEach(listener => listener())
}
export function useAccountSession() {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => listeners.delete(listener) }, getSession, getSession)
}

export function safeLoginTarget(value: string | null, role: 'user' | 'admin'): string {
  if (value && value.startsWith('/') && !value.startsWith('//') && !value.includes('\\')
    && !/[\r\n]/.test(value) && (value === '/' || value === '/admin/articles' || value === '/profile')
    && (value !== '/admin/articles' || role === 'admin')) return value
  return role === 'admin' ? '/admin/articles' : '/'
}
