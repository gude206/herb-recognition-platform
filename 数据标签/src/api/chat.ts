import { isAxiosError } from 'axios'
import { apiClient } from './client'

export interface ChatMessage { role: 'user' | 'assistant'; content: string }
export interface ChatPayload { message: string; herb_id?: string; history?: ChatMessage[] }
export async function sendChat(payload: ChatPayload, signal?: AbortSignal): Promise<{ answer: string; references: string[]; model: string }> {
  try {
    return (await apiClient.post('/api/v1/chat', payload, { timeout: 195000, signal })).data
  } catch (error) {
    if (isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') throw new Error(detail)
      if (error.response?.status === 422) throw new Error('问题或对话过长，请缩短后重试。')
      if (error.code === 'ECONNABORTED') throw new Error('AI 回答超时，请稍后重试。')
    }
    throw new Error('暂时无法连接问答服务，请检查后端是否启动。')
  }
}
