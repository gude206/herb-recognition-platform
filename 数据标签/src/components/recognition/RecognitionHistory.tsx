import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Clock3, Image, LoaderCircle, RefreshCw, Search } from 'lucide-react'
import { historyError, loadRecognitionHistory, loadRecognitionImage } from '../../api/history'
import type { HistoryPage, RecognitionRecord } from '../../api/history'
import { useAccountSession } from '../../api/session'

export function RecognitionHistory({ onSelect }: { onSelect: (record: RecognitionRecord, image: Blob) => void }) {
  const account = useAccountSession()
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [records, setRecords] = useState<HistoryPage<RecognitionRecord>>()
  const [loading, setLoading] = useState(true)
  const [opening, setOpening] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!account.ready) return
    let alive = true
    setLoading(true)
    const timer = setTimeout(() => {
      void loadRecognitionHistory(query, page).then(data => {
        if (alive) { setRecords(data); setError('') }
      }).catch(error => { if (alive) setError(historyError(error)) })
        .finally(() => { if (alive) setLoading(false) })
    }, 200)
    return () => { alive = false; clearTimeout(timer) }
  }, [query, page, refresh, account.ready, account.user?.id])

  const open = async (record: RecognitionRecord) => {
    setOpening(record.id)
    try {
      const image = await loadRecognitionImage(record.id)
      onSelect(record, image)
    } catch (error) { setError(historyError(error)) }
    finally { setOpening('') }
  }

  return <section className="recognition-history" aria-label="图片识别历史记录">
    <div className="recognition-history-toolbar"><div className="chat-history-search"><Search size={16} />
      <input aria-label="搜索识别记录" placeholder="搜索植物名称或图片文件名" value={query}
        onChange={event => { setQuery(event.target.value); setPage(1) }} /></div>
      <button type="button" className="chat-action" aria-label="刷新识别记录" disabled={loading}
        onClick={() => setRefresh(value => value + 1)}><RefreshCw size={16} className={loading ? 'spin' : ''} /></button></div>
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="recognition-history-list" aria-busy={loading}>
      {loading ? <div className="chat-history-empty"><LoaderCircle size={25} className="spin" /><p>正在读取 MySQL 识别记录…</p></div>
        : records?.items.map(record => <button type="button" className="recognition-history-item" key={record.id}
          disabled={!!opening} onClick={() => void open(record)}>
          {opening === record.id ? <LoaderCircle size={19} className="spin" /> : <Image size={19} />}
          <span><strong>{record.result.prediction.name}<small>{(record.result.prediction.confidence * 100).toFixed(1)}% 模型分数</small></strong>
            <span className="recognition-history-filename">{record.filename}</span>
            <time dateTime={new Date(record.createdAt).toISOString()}>{new Date(record.createdAt).toLocaleString('zh-CN')}</time></span>
          <ChevronRight size={16} />
        </button>)}
      {!loading && !error && !records?.items.length && <div className="chat-history-empty"><Clock3 size={28} /><strong>{query ? '没有匹配的识别记录' : '还没有识别记录'}</strong><p>成功识别图片后会自动保存，点击记录可查看原图和结果。</p></div>}
    </div>
    {!!records?.total && <div className="recognition-history-pagination"><span>共 {records.total} 条 · 第 {page} 页</span>
      <button type="button" className="chat-action" aria-label="上一页识别记录" disabled={loading || page === 1} onClick={() => setPage(page - 1)}><ChevronLeft size={17} /></button>
      <button type="button" className="chat-action" aria-label="下一页识别记录" disabled={loading || page * records.page_size >= records.total} onClick={() => setPage(page + 1)}><ChevronRight size={17} /></button></div>}
    <p className="chat-storage-note">记录由后端 MySQL 保存；原图保存在服务器本地，{account.user ? '仅当前账号可以读取。' : '登录时可将访客记录关联到账号。'}</p>
  </section>
}
