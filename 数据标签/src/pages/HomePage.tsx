import { useEffect, useRef, useState } from 'react'
import { ArrowRight, BookOpen, Bot, Camera, Check, Leaf, MessageCircle, Send } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getHerb } from '../api/herb'
import { PlantImage } from '../components/herb/PlantImage'
import { IdentityWarning } from '../components/herb/HerbIdentity'
import type { Herb } from '../types/herb'
import { ImageUploader } from '../components/recognition/ImageUploader'
import { RecognitionResult } from '../components/recognition/RecognitionResult'
import { RecentViewed } from '../components/herb/RecentViewed'
import { SectionTitle } from '../components/common/SectionTitle'
import { useHerbChat } from '../hooks/useHerbChat'
import type { RecognitionResult as ResultType } from '../types/recognition'

export function HomePage() {
 const [result,setResult]=useState<ResultType>();const [preview,setPreview]=useState('')
 const {question,setQuestion,pendingQuestion:lastQuestion,loading:chatLoading,messages:chatMessages,error:chatError,ask}=useHerbChat(result?.prediction.herb_id)
 const chatBody=useRef<HTMLDivElement>(null)
 const [knowledgeHerb,setKnowledgeHerb]=useState<Herb>()
 const knowledgeId=result?.prediction.herb_id || 'tcmp-004'
 useEffect(()=>{let alive=true;setKnowledgeHerb(undefined);void getHerb(knowledgeId).then(h=>{if(alive)setKnowledgeHerb(h)}).catch(()=>{});return()=>{alive=false}},[knowledgeId])
 useEffect(()=>{if(chatBody.current)chatBody.current.scrollTop=chatBody.current.scrollHeight},[chatMessages,chatLoading,chatError])
 return <div className="page-shell home-page">
  <section className="home-hero"><div className="home-hero-copy"><span className="eyebrow"><span className="eyebrow-dot"/>识本草 · 传文化 · 智未来</span><h1>看图识本草，<br/><em>智能问药理</em></h1><h2>基于人工智能的中草药识别、知识问答与科普平台</h2><p>融合图像识别与大语言模型，提供中草药识别、药材知识查询、智能问答等功能，<br className="wide-break"/>让传统中医药知识触手可及。</p><div className="feature-links">{[[Camera,'拍照识别','快速识别中草药','/','#recognize'],[BookOpen,'图鉴查询','细览本草知识','/herbs',''],[MessageCircle,'知识问答','专业知识检索','/','#assistant']].map(([Icon,title,sub,to,hash])=>{const I=Icon as typeof Leaf;return <Link to={`${to}${hash}`} key={String(title)}><span><I size={20}/></span><b>{String(title)}<small>{String(sub)}</small></b></Link>})}</div></div><div className="home-hero-art"><div className="art-sun"/><div className="art-label">本草<br/>纲目</div><div className="art-calligraphy">传承本草<br/>智启未来</div></div></section>
  <section className="home-workspace" id="recognize"><div className="paper-card upload-card"><SectionTitle icon={<Leaf/>} title="草药识别" sub="上传植物图片，快速识别中草药，获取详细的草药信息"/><ImageUploader onStart={()=>{setResult(undefined);setPreview('')}} onResult={(value,image)=>{setResult(value);setPreview(image)}}/></div><RecognitionResult result={result} preview={preview}/><RecentViewed/></section>
  <section className="home-detail-grid"><div className="paper-card knowledge-card"><SectionTitle icon={<BookOpen/>} title="草药知识" sub="查看活体植物的形态、分布与来源资料" action={knowledgeHerb&&<Link to={`/herbs/${knowledgeHerb.id}`} className="pill-link">查看完整资料 <ArrowRight size={14}/></Link>}/>{(()=>{const herb=knowledgeHerb;if(!herb)return <div className="knowledge-pending"><strong>{result?.prediction.name}</strong><p className="latin">{result?.prediction.latin_name}</p><p>科属：{result?.prediction.family||'待补充'}</p><p>植物资料正在加载；若服务暂时不可用，可从图鉴入口重试。</p>{result&&<Link className="text-link" to={'/herbs/'+result.prediction.herb_id}>打开植物详情 →</Link>}</div>;return <div className="knowledge-preview"><PlantImage herb={herb}/><div><h3>{herb.name}<span className="tag">{herb.identityConflict ? '身份待核实' : '活体植物'}</span></h3>{herb.identityConflict && <IdentityWarning className="prediction-warning"/>}<p className="latin">{herb.latinName}</p><dl><dt>科属</dt><dd>{herb.family} / {herb.genus || '暂无可靠资料'}</dd><dt>分布</dt><dd>{herb.distribution || '暂无可靠资料'}</dd><dt>形态</dt><dd>{herb.growthForm || '暂无可靠资料'}</dd><dt>简介</dt><dd>{herb.description}</dd></dl></div></div>})()}</div>
   <div className="paper-card assistant-card" id="assistant">
    <SectionTitle icon={<Bot/>} title="AI 中医药助手" sub="由 DeepSeek 提供问答，同一植物的对话单独保存"/>
    <p className="chat-context" role="status">当前参考：{result ? <><strong>{result.prediction.name}</strong> · {result.prediction.identity_conflict ? '身份冲突，待核实' : '模型候选，待核实'}</> : '通用本草知识（尚未选择植物）'}<small>切换植物后显示对应会话；原会话的回答仍保存在原植物下。</small></p>
    <div className="chat-body" ref={chatBody} aria-label="问答记录" aria-busy={chatLoading}>
     <div className="chat-bubble assistant-bubble"><span className="bot-avatar"><Bot size={20}/></span><div>您好！我是草药助手，能够为您介绍中草药的植物形态、知识库条目与本草文化。<br/>请问您想了解什么？<small>本助手用于知识科普，不提供诊断或用药建议。</small></div></div>
     {chatMessages.map((item,index)=>item.role==='user'?<div className="chat-bubble user-bubble" key={index}>{item.content}</div>:<div className="chat-bubble assistant-bubble" key={index}><span className="bot-avatar"><Bot size={20}/></span><div>{item.content}</div></div>)}
     {chatLoading&&<><div className="chat-bubble user-bubble">{lastQuestion}</div><div className="chat-bubble assistant-bubble" role="status"><span className="bot-avatar"><Bot size={20}/></span><div className="typing">正在整理本草知识…</div></div></>}
     {chatError&&<p className="chat-error" role="alert">{chatError}</p>}
    </div>
    <div className="prompt-chips">{['金银花的植物特征是什么？','黄芪有哪些传统记载？','如何识别常见本草？'].map(item=><button key={item} disabled={chatLoading} onClick={()=>void ask(item)}>{item}</button>)}</div>
    <form className="chat-input" onSubmit={event=>{event.preventDefault();void ask()}}><input value={question} onChange={event=>setQuestion(event.target.value)} maxLength={2000} disabled={chatLoading} placeholder="请输入您想了解的中草药问题…" aria-label="输入问题"/><button aria-label="发送问题" disabled={chatLoading||!question.trim()}><Send size={17}/></button></form>
   </div>
  </section>
  <section className="home-bottom-note"><span><Check size={16}/> 植物识别与知识科普</span><span><Check size={16}/> 数据与模型持续完善</span><span><Check size={16}/> 传统文化数字化传承</span></section>
 </div>
}
