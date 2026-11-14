import type { ChatMessage } from '../api/chat'
import { chatSessionsReducer, GENERAL_CHAT } from './chatSessions'
import type { ChatAction, ChatSession } from './chatSessions'

export const CHAT_STORAGE_KEY = 'herbal-knowledge-chat-history-v1'

export interface ChatContext {
  herbId?: string
  name?: string
  identityConflict?: boolean
}

export interface ChatConversation extends ChatSession {
  id: string
  context: ChatContext
  createdAt: number
  updatedAt: number
}

export interface ChatArchive {
  conversations: ChatConversation[]
  activeId: string
}

export type ConversationAction =
  | { type: 'hydrate'; conversations: ChatConversation[] }
  | { type: 'create'; conversation: ChatConversation }
  | { type: 'select'; id: string }
  | { type: 'session'; action: ChatAction; now: number }

export function contextKey(context: ChatContext): string {
  return context.herbId || GENERAL_CHAT
}

export function newConversation(context: ChatContext, id: string, now: number): ChatConversation {
  return { id, context: { ...context }, createdAt: now, updatedAt: now,
    messages: [], question: '', pendingQuestion: '', error: '' }
}

export function conversationTitle(conversation: ChatConversation): string {
  const firstQuestion = conversation.messages.find(message => message.role === 'user')?.content
  return (firstQuestion || conversation.pendingQuestion || conversation.question).trim() || (conversation.messages.some(m=>m.image_record_id)||conversation.pendingImageId?'图片识别':'新对话')
}

export function contextLabel(context: ChatContext): string {
  return context.name || (context.herbId ? `植物 ${context.herbId}` : '通用本草知识')
}

export function conversationHistory(archive: ChatArchive, query = ''): ChatConversation[] {
  const keyword = query.trim().toLocaleLowerCase()
  return archive.conversations.filter(conversation => {
    if (!conversation.messages.length && !conversation.question.trim() && !conversation.pendingQuestion && !conversation.pendingImageId) return false
    return !keyword || [conversationTitle(conversation), contextLabel(conversation.context),
      ...conversation.messages.map(message => message.content)].some(text => text.toLocaleLowerCase().includes(keyword))
  }).sort((left, right) => right.updatedAt - left.updatedAt)
}

export function latestForContext(archive: ChatArchive, context: ChatContext): ChatConversation | undefined {
  return [...archive.conversations].filter(item => contextKey(item.context) === contextKey(context))
    .sort((left, right) => right.updatedAt - left.updatedAt)[0]
}

export function chatConversationsReducer(archive: ChatArchive, action: ConversationAction): ChatArchive {
  if (action.type === 'hydrate') {
    // Keep drafts and requests in flight, while successful messages come from MySQL.
    const conversations = action.conversations.map(item => {
      const local = archive.conversations.find(previous => previous.id === item.id)
      return local ? { ...item, messages: local.messages.length > item.messages.length ? local.messages : item.messages,
        question: local.question, pendingQuestion: local.pendingQuestion,
        error: local.error, requestId: local.requestId, ...(local.pendingImageId?{pendingImageId:local.pendingImageId}:{}), ...(local.progress?{progress:local.progress}:{}) } : item
    })
    for (const local of archive.conversations) {
      if (!conversations.some(item => item.id === local.id) && (!local.messages.length || local.requestId !== undefined)) conversations.push(local)
    }
    const activeId = conversations.some(item => item.id === archive.activeId) ? archive.activeId : conversations[0]?.id
    return activeId ? { conversations, activeId } : archive
  }
  if (action.type === 'select') {
    return archive.conversations.some(item => item.id === action.id)
      ? { ...archive, activeId: action.id } : archive
  }
  if (action.type === 'create') {
    // Discard only untouched empty conversations, so repeated clicks do not fill the history.
    const conversations = archive.conversations.filter(item => item.messages.length || item.question.trim() || item.pendingQuestion || item.pendingImageId || item.requestId!==undefined)
    return { conversations: [...conversations, action.conversation], activeId: action.conversation.id }
  }
  const conversation = archive.conversations.find(item => item.id === action.action.key)
  if (!conversation) return archive
  const sessions = { [conversation.id]: conversation }
  const updated = chatSessionsReducer(sessions, action.action)
  if (updated === sessions) return archive
  return { ...archive, conversations: archive.conversations.map(item => item.id === conversation.id
    ? { ...conversation, ...updated[conversation.id], updatedAt: action.now } : item) }
}

export function serializeChatArchive(archive: ChatArchive): string {
  return JSON.stringify({ version: 1, activeId: archive.activeId,
    conversations: archive.conversations.map(item => ({
      id: item.id, context: item.context, createdAt: item.createdAt, updatedAt: item.updatedAt,
      messages: item.messages, question: item.question || item.pendingQuestion,
    })) })
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readContext(value: unknown): ChatContext | undefined {
  if (!isObject(value)) return undefined
  if (value.herbId !== undefined && (typeof value.herbId !== 'string' || !/^tcmp-\d{3}$/.test(value.herbId))) return undefined
  return { herbId: value.herbId as string | undefined,
    name: typeof value.name === 'string' ? value.name.slice(0, 120) : undefined,
    identityConflict: value.identityConflict === true }
}

export function parseChatArchive(raw: string | null): ChatArchive | undefined {
  if (!raw) return undefined
  try {
    const saved: unknown = JSON.parse(raw)
    if (!isObject(saved) || saved.version !== 1 || !Array.isArray(saved.conversations)) return undefined
    const conversations: ChatConversation[] = []
    const ids = new Set<string>()
    for (const entry of saved.conversations) {
      if (!isObject(entry) || typeof entry.id !== 'string' || !/^[a-zA-Z0-9-]{1,80}$/.test(entry.id) || ids.has(entry.id)) continue
      const context = readContext(entry.context)
      if (!context || typeof entry.createdAt !== 'number' || !Number.isFinite(new Date(entry.createdAt).getTime())
        || typeof entry.updatedAt !== 'number' || !Number.isFinite(new Date(entry.updatedAt).getTime()) || !Array.isArray(entry.messages)) continue
      const messages: ChatMessage[] = []
      let valid = entry.messages.length % 2 === 0
      for (const [index, message] of entry.messages.entries()) {
        if (!isObject(message) || message.role !== (index % 2 ? 'assistant' : 'user')
          || typeof message.content !== 'string' || (!message.content.trim() && !(index%2===0&&typeof message.image_record_id==='string'&&/^[a-f0-9-]{36}$/i.test(message.image_record_id)))) { valid = false; break }
        messages.push({ role: index % 2 ? 'assistant' : 'user', content: message.content,
          ...(index%2===0&&typeof message.image_record_id==='string'&&/^[a-f0-9-]{36}$/i.test(message.image_record_id)?{image_record_id:message.image_record_id}:{}) })
      }
      if (!valid) continue
      ids.add(entry.id)
      conversations.push({ ...newConversation(context, entry.id, entry.createdAt), updatedAt: entry.updatedAt,
        messages, question: typeof entry.question === 'string' ? entry.question.slice(0, 2000) : '' })
    }
    if (!conversations.length) return undefined
    const activeId = typeof saved.activeId === 'string' && ids.has(saved.activeId)
      ? saved.activeId : [...conversations].sort((left, right) => right.updatedAt - left.updatedAt)[0].id
    return { conversations, activeId }
  } catch { return undefined }
}
