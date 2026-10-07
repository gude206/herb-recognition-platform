import { useEffect, useReducer, useRef } from 'react'
import { sendChat } from '../api/chat'
import { chatHistory, chatSessionsReducer, GENERAL_CHAT, sessionFor } from '../utils/chatSessions'

export function useHerbChat(herbId?: string) {
  const [sessions, dispatch] = useReducer(chatSessionsReducer, {})
  const sessionsRef = useRef(sessions)
  sessionsRef.current = sessions
  const requests = useRef(new Map<string, AbortController>())
  const nextRequestId = useRef(0)
  const key = herbId || GENERAL_CHAT
  const session = sessionFor(sessions, key)
  useEffect(() => {
    const pending = requests.current
    return () => { pending.forEach(controller => controller.abort()); pending.clear() }
  }, [])

  const ask = async (text = session.question) => {
    const message = text.trim()
    if (!message || requests.current.has(key)) return
    const controller = new AbortController()
    const requestId = ++nextRequestId.current
    requests.current.set(key, controller)
    const history = chatHistory(sessionFor(sessionsRef.current, key))
    dispatch({ type: 'start', key, requestId, message })
    try {
      const response = await sendChat({ message, herb_id: herbId, history }, controller.signal)
      if (!controller.signal.aborted) dispatch({ type: 'success', key, requestId, answer: response.answer })
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: 'failure', key, requestId,
        error: error instanceof Error ? error.message : '问答服务暂时不可用，请稍后重试。' })
    } finally {
      if (requests.current.get(key) === controller) requests.current.delete(key)
    }
  }
  return { ...session, loading: session.requestId !== undefined, ask,
    setQuestion: (value: string) => dispatch({ type: 'question', key, value }) }
}
