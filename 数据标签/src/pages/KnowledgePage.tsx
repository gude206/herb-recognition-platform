import { useEffect, useRef, useState } from 'react'
import { ArrowRight, BookOpen, Flame, Flower2, Leaf, ScrollText, ShieldCheck, Sun, X } from 'lucide-react'
import { PageHero } from '../components/common/PageHero'
import { SectionTitle } from '../components/common/SectionTitle'
import { getArticle, getArticles, knowledgeError } from '../api/knowledge'
import type { Article } from '../types/article'
import { PhotoCredit } from '../components/common/PhotoCredit'

const categories=[['本草故事',ScrollText],['植物知识',Leaf],['节气养生',Sun],['药食同源',Flower2],['名医典故',BookOpen],['安全常识',ShieldCheck]] as const
export function KnowledgePage() {
 const [articles,setArticles]=useState<Article[]>([]);const [category,setCategory]=useState('全部');const [active,setActive]=useState<Article>()
 const [loading,setLoading]=useState(true);const [error,setError]=useState('');const [retry,setRetry]=useState(0)
 const [detailLoading,setDetailLoading]=useState(false);const [detailError,setDetailError]=useState('');const detailRequest=useRef(0)
 useEffect(()=>{let alive=true;setLoading(true);setError('');void getArticles().then(items=>{if(alive)setArticles(items)}).catch(error=>{if(alive)setError(knowledgeError(error))}).finally(()=>{if(alive)setLoading(false)});return()=>{alive=false}},[retry])
 useEffect(()=>()=>{detailRequest.current++},[])
 const closeArticle=()=>{detailRequest.current++;setActive(undefined);setDetailLoading(false);setDetailError('')}
 const openArticle=async(article:Article)=>{const requestId=++detailRequest.current;setActive({...article,body:''});setDetailLoading(true);setDetailError('');try{const detail=await getArticle(article.id);if(detailRequest.current===requestId){if(detail)setActive(detail);else setDetailError('未找到这篇已发布文章。')}}catch(error){if(detailRequest.current===requestId)setDetailError(knowledgeError(error))}finally{if(detailRequest.current===requestId)setDetailLoading(false)}}
 const selected=category==='全部'?articles:articles.filter(item=>item.category===category||category==='草药背景'&&item.category==='植物知识')
 const featured=articles[0]
 const shownCategories=categories.filter(([name])=>articles.some(article=>article.category===name||(name==='植物知识'&&article.category==='草药背景')))
 return <div className="page-shell knowledge-page"><PageHero eyebrow="本草文化 · 科普阅读" title="本草科普" subtitle="观察身边的草木，读懂植物的结构与季节变化。以植物志为依据，用清晰的文字连接真实照片与科学知识。" variant="library"/>
  {!!shownCategories.length&&<div className="knowledge-categories">{shownCategories.map(([name,Icon])=><button key={name} className={category===name?'active':''} onClick={()=>setCategory(category===name?'全部':name)}><span><Icon size={21}/></span><b>{name}</b><small>探索本草知识</small><ArrowRight size={15}/></button>)}</div>}
  <div className={'knowledge-layout'+(!articles.length?' knowledge-layout-empty':'')}><div className="knowledge-main">{featured&&<section className="paper-card featured-article"><img src={featured.image} alt={featured.title}/><div className="featured-copy"><PhotoCredit credit={featured.imageCredit} linked/><span className="eyebrow">今日推荐 · {featured.category}</span><h2>{featured.title}</h2><div className="tag-row"><span className="tag">{featured.category}</span></div><p>{featured.excerpt}</p><button className="button button-primary" onClick={()=>void openArticle(featured)}>阅读全文 <ArrowRight size={16}/></button></div><div className="featured-seal">今日<br/>推荐</div></section>}
   <section className="paper-card article-library"><SectionTitle icon={<BookOpen/>} title="科普文章" sub="阅读有据可查的植物知识与本草文化" action={<div className="article-tabs"><button className={category==='全部'?'active':''} onClick={()=>setCategory('全部')}>全部</button>{shownCategories.slice(0,5).map(([name])=><button className={category===name?'active':''} key={name} onClick={()=>setCategory(name)}>{name}</button>)}</div>}/>{loading&&<div className="loading-box" role="status">正在加载科普文章…</div>}{error&&<div className="empty-state" role="alert"><p>{error}</p><button className="button button-light" onClick={()=>setRetry(value=>value+1)}>重新加载科普文章</button></div>}<div className="article-grid">{selected.map(article=><button className="article-card" key={article.id} onClick={()=>void openArticle(article)}><img src={article.image} alt={article.title}/><div><PhotoCredit credit={article.imageCredit}/><span className="tag">{article.category}</span><h3>{article.title}</h3><p>{article.excerpt}</p><span className="article-read">阅读全文 <ArrowRight size={14}/></span></div></button>)}</div>{!loading&&!error&&!selected.length&&<div className="empty-state">{category==='全部'?'暂无已发布的科普文章。':'该专题暂无已发布文章。'}</div>}</section>
  </div>{!!articles.length&&<aside className="knowledge-aside"><section className="paper-card reading-list"><SectionTitle icon={<Flame/>} title="推荐阅读"/>{articles.slice(0,5).map((article,index)=><button key={article.id} onClick={()=>void openArticle(article)}><b className={`rank rank-${index+1}`}>{index+1}</b><img src={article.image} alt=""/><span><strong>{article.title}</strong><small>{article.category}</small></span></button>)}</section><section className="paper-card special-topics"><SectionTitle icon={<BookOpen/>} title="科普专题"/>{shownCategories.map(([name])=><button key={name} onClick={()=>setCategory(name)}><span><b>{name}</b><small>阅读{articles.filter(a=>a.category===name).length}篇科普文章</small></span><ArrowRight/></button>)}</section></aside>}</div>

  {active&&<div className="modal-backdrop" role="presentation" onClick={closeArticle}><article className="article-modal paper-card" role="dialog" aria-modal="true" aria-label={active.title} onClick={event=>event.stopPropagation()}><button className="modal-close" onClick={closeArticle} aria-label="关闭"><X/></button><img src={active.image} alt={active.title+'配图'}/><PhotoCredit credit={active.imageCredit} linked/><span className="eyebrow">{active.category} · 本草科普</span><h2>{active.title}</h2><p className="article-source-note">{active.sourceNote?.split('\n')[0]}</p><p className="article-modal-lead">{active.excerpt}</p>{detailLoading?<p role="status">正在读取文章正文…</p>:detailError?<div role="alert"><p className="form-error">{detailError}</p><button className="button button-light" onClick={()=>void openArticle(active)}>重试读取正文</button></div>:<ArticleBody body={active.body}/>}<ArticleSources note={active.sourceNote}/><p className="article-scope-note">本平台提供植物知识科普，内容以所列来源为依据，不作为采食或用药依据。</p></article></div>}
 </div>
}


function ArticleBody({body}:{body:string}) {
  return <div className="editorial-article-body">{body.split('\n\n').filter(Boolean).map((block,index)=>{
    const lines=block.split('\n')
    return lines.length>1 ? <section key={index}><h3>{lines[0]}</h3><p>{lines.slice(1).join('\n')}</p></section> : <p key={index}>{block}</p>
  })}</div>
}

function ArticleSources({note}:{note?:string}) {
  const sources=(note||'').split('\n').flatMap(line=>{
    const match=line.match(/https?:\/\/[^\s]+/)
    return match ? [{url:match[0],name:line.slice(0,match.index).trim()||'参考资料'}] : []
  })
  if(!sources.length)return null
  return <section className="article-references"><h3>参考资料</h3><ol>{sources.map(source=><li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.name}</a></li>)}</ol></section>
}
