import { useEffect, useRef, useState } from 'react'
import { Bot, Clock3, MessageCirclePlus, MessageSquareText, RefreshCw, Search, Send, X } from 'lucide-react'
import { SectionTitle } from '../common/SectionTitle'
import { useHerbChat } from '../../hooks/useHerbChat'
import { contextLabel, conversationHistory, conversationTitle } from '../../utils/chatConversations'
import type { ChatContext } from '../../utils/chatConversations'
import { useAccountSession } from '../../api/session'
import { AgentChat, AgentToolCalls, ChatUserMessage } from './AgentChat'
import { initialSuggestedPrompts, rememberSuggestedPrompts } from '../../utils/suggestedPrompts'

function formatTime(timestamp: number) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(timestamp)
}

export function HerbAssistant({ context }: { context?: ChatContext }) {
  const account = useAccountSession()
  const [prompts] = useState(initialSuggestedPrompts)
  useEffect(() => rememberSuggestedPrompts(prompts), [prompts])
  return <HerbAssistantBody key={account.ready ? account.user?.id || 'guest' : 'session-loading'} context={context} prompts={prompts}/>
}

function HerbAssistantBody({ context, prompts }: { context?: ChatContext; prompts: string[] }) {
  const account = useAccountSession()
  const chat = useHerbChat(context)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [imageRecordId,setImageRecordId] = useState<string>()
  const [imageUploading,setImageUploading] = useState(false)
  const activeConversation=useRef(chat.id)
  activeConversation.current=chat.id
  async function sendQuestion(text=chat.question){
    if(imageUploading)return
    const sentImage=imageRecordId,sentConversation=chat.id
    const success=await chat.ask(text,sentImage,()=>setImageRecordId(undefined))
    if(success===false&&sentImage&&activeConversation.current===sentConversation)setImageRecordId(current=>current||sentImage)
  }
  const chatBody = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const historyButton = useRef<HTMLButtonElement>(null)
  const previousView = useRef({ historyOpen, id: chat.id })
  const history = conversationHistory(chat.archive, query)
  const allHistory = conversationHistory(chat.archive)

  useEffect(() => {
    if (chatBody.current) chatBody.current.scrollTop = chatBody.current.scrollHeight
  }, [chat.id, chat.messages, chat.loading, chat.error, historyOpen])

  useEffect(() => {
    if (!historyOpen && (previousView.current.historyOpen || previousView.current.id !== chat.id)) input.current?.focus({ preventScroll: true })
    previousView.current = { historyOpen, id: chat.id }
  }, [historyOpen, chat.id])

  const startNewChat = () => { chat.newChat(); setHistoryOpen(false); setQuery('') }
  const closeHistory = () => { setHistoryOpen(false); historyButton.current?.focus({ preventScroll: true }) }

  return <div className="paper-card assistant-card" id="assistant">
    <SectionTitle icon={<Bot />} title="AI 中医药助手" sub="支持植物资料查询、图片识别、文本分类与连续追问" action={
      <div className="chat-actions">
        <button ref={historyButton} type="button" className="chat-action" aria-label="历史对话" title="历史对话"
          aria-expanded={historyOpen} aria-controls="chat-history-panel" onClick={() => setHistoryOpen(!historyOpen)}><Clock3 size={19} /></button>
        <button type="button" className="chat-action" aria-label="新对话" title="新对话" onClick={startNewChat}><MessageCirclePlus size={19} /></button>
      </div>
    } />
    {historyOpen ? <section id="chat-history-panel" className="chat-history-panel" aria-label="历史对话列表"
      onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); closeHistory() } }}>
      <div className="chat-history-heading"><h3>历史对话 <span>{allHistory.length}</span></h3>
        <button type="button" className="chat-action" aria-label="刷新历史对话" title="从 MySQL 刷新历史" disabled={chat.historyLoading}
          onClick={() => void chat.refreshHistory()}><RefreshCw size={15} className={chat.historyLoading ? 'spin' : ''} /></button>
        <button type="button" className="chat-action" aria-label="关闭历史记录" title="返回对话" onClick={closeHistory}><X size={17} /></button></div>
      <div className="chat-history-search"><Search size={16} /><input autoFocus value={query} onChange={event => setQuery(event.target.value)}
        aria-label="搜索历史对话" placeholder="搜索问题、回答或植物名称" />
        {query && <button type="button" className="chat-search-clear" aria-label="清空历史搜索" onClick={() => setQuery('')}><X size={14} /></button>}</div>
      <div className="chat-history-list">
        {history.map(conversation => <button type="button" className="chat-history-item" key={conversation.id}
          aria-current={conversation.id === chat.id ? 'true' : undefined}
          onClick={() => { chat.selectChat(conversation.id); setHistoryOpen(false) }}>
          <MessageSquareText size={17} />
          <span className="chat-history-copy"><strong>{conversationTitle(conversation)}</strong>
            <span>{contextLabel(conversation.context)} · {conversation.messages.length / 2} 条问答{conversation.requestId !== undefined ? ' · 正在回答' : ''}</span></span>
          <time dateTime={new Date(conversation.updatedAt).toISOString()}>{formatTime(conversation.updatedAt)}</time>
        </button>)}
        {!history.length && <div className="chat-history-empty"><Clock3 size={30} /><strong>{query.trim() ? '没有找到相关对话' : '还没有历史对话'}</strong>
          <p>{query.trim() ? '试试其他关键词，问题和回答都可以搜索。' : '发送第一个问题后，就会在这里留下记录。'}</p>
          {!query.trim() && <button type="button" className="button button-light" onClick={startNewChat}><MessageCirclePlus size={16} />开始新对话</button>}</div>}
      </div>
      <p className="chat-storage-note">{account.user ? '记录保存在当前登录账号下，换设备登录后可继续查看。' : '当前为访客记录；登录或注册时可关联到账号。'}</p>
    </section> : <>
      <div className="chat-session-heading"><MessageSquareText size={14} /><strong title={conversationTitle(chat)}>{conversationTitle(chat)}</strong>
        <span>{chat.messages.length / 2} 条问答</span></div>
      <p className="chat-context" role="status">当前参考：<strong>{contextLabel(chat.context)}</strong>
        {chat.context.herbId && <> · {chat.context.identityConflict ? '该记录不提供植物参考资料' : '植物参考资料'}</>}
        <small>{chat.historyLoading ? '正在读取 MySQL 历史记录…' : '问答成功后自动保存到 MySQL；历史对话保留原植物参考。'}</small></p>
      <div className="chat-body" ref={chatBody} aria-label="问答记录" aria-busy={chat.loading} aria-live="polite" aria-relevant="additions text">
        <div className="chat-bubble assistant-bubble"><span className="bot-avatar"><Bot size={20} /></span><div>您好！我是草药助手，能够为您介绍中草药的植物形态、知识库条目与本草文化。<br />请问您想了解什么？<small>本助手用于知识科普，不提供诊断或用药建议。</small></div></div>
        {chat.messages.map((item, index) => item.role === 'user'
          ? <ChatUserMessage message={item} key={index}/>
          : <div className="chat-bubble assistant-bubble" key={index}><span className="bot-avatar"><Bot size={20} /></span><div>{item.content}<AgentToolCalls calls={item.tool_calls}/></div></div>)}
        {chat.loading && <><ChatUserMessage message={{role:'user',content:chat.pendingQuestion,image_record_id:chat.pendingImageId}}/><div className="chat-bubble assistant-bubble" role="status"><span className="bot-avatar"><Bot size={20} /></span><div className="typing">{chat.progress || '正在理解问题…'}</div></div></>}
        {chat.error && <p className="chat-error" role="alert">{chat.error}</p>}
      </div>
      <div className="prompt-chips">{prompts.map(item =>
        <button key={item} disabled={chat.loading || chat.historyLoading || imageUploading} onClick={() => void sendQuestion(item)}>{item}</button>)}</div>
      <AgentChat conversationId={chat.id} disabled={chat.loading||chat.historyLoading} value={imageRecordId} onAttachment={setImageRecordId} onUploading={setImageUploading}/>
      <form className="chat-input" onSubmit={event => { event.preventDefault(); void sendQuestion() }}>
        <input ref={input} value={chat.question} onChange={event => chat.setQuestion(event.target.value)} maxLength={2000}
          disabled={chat.loading || chat.historyLoading} placeholder="请输入您想了解的中草药问题…" aria-label="输入问题" />
        <button aria-label="发送问题" disabled={chat.loading || chat.historyLoading || imageUploading || (!chat.question.trim()&&!imageRecordId)}><Send size={17} /></button>
      </form>
    </>}
    {chat.storageError && <p className="chat-storage-warning" role="status">{chat.storageError}</p>}
  </div>
}
