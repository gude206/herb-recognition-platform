import { useEffect, useRef, useState } from 'react'
import { ArrowRight, BookOpen, Camera, Check, Clock3, Leaf, MessageCircle, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getHerb } from '../api/herb'
import { PlantImage } from '../components/herb/PlantImage'
import type { Herb } from '../types/herb'
import { ImageUploader } from '../components/recognition/ImageUploader'
import { RecognitionHistory } from '../components/recognition/RecognitionHistory'
import type { RecognitionRecord } from '../api/history'
import { RecognitionResult } from '../components/recognition/RecognitionResult'
import { RecentViewed } from '../components/herb/RecentViewed'
import { SectionTitle } from '../components/common/SectionTitle'
import { HerbAssistant } from '../components/chat/HerbAssistant'
import type { RecognitionResult as ResultType } from '../types/recognition'

export function HomePage() {
 const [result,setResult]=useState<ResultType>();const [preview,setPreview]=useState('')
 const [recognitionHistoryOpen,setRecognitionHistoryOpen]=useState(false)
 const [recognitionBusy,setRecognitionBusy]=useState(false)
 const historyPreview=useRef('')
 useEffect(()=>()=>{if(historyPreview.current)URL.revokeObjectURL(historyPreview.current)},[])
 const clearHistoryPreview=()=>{if(historyPreview.current){URL.revokeObjectURL(historyPreview.current);historyPreview.current=''}}
 const restoreRecognition=(record:RecognitionRecord,image:Blob)=>{clearHistoryPreview();const url=URL.createObjectURL(image);historyPreview.current=url;setResult(record.result);setPreview(url);setRecognitionHistoryOpen(false)}
 const [knowledgeHerb,setKnowledgeHerb]=useState<Herb>()
 const knowledgeId=result?.prediction.identity_conflict ? undefined : result?.prediction.herb_id || 'tcmp-298'
 useEffect(()=>{let alive=true;setKnowledgeHerb(undefined);if(!knowledgeId)return;void getHerb(knowledgeId).then(h=>{if(alive)setKnowledgeHerb(h)}).catch(()=>{});return()=>{alive=false}},[knowledgeId])
 return <div className="page-shell home-page">
  <section className="home-hero"><div className="home-hero-copy"><span className="eyebrow"><span className="eyebrow-dot"/>识本草 · 传文化 · 智未来</span><h1>看图识本草，<br/><em>读懂植物</em></h1><h2>基于人工智能的中草药识别、知识问答与科普平台</h2><p>融合图像识别与大语言模型，提供中草药识别、植物知识查询、智能问答等功能，<br className="wide-break"/>让传统中医药知识触手可及。</p><div className="feature-links">{[[Camera,'拍照识别','快速识别中草药','/','#recognize'],[BookOpen,'图鉴查询','细览本草知识','/herbs',''],[MessageCircle,'知识问答','本草知识问答','/','#assistant']].map(([Icon,title,sub,to,hash])=>{const I=Icon as typeof Leaf;return <Link to={`${to}${hash}`} key={String(title)}><span><I size={20}/></span><b>{String(title)}<small>{String(sub)}</small></b></Link>})}</div></div><div className="home-hero-art"><div className="art-sun"/><div className="art-label">本草<br/>纲目</div><div className="art-calligraphy">传承本草<br/>智启未来</div></div></section>
  <section className="home-workspace" id="recognize"><div className="paper-card upload-card"><SectionTitle icon={<Leaf/>} title={recognitionHistoryOpen?'图片识别记录':'草药识别'} sub={recognitionHistoryOpen?'查看后端保存的原图与模型识别结果':'上传植物图片，成功识别后可在历史记录中查看'} action={<button type="button" className="chat-action" aria-label={recognitionHistoryOpen?'返回图片上传':'识别历史记录'} title={recognitionHistoryOpen?'返回图片上传':'识别历史记录'} disabled={recognitionBusy} onClick={()=>setRecognitionHistoryOpen(!recognitionHistoryOpen)}>{recognitionHistoryOpen?<X size={18}/>:<Clock3 size={18}/>}</button>}/>{recognitionHistoryOpen?<RecognitionHistory onSelect={restoreRecognition}/>:<ImageUploader onStart={()=>{clearHistoryPreview();setRecognitionBusy(true);setResult(undefined);setPreview('')}} onFinish={()=>setRecognitionBusy(false)} onResult={(value,image)=>{setResult(value);setPreview(image)}}/>}</div><RecognitionResult result={result} preview={preview}/><RecentViewed/></section>
  <section className="home-detail-grid"><div className="paper-card knowledge-card">
   <SectionTitle icon={<BookOpen/>} title="草药知识" sub="查看有来源的植物形态与分布资料" action={knowledgeHerb&&<Link to={`/herbs/${knowledgeHerb.id}`} className="pill-link">查看完整资料 <ArrowRight size={14}/></Link>}/>
   {knowledgeHerb ? <div className={'knowledge-preview'+(knowledgeHerb.image?'':' knowledge-preview-text')}>
    {knowledgeHerb.image&&<PlantImage herb={knowledgeHerb}/>}
    <div><h3>{knowledgeHerb.name}<span className="tag">活体植物</span></h3><p className="latin">{knowledgeHerb.latinName}</p><dl>
     {(knowledgeHerb.family||knowledgeHerb.genus)&&<><dt>科属</dt><dd>{[knowledgeHerb.family,knowledgeHerb.genus].filter(Boolean).join(' / ')}</dd></>}
     {knowledgeHerb.distribution&&<><dt>分布</dt><dd>{knowledgeHerb.distribution}</dd></>}
     {knowledgeHerb.growthForm&&<><dt>形态</dt><dd>{knowledgeHerb.growthForm}</dd></>}
    </dl></div></div> : <div className="knowledge-pending"><p>{result?.prediction.identity_conflict?'本次结果无法确定植物名称，暂不提供对应的植物资料。':'正在读取植物资料，暂时无法读取时可从图鉴入口重试。'}</p><Link className="text-link" to="/herbs">浏览草药图鉴</Link></div>}
  </div><HerbAssistant context={result&&!result.prediction.identity_conflict ? {herbId:result.prediction.herb_id,name:result.prediction.name} : undefined}/></section>
  <section className="home-bottom-note"><span><Check size={16}/> 植物识别与知识科普</span><span><Check size={16}/> 数据与模型持续完善</span><span><Check size={16}/> 传统文化数字化传承</span></section>
 </div>
}
