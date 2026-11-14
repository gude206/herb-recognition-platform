import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { authError, refreshAuth } from '../api/auth'
import { useAccountSession } from '../api/session'
import type { AccountUser } from '../api/session'
import { avatarFileError, changeAvatar, loadProfile, loadProfileConversations, saveProfile } from '../api/profile'
import type { UserProfile } from '../api/profile'
import { historyError, loadRecognitionHistory } from '../api/history'
import type { RecognitionRecord } from '../api/history'
import { UserAvatar } from '../components/common/UserAvatar'
import { ChatMessageImage, ChatUserMessage } from '../components/chat/AgentChat'
import { conversationTitle, type ChatConversation } from '../utils/chatConversations'

const dateLabel = (value: string | number) => new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })

export function ProfilePage() {
  const session = useAccountSession()
  if (session.error) return <section className="page-shell profile-gate"><h1>个人中心</h1><p role="alert">{session.error}</p><button className="button button-light" onClick={() => void refreshAuth().catch(() => {})}>重新读取登录状态</button></section>
  if (!session.ready) return <div className="loading-box">正在读取登录状态…</div>
  if (!session.user) return <section className="page-shell profile-gate"><h1>个人中心</h1><p>登录后查看你的个人资料、AI 对话和植物识别记录。</p><Link className="button button-primary" to="/login?next=/profile">前往登录</Link></section>
  return <ProfileContent key={session.user.id} user={session.user} />
}

function ProfileContent({ user }: { user: AccountUser }) {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [name, setName] = useState(''), [bio, setBio] = useState('')
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(''), [error, setError] = useState('')
  const [retry, setRetry] = useState(0), [profileLoading, setProfileLoading] = useState(true)
  const picker = useRef<HTMLInputElement>(null)
  useEffect(() => {
    let alive = true
    const controller = new AbortController()
    setProfileLoading(true); setError('')
    void loadProfile(controller.signal).then(data => {
      if (alive) { setProfile(data); setName(data.user.name); setBio(data.bio) }
    }).catch(error => { if (alive) setError(authError(error)) }).finally(() => { if (alive) setProfileLoading(false) })
    return () => { alive = false; controller.abort() }
  }, [retry])

  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setNotice('')
    if (!name.trim()) { setError('请输入昵称。'); return }
    setBusy(true)
    try { const data = await saveProfile(name.trim(), bio.trim()); setProfile(data); setName(data.user.name); setBio(data.bio); setNotice('个人资料已保存。') }
    catch (error) { setError(authError(error)) }
    finally { setBusy(false) }
  }
  async function upload(file?: File) {
    setError(''); setNotice('')
    if (file) { const message = avatarFileError(file); if (message) { setError(message); return } }
    setBusy(true)
    try { await changeAvatar(file); setNotice(file ? '头像已更新。' : '已恢复默认头像。') }
    catch (error) { setError(authError(error)) }
    finally { setBusy(false); if (picker.current) picker.current.value = '' }
  }
  return <div className="page-shell profile-page">
    <div className="profile-heading"><div><span className="eyebrow">我的本草空间</span><h1>个人中心</h1><p>留下每一次探索，回看与本草相遇的记录。</p></div><Link className="text-link" to="/">返回首页 →</Link></div>
    <div className="profile-layout">
      <aside className="paper-card profile-sidebar">
        <div className="profile-avatar-block"><UserAvatar user={user} size={104} /><h2>{user.name}</h2><span className="tag">{user.role === 'admin' ? '管理员' : '平台用户'}</span>
          <div className="profile-avatar-actions"><button type="button" disabled={busy} onClick={() => picker.current?.click()}>更换头像</button>{user.avatar_url && <button type="button" disabled={busy} onClick={() => void upload()}>恢复默认</button>}</div>
          <input ref={picker} type="file" hidden aria-label="选择新头像" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file) }} />
          <small>JPG / PNG / WEBP，最大 2MB<br />图片将居中裁剪为正方形</small>
        </div>
        {notice && <p className="form-success" role="status">{notice}</p>}{error && <p className="form-error" role="alert">{error}</p>}
        {profileLoading ? <p className="profile-muted">正在读取个人资料…</p> : profile ? <>
          <dl className="profile-facts"><div><dt>登录账号</dt><dd>{user.account}</dd></div><div><dt>加入时间</dt><dd>{dateLabel(profile.created_at)}</dd></div></dl>
          <form className="profile-form" onSubmit={event => void submit(event)}><h3>个人信息</h3>
            <label>昵称<input value={name} maxLength={80} autoComplete="nickname" disabled={busy} onChange={event => setName(event.target.value)} required /></label>
            <label>个人简介<textarea value={bio} maxLength={300} rows={4} placeholder="介绍一下自己与植物的故事" disabled={busy} onChange={event => setBio(event.target.value)} /><small>{bio.length} / 300</small></label>
            <button className="button button-primary" disabled={busy}>{busy ? '正在保存…' : '保存资料'}</button>
          </form></> : <button className="button button-light" onClick={() => setRetry(value => value + 1)}>重新加载资料</button>}
      </aside>
      <section className="profile-main">
        <div className="profile-stats"><div className="paper-card"><span>AI 对话</span><strong>{profile?.stats.conversations ?? '—'}<small> 段</small></strong><p>你的本草问答记录</p></div><div className="paper-card"><span>图片识别</span><strong>{profile?.stats.recognitions ?? '—'}<small> 次</small></strong><p>从一张照片开始认识植物</p></div></div>
        <PersonalHistory />
      </section>
    </div>
  </div>
}

function PersonalHistory() {
  const [tab, setTab] = useState<'chats' | 'images'>('chats')
  const [input, setInput] = useState(''), [query, setQuery] = useState(''), [page, setPage] = useState(1)
  const [chats, setChats] = useState<ChatConversation[]>([]), [images, setImages] = useState<RecognitionRecord[]>([])
  const [total, setTotal] = useState(0), [loading, setLoading] = useState(true), [error, setError] = useState(''), [retry, setRetry] = useState(0)
  useEffect(() => {
    let alive = true
    const controller = new AbortController()
    setLoading(true); setError(''); setChats([]); setImages([])
    const task = tab === 'chats'
      ? loadProfileConversations(query, page, controller.signal).then(data => { if (alive) { setChats(data.items); setTotal(data.total) } })
      : loadRecognitionHistory(query, page, controller.signal).then(data => { if (alive) { setImages(data.items); setTotal(data.total) } })
    void task.catch(error => { if (alive) setError(historyError(error)) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false; controller.abort() }
  }, [tab, query, page, retry])
  function switchTab(next: typeof tab) { setTab(next); setInput(''); setQuery(''); setPage(1) }
  return <section className="paper-card profile-history">
    <div className="profile-history-heading"><h2>我的记录</h2><span>仅当前账号可见</span></div>
    <div className="profile-tabs" role="tablist" aria-label="历史记录分类"><button id="profile-tab-chats" role="tab" aria-selected={tab === 'chats'} aria-controls="profile-records" onClick={() => switchTab('chats')}>AI 对话记录</button><button id="profile-tab-images" role="tab" aria-selected={tab === 'images'} aria-controls="profile-records" onClick={() => switchTab('images')}>图片识别记录</button></div>
    <form className="profile-search" onSubmit={event => { event.preventDefault(); setQuery(input.trim()); setPage(1); setRetry(value => value + 1) }}><input aria-label="搜索我的记录" placeholder={tab === 'chats' ? '搜索对话标题或内容' : '搜索植物名称或图片文件名'} value={input} maxLength={200} onChange={event => setInput(event.target.value)} /><button className="button button-light">搜索</button>{query && <button className="profile-clear" type="button" onClick={() => { setInput(''); setQuery(''); setPage(1) }}>清除</button>}</form>
    <div id="profile-records" role="tabpanel" aria-labelledby={`profile-tab-${tab}`} aria-busy={loading}>
      {loading ? <p className="loading-box">正在读取记录…</p> : error ? <div className="profile-record-error"><p role="alert">{error}</p><button className="button button-light" onClick={() => setRetry(value => value + 1)}>重新加载记录</button></div> : total === 0 ? <div className="empty-state"><h3>{query ? '没有找到相关记录' : '还没有这类记录'}</h3><p>{query ? '试试其他关键词。' : '在首页与 AI 聊一聊，或上传一张植物照片。'}</p><Link className="text-link" to="/">去首页探索 →</Link></div> : <>
        <div className="profile-record-list" key={`${tab}-${query}-${page}`}>{tab === 'chats' ? chats.map(chat => <details className="profile-conversation" key={chat.id}><summary><div><strong>{conversationTitle({ ...chat, question: '', pendingQuestion: '', error: '' })}</strong><small>{dateLabel(chat.updatedAt)} · {chat.messages.filter(message => message.role === 'user').length} 条提问</small></div><span>查看对话</span></summary><div className="profile-transcript">{chat.messages.length ? chat.messages.map((message, index) => <article key={index} className={`profile-message profile-message-${message.role}`}><span>{message.role === 'user' ? '我' : '本草助手'}</span>{message.role === 'user' ? <ChatUserMessage message={message} /> : <p>{message.content}</p>}</article>) : <p className="profile-muted">这段对话尚未发送消息。</p>}</div></details>) : images.map(record => <article className="profile-recognition" key={record.id}><ChatMessageImage recordId={record.id} /><div><h3>{record.result.prediction.name}</h3><p className="latin">{record.result.prediction.latin_name}</p><p>模型置信度 {(record.result.prediction.confidence * 100).toFixed(1)}%</p><small>{dateLabel(record.createdAt)}</small><p className="profile-filename" title={record.filename}>{record.filename}</p><details><summary>查看候选结果</summary><ol>{record.result.top_k.map((item, index) => <li key={`${item.herb_id}-${index}`}>{item.name} <span>{(item.confidence * 100).toFixed(1)}%</span></li>)}</ol></details><Link className="text-link" to={`/herbs/${record.result.prediction.herb_id}`}>查看植物资料 →</Link></div></article>)}</div>
        <nav className="profile-pagination" aria-label="历史记录分页"><span>共 {total} 条 · 第 {page} / {Math.max(1, Math.ceil(total / 8))} 页</span><div><button type="button" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><button type="button" disabled={page * 8 >= total} onClick={() => setPage(value => value + 1)}>下一页</button></div></nav>
      </>}
    </div>
  </section>
}
