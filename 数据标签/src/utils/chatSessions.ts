import type { ChatMessage, ToolCall } from '../api/chat'

export const GENERAL_CHAT = 'general'
export interface ChatSession {
  messages: ChatMessage[]
  question: string
  pendingQuestion: string
  pendingImageId?: string
  error: string
  requestId?: number
  progress?: string
}
export type ChatSessions = Record<string, ChatSession>
export type ChatAction =
  | { type: 'progress'; key: string; requestId: number; message: string }
  | { type: 'question'; key: string; value: string }
  | { type: 'start'; key: string; requestId: number; message: string; image_record_id?: string }
  | { type: 'success'; key: string; requestId: number; answer: string; tool_calls?: ToolCall[] }
  | { type: 'failure'; key: string; requestId: number; error: string }

export function sessionFor(sessions: ChatSessions, key: string): ChatSession {
  return sessions[key] || { messages: [], question: '', pendingQuestion: '', error: '' }
}

export function chatHistory(session: ChatSession): ChatMessage[] {
  return session.messages.slice(-12).map(item => ({ ...item, content: (item.content || (item.image_record_id?'[用户发送了一张植物图片]':'')).slice(0, 6000) }))
}

// Completion carries the context captured at send time, including while another plant is visible.
export function chatSessionsReducer(sessions: ChatSessions, action: ChatAction): ChatSessions {
  const previous = sessionFor(sessions, action.key)
  if (action.type === 'question') return { ...sessions, [action.key]: { ...previous, question: action.value } }
  if (action.type === 'start') {
    if (previous.requestId !== undefined) return sessions
    return { ...sessions, [action.key]: { ...previous, question: '', pendingQuestion: action.message, ...(action.image_record_id?{pendingImageId:action.image_record_id}:{}), error: '', requestId: action.requestId } }
  }
  if (previous.requestId !== action.requestId) return sessions
  if(action.type==='progress')return {...sessions,[action.key]:{...previous,progress:action.message}}
  const {progress: _progress,pendingImageId: _image,...withoutProgress}=previous
  const completed = { ...withoutProgress, pendingQuestion: '', requestId: undefined }
  return { ...sessions, [action.key]: action.type === 'success'
    ? { ...completed, messages: [...previous.messages, { role: 'user', content: previous.pendingQuestion, ...(previous.pendingImageId?{image_record_id:previous.pendingImageId}:{}) }, { role: 'assistant', content: action.answer, ...(action.tool_calls ? {tool_calls: action.tool_calls} : {}) }] }
    : { ...completed, error: action.error, question: previous.pendingQuestion } }
}
