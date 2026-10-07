import { apiClient, useMock, wait } from './client'
export interface LoginPayload { account: string; password: string; mode: 'password' | 'code' }
export async function login(payload: LoginPayload): Promise<{ token: string; user: { name: string } }> {
  if (!useMock) return (await apiClient.post('/api/v1/auth/login', payload)).data
  await wait(350)
  return { token: 'demo-session-token', user: { name: payload.account.split('@')[0] || '本草访客' } }
}
