import { isAxiosError } from 'axios'
import { apiClient } from './client'
import type { ChatArchive, ChatConversation } from '../utils/chatConversations'
import type { RecognitionResult } from '../types/recognition'

export interface RecognitionRecord { id: string; filename: string; createdAt: number; result: RecognitionResult }
export interface HistoryPage<T> { items: T[]; total: number; page: number; page_size: number }

export function historyError(error: unknown): string {
  if (isAxiosError(error) && typeof error.response?.data?.detail === 'string') return error.response.data.detail
  return '无法连接历史记录服务，请检查后端和 MySQL 是否启动。'
}

export async function importChatCache(archive: ChatArchive): Promise<void> {
  const conversations = archive.conversations.filter(item => item.messages.length)
  for (let offset = 0; offset < conversations.length; offset += 100) {
    await apiClient.post('/api/v1/history/import', { conversations: conversations.slice(offset, offset + 100)
      .map(item => ({ id: item.id, context: item.context, messages: item.messages,
        createdAt: item.createdAt, updatedAt: item.updatedAt })) })
  }
}

export async function loadChatHistory(): Promise<ChatConversation[]> {
  const conversations: ChatConversation[] = []
  let page = 1
  while (true) {
    const { data } = await apiClient.get<HistoryPage<ChatConversation>>('/api/v1/history/conversations', { params: { page, page_size: 100 } })
    conversations.push(...data.items.map(item => ({ ...item, question: '', pendingQuestion: '', error: '' })))
    if (page * data.page_size >= data.total) break
    page++
  }
  return conversations
}

export async function createChat(conversation: ChatConversation): Promise<void> {
  await apiClient.post('/api/v1/history/conversations', { id: conversation.id, context: conversation.context })
}

export async function loadRecognitionHistory(query: string, page: number, signal?: AbortSignal): Promise<HistoryPage<RecognitionRecord>> {
  return (await apiClient.get('/api/v1/history/recognitions', { params: { q: query, page, page_size: 8 }, signal })).data
}

export async function loadRecognitionImage(id: string): Promise<Blob> {
  return (await apiClient.get('/api/v1/history/recognitions/' + encodeURIComponent(id) + '/image', { responseType: 'blob' })).data
}
