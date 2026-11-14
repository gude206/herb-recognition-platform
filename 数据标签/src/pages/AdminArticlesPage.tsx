import { useEffect, useRef, useState, type FormEvent } from 'react'
import { BookOpen, ChevronLeft, ChevronRight, Edit3, Plus, RefreshCw, Search, Trash2, Undo2, Upload, X } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { authError } from '../api/auth'
import { useAccountSession } from '../api/session'
import { deleteAdminArticle, getAdminArticle, getAdminArticles, restoreAdminArticle, saveAdminArticle, uploadAdminCover } from '../api/adminArticles'
import type { AdminArticle, AdminArticlePage, ArticleForm } from '../api/adminArticles'

const blankForm = (): ArticleForm => ({ title:'', category:'植物知识', excerpt:'', body:'', status:'draft', reviewStatus:'未审核', sourceKind:'editorial', sourceNote:'', displayOrder:100 })
const formFor = (article: AdminArticle): ArticleForm => ({ title:article.title, category:article.category, excerpt:article.excerpt, body:article.body,
  status:article.status || 'draft', reviewStatus:article.reviewStatus || '未审核', sourceKind:article.sourceKind === 'course_example' ? 'course_example' : 'editorial', sourceNote:article.sourceNote || '', displayOrder:article.displayOrder })

export function AdminArticlesPage() {
 const session = useAccountSession(); const navigate = useNavigate()
 const [q,setQ]=useState('');const [status,setStatus]=useState('all');const [page,setPage]=useState(1);const [refresh,setRefresh]=useState(0)
 const [data,setData]=useState<AdminArticlePage>();const [loading,setLoading]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('')
 const [editing,setEditing]=useState(false);const [article,setArticle]=useState<AdminArticle>();const [form,setForm]=useState<ArticleForm>(blankForm)
 const [busy,setBusy]=useState(false);const [cover,setCover]=useState<File>();const editorRequest=useRef(0)

 useEffect(()=>{if(session.ready&&session.user?.role!=='admin')navigate('/login?role=admin&next=%2Fadmin%2Farticles',{replace:true})},[session.ready,session.user?.role,navigate])
 useEffect(()=>{
  if(session.user?.role!=='admin')return
  let alive=true;setLoading(true)
  const timer=setTimeout(()=>{void getAdminArticles(q,status,page).then(result=>{if(alive){setData(result);setError('')}}).catch(error=>{if(alive)setError(authError(error))}).finally(()=>{if(alive)setLoading(false)})},200)
  return()=>{alive=false;clearTimeout(timer)}
 },[q,status,page,refresh,session.user?.id,session.user?.role])
 useEffect(()=>()=>{editorRequest.current++},[])
 if(!session.ready||session.user?.role!=='admin')return <div className="loading-box">正在验证管理员登录…</div>

 const reload=()=>setRefresh(value=>value+1)
 const closeEditor=()=>{if(busy)return;editorRequest.current++;setEditing(false);setArticle(undefined);setCover(undefined)}
 const create=()=>{editorRequest.current++;setArticle(undefined);setForm(blankForm());setCover(undefined);setError('');setNotice('');setEditing(true)}
 const edit=async(item:AdminArticle)=>{const request=++editorRequest.current;setBusy(true);setError('');try{const current=await getAdminArticle(item.id);if(request===editorRequest.current){setArticle(current);setForm(formFor(current));setCover(undefined);setEditing(true)}}catch(error){setError(authError(error))}finally{if(request===editorRequest.current)setBusy(false)}}
 const save=async(event:FormEvent)=>{
  event.preventDefault();setBusy(true);setError('');setNotice('')
  try{
   let saved=await saveAdminArticle(form,article)
   setArticle(saved)
   if(cover){
    try{saved=await uploadAdminCover(saved,cover);setCover(undefined)}catch(error){setError('文章已保存，但封面上传未成功：'+authError(error));setArticle(saved);reload();return}
   }
   setArticle(saved);setForm(formFor(saved));setNotice(saved.status==='published'?'文章已保存并发布。':'草稿已保存。');reload()
  }catch(error){setError(authError(error))}finally{setBusy(false)}
 }
 const remove=async(item:AdminArticle)=>{if(!window.confirm('将“'+item.title+'”移入回收站？可在回收站恢复。'))return;setBusy(true);setError('');try{await deleteAdminArticle(item);setNotice('文章已移入回收站。');reload()}catch(error){setError(authError(error))}finally{setBusy(false)}}
 const restore=async(item:AdminArticle)=>{setBusy(true);setError('');try{await restoreAdminArticle(item);setNotice('文章已恢复为草稿。');reload()}catch(error){setError(authError(error))}finally{setBusy(false)}}

 return <div className="page-shell admin-articles-page"><div className="admin-page-heading"><div><span className="eyebrow">管理员工作区</span><h1><BookOpen size={25}/>文章维护</h1><p>管理科普文章、封面、发布状态与资料来源。</p></div><div><Link className="button button-light" to="/knowledge">查看科普页面</Link><button type="button" className="button button-primary" disabled={busy} onClick={create}><Plus size={17}/>新增文章</button></div></div>
 {notice&&<p className="form-success" role="status">{notice}</p>}{error&&<p className="form-error admin-error" role="alert">{error}</p>}
 <section className="paper-card admin-article-library"><div className="admin-toolbar"><div className="chat-history-search"><Search size={16}/><input aria-label="搜索管理员文章" value={q} maxLength={200} placeholder="搜索标题或分类" onChange={event=>{setQ(event.target.value);setPage(1)}}/></div><select aria-label="文章发布状态筛选" value={status} onChange={event=>{setStatus(event.target.value);setPage(1)}}><option value="all">全部文章</option><option value="draft">草稿</option><option value="published">已发布</option><option value="deleted">回收站</option></select><button className="chat-action" type="button" aria-label="刷新管理员文章" disabled={loading} onClick={reload}><RefreshCw size={17} className={loading?'spin':''}/></button></div>
 {loading?<div className="loading-box" role="status">正在读取文章…</div>:<div className="admin-article-list">{data?.items.map(item=><article className="admin-article-row" key={item.id}><div><h3>{item.title}</h3><p>{item.category} · {item.deleted?'回收站':item.status==='published'?'已发布':'草稿'} · {item.reviewStatus}</p><small>更新：{item.updatedAt?new Date(item.updatedAt).toLocaleString('zh-CN'):'—'}</small></div><div className="admin-row-actions">{item.deleted?<button type="button" className="button button-light" disabled={busy} onClick={()=>void restore(item)}><Undo2 size={15}/>恢复为草稿</button>:<><button type="button" className="button button-light" disabled={busy} onClick={()=>void edit(item)}><Edit3 size={15}/>编辑</button><button type="button" className="button admin-danger" disabled={busy} onClick={()=>void remove(item)}><Trash2 size={15}/>移入回收站</button></>}</div></article>)}{!data?.items.length&&<div className="empty-state">没有匹配的文章。</div>}</div>}
 {data&&<div className="admin-pagination"><span>共 {data.total} 篇 · 第 {page} 页</span><button type="button" className="chat-action" aria-label="上一页管理员文章" disabled={loading||page===1} onClick={()=>setPage(page-1)}><ChevronLeft size={17}/></button><button type="button" className="chat-action" aria-label="下一页管理员文章" disabled={loading||page*data.pageSize>=data.total} onClick={()=>setPage(page+1)}><ChevronRight size={17}/></button></div>}</section>
 {editing&&<div className="modal-backdrop admin-editor-backdrop" role="presentation"><section className="paper-card admin-editor" role="dialog" aria-modal="true" aria-label={article?'编辑科普文章':'新增科普文章'}><div className="admin-editor-heading"><h2>{article?'编辑科普文章':'新增科普文章'}</h2><button type="button" className="chat-action" aria-label="关闭文章编辑" disabled={busy} onClick={closeEditor}><X size={19}/></button></div>
 {error&&<p className="form-error" role="alert">{error}</p>}{notice&&<p className="form-success" role="status">{notice}</p>}
 <form onSubmit={event=>void save(event)}><label>标题<input aria-label="文章标题" value={form.title} maxLength={255} required disabled={busy} onChange={event=>setForm({...form,title:event.target.value})}/></label><div className="admin-form-grid"><label>分类<input aria-label="文章分类" value={form.category} maxLength={64} required disabled={busy} onChange={event=>setForm({...form,category:event.target.value})}/></label><label>排序<input aria-label="文章排序" type="number" min={0} max={100000} value={form.displayOrder} disabled={busy} onChange={event=>setForm({...form,displayOrder:Number(event.target.value)})}/></label><label>发布状态<select aria-label="文章发布状态" value={form.status} disabled={busy} onChange={event=>setForm({...form,status:event.target.value as ArticleForm['status']})}><option value="draft">草稿</option><option value="published">已发布</option></select></label><label>审核状态<select aria-label="文章审核状态" value={form.reviewStatus} disabled={busy} onChange={event=>setForm({...form,reviewStatus:event.target.value})}><option value="未审核">未审核</option><option value="已审核">已审核</option><option value="待修订">待修订</option></select></label></div>
 <label>摘要<textarea aria-label="文章摘要" rows={2} value={form.excerpt} maxLength={4000} disabled={busy} onChange={event=>setForm({...form,excerpt:event.target.value})}/></label><label>正文<textarea aria-label="文章正文" className="admin-body-input" rows={10} value={form.body} maxLength={80000} disabled={busy} onChange={event=>setForm({...form,body:event.target.value})}/></label>
 <div className="admin-form-grid"><label>内容类型<select aria-label="文章内容类型" value={form.sourceKind} disabled={busy} onChange={event=>setForm({...form,sourceKind:event.target.value as ArticleForm['sourceKind']})}><option value="editorial">科普文章</option><option value="course_example">归档示例（不可发布）</option></select></label><label>封面图片<input aria-label="文章封面文件" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event=>{const file=event.target.files?.[0];if(file&&file.size>5*1024*1024){setError('封面图片不得超过 5MB');event.target.value='';return}setCover(file)}}/><small>JPG、PNG、WEBP，最大 5MB。</small></label></div>
 {article?.image&&<img className="admin-cover-preview" src={article.image} alt="当前文章封面"/>}<p className="auth-help">公开发布前需完成审核并填写公开来源链接；归档示例和含待核验内容的文章仅能保存为草稿。</p><label>资料来源与说明<textarea aria-label="文章资料来源" rows={2} value={form.sourceNote} maxLength={4000} disabled={busy} onChange={event=>setForm({...form,sourceNote:event.target.value})}/></label><div className="admin-editor-footer"><button className="button button-light" type="button" disabled={busy} onClick={closeEditor}>关闭</button><button className="button button-primary" disabled={busy}>{busy?'正在保存…':form.status==='published'?'保存并发布':'保存草稿'}{cover&&<Upload size={15}/>}</button></div></form></section></div>}
 </div>
}
