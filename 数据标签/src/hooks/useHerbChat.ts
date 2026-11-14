import { useEffect, useReducer, useRef, useState } from 'react'
import { sendChat } from '../api/chat'
import { createChat, historyError, importChatCache, loadChatHistory } from '../api/history'
import { getSession, useAccountSession } from '../api/session'
import { chatHistory } from '../utils/chatSessions'
import { CHAT_STORAGE_KEY, chatConversationsReducer, contextKey, latestForContext,
  newConversation, parseChatArchive, serializeChatArchive } from '../utils/chatConversations'
import type { ChatArchive, ChatContext } from '../utils/chatConversations'

function createConversation(context: ChatContext) {
  return newConversation(context, crypto.randomUUID(), Date.now())
}

function restoreArchive(context: ChatContext): ChatArchive {
  try {
    const account = getSession()
    const saved = account.ready ? parseChatArchive(account.user
      ? sessionStorage.getItem(CHAT_STORAGE_KEY + ':account:' + account.user.id)
      : localStorage.getItem(CHAT_STORAGE_KEY)) : undefined
    if (saved) return saved
  } catch { /* The chat still works when browser storage is unavailable. */ }
  const conversation = createConversation(context)
  return { conversations: [conversation], activeId: conversation.id }
}

export function useHerbChat(context: ChatContext = {}) {
  const account = useAccountSession()
  const [archive, dispatch] = useReducer(chatConversationsReducer, context, restoreArchive)
  const [storageError, setStorageError] = useState('')
  const [databaseError, setDatabaseError] = useState('')
  const [historyLoading, setHistoryLoading] = useState(true)
  const archiveRef = useRef(archive)
  archiveRef.current = archive
  const requests = useRef(new Map<string, AbortController>())
  const nextRequestId = useRef(0)
  const previousContext = useRef(contextKey(context))
  const session = archive.conversations.find(item => item.id === archive.activeId)!

  const refreshHistory = async () => {
    setHistoryLoading(true)
    try {
      if (!account.user) await importChatCache(archiveRef.current)
      const conversations = await loadChatHistory()
      dispatch({ type: 'hydrate', conversations })
      setDatabaseError('')
    } catch (error) { setDatabaseError(historyError(error) + (account.user ? '' : ' 当前显示本机缓存。')) }
    finally { setHistoryLoading(false) }
  }

  useEffect(() => {
    if (!account.ready) return
    let alive = true
    const load = async () => {
      try {
        if (!account.user) await importChatCache(archiveRef.current)
        const conversations = await loadChatHistory()
        if (alive) { dispatch({ type: 'hydrate', conversations }); setDatabaseError('') }
      } catch (error) { if (alive) setDatabaseError(historyError(error) + (account.user ? '' : ' 当前显示本机缓存。')) }
      finally { if (alive) setHistoryLoading(false) }
    }
    void load()
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!account.ready) return
    try {
      if (account.user) {
        // Only selection/context/drafts are kept in this tab; completed account messages stay on the server.
        const preferences = { ...archive, conversations: archive.conversations.map(item => ({ ...item, messages: [] })) }
        sessionStorage.setItem(CHAT_STORAGE_KEY + ':account:' + account.user.id, serializeChatArchive(preferences))
      } else localStorage.setItem(CHAT_STORAGE_KEY, serializeChatArchive(archive))
      setStorageError('')
    } catch { setStorageError(account.user ? '浏览器暂时无法保存草稿，已完成的问答仍保存在账号中。' : '浏览器暂时无法保存历史记录，本次对话仍可继续。') }
  }, [archive])

  useEffect(() => {
    const key = contextKey(context)
    if (key === previousContext.current) return
    previousContext.current = key
    const existing = latestForContext(archiveRef.current, context)
    if (existing) dispatch({ type: 'select', id: existing.id })
    else dispatch({ type: 'create', conversation: createConversation(context) })
  }, [context.herbId, context.name, context.identityConflict])

  useEffect(() => {
    const pending = requests.current
    return () => { pending.forEach(controller => controller.abort()); pending.clear() }
  }, [])

  const ask = async (text = session.question, imageRecordId?: string, onStart?:()=>void) => {
    const current = archiveRef.current.conversations.find(item => item.id === archiveRef.current.activeId)!
    const key = current.id
    const message = text.trim()
    if ((!message&&!imageRecordId) || requests.current.has(key) || historyLoading || !account.ready) return
    const controller = new AbortController()
    const requestId = ++nextRequestId.current
    requests.current.set(key, controller)
    const history = chatHistory(current)
    dispatch({ type: 'session', action: { type: 'start', key, requestId, message, image_record_id:imageRecordId }, now: Date.now() })
    onStart?.()
    try {
      const response = await sendChat({ message, herb_id: current.context.herbId, history, conversation_id: key, image_record_id: imageRecordId }, controller.signal,
        message=>dispatch({type:'session',action:{type:'progress',key,requestId,message},now:Date.now()}))
      if (response.saved) setDatabaseError('')
      else setDatabaseError('本次回答未写入 MySQL，仅保存在本机缓存。')
      if (!controller.signal.aborted) dispatch({ type: 'session',
        action: { type: 'success', key, requestId, answer: response.answer, tool_calls: response.tool_calls }, now: Date.now() })
      return controller.signal.aborted?undefined:true
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: 'session', action: { type: 'failure', key, requestId,
        error: error instanceof Error ? error.message : '问答服务暂时不可用，请稍后重试。' }, now: Date.now() })
      return controller.signal.aborted?undefined:false
    } finally {
      if (requests.current.get(key) === controller) requests.current.delete(key)
    }
  }
  return { ...session, archive, storageError: databaseError || storageError, historyLoading, refreshHistory,
    loading: session.requestId !== undefined, ask,
    newChat: () => {
      const conversation = createConversation(session.context)
      dispatch({ type: 'create', conversation })
      void createChat(conversation).catch(error => setDatabaseError(historyError(error)))
    },
    selectChat: (id: string) => dispatch({ type: 'select', id }),
    setQuestion: (value: string) => dispatch({ type: 'session',
      action: { type: 'question', key: session.id, value }, now: Date.now() }) }
}
