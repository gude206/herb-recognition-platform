import type { ChatMessage } from '../api/chat'

export const GENERAL_CHAT = 'general'
export interface ChatSession {
  messages: ChatMessage[]
  question: string
  pendingQuestion: string
  error: string
  requestId?: number
}
export type ChatSessions = Record<string, ChatSession>
export type ChatAction =
  | { type: 'question'; key: string; value: string }
  | { type: 'start'; key: string; requestId: number; message: string }
  | { type: 'success'; key: string; requestId: number; answer: string }
  | { type: 'failure'; key: string; requestId: number; error: string }

export function sessionFor(sessions: ChatSessions, key: string): ChatSession {
  return sessions[key] || { messages: [], question: '', pendingQuestion: '', error: '' }
}

export function chatHistory(session: ChatSession): ChatMessage[] {
  return session.messages.slice(-12).map(item => ({ ...item, content: item.content.slice(0, 6000) }))
}

// Completion carries the context captured at send time, including while another plant is visible.
export function chatSessionsReducer(sessions: ChatSessions, action: ChatAction): ChatSessions {
  const previous = sessionFor(sessions, action.key)
  if (action.type === 'question') return { ...sessions, [action.key]: { ...previous, question: action.value } }
  if (action.type === 'start') {
    if (previous.requestId !== undefined) return sessions
    return { ...sessions, [action.key]: { ...previous, question: '', pendingQuestion: action.message, error: '', requestId: action.requestId } }
  }
  if (previous.requestId !== action.requestId) return sessions
  const completed = { ...previous, pendingQuestion: '', requestId: undefined }
  return { ...sessions, [action.key]: action.type === 'success'
    ? { ...completed, messages: [...previous.messages, { role: 'user', content: previous.pendingQuestion }, { role: 'assistant', content: action.answer }] }
    : { ...completed, error: action.error, question: previous.pendingQuestion } }
}
