import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ArrowLeft, BookOpen, MapPin, Sprout } from 'lucide-react'
import { PageHero } from '../components/common/PageHero'
import { HerbCard } from '../components/herb/HerbCard'
import { PlantImage } from '../components/herb/PlantImage'
import { HerbLatinNames } from '../components/herb/HerbIdentity'
import { getHerb, getHerbs } from '../api/herb'
import { addRecentHerb } from '../utils/history'
import type { Herb } from '../types/herb'
import { returnToFromState } from '../utils/atlasNavigation'

const safeURL = (value: string) => /^https?:\/\//i.test(value)

export function HerbDetailPage() {
  const {id=''} = useParams()
  const location = useLocation()
  const returnTo = returnToFromState(location.state)
  const [herb,setHerb] = useState<Herb>(), [related,setRelated] = useState<Herb[]>([])
  const [loading,setLoading] = useState(true), [error,setError] = useState(''), [retry,setRetry] = useState(0)
  useEffect(() => {
    let alive=true; setLoading(true); setHerb(undefined); setRelated([]); setError('')
    void getHerb(id).then(value => {
      if(!alive)return
      setHerb(value)
      if(value){
        addRecentHerb(value.id)
        if(value.family)void getHerbs({family:value.family,page_size:5}).then(list => {
          if(alive)setRelated(list.items.filter(h => h.id!==value.id).slice(0,4))
        }).catch(() => {})
      }
    }).catch((reason: {response?: {status: number}}) => {
      if(alive)setError(reason.response?.status===404 ? '未找到这个植物条目。' : '植物资料加载失败，请确认数据服务已启动后重试。')
    }).finally(() => {if(alive)setLoading(false)})
    return () => {alive=false}
  },[id,retry])
  if(loading)return <div className="page-shell loading-box" role="status">正在打开植物资料…</div>
  if(!herb)return <div className="page-shell empty-state paper-card" role="alert"><h2>{error || '未找到这株植物'}</h2><button className="button button-light" onClick={() => setRetry(v => v+1)}>重试</button> <Link to={returnTo} className="button button-primary">返回草药图鉴</Link></div>
  return <div className="page-shell detail-page">
    <PageHero eyebrow="本草档案 · 活体植物" title={herb.name} subtitle={herb.latinName} variant="garden"/>
    <div className="detail-back"><Link to={returnTo}><ArrowLeft size={15}/>返回草药图鉴</Link><span>类别 {herb.classId ?? '—'} · {herb.id}</span></div>
    <div className="atlas-detail-layout"><div className="detail-main">
     <section className={'paper-card detail-overview'+(herb.image?'':' detail-overview-text')}>
      {herb.image&&<PlantImage herb={herb} className="detail-image" creditLinks/>}
      <div className="detail-intro">{herb.family&&<span className="eyebrow">{herb.family}</span>}<h2>{herb.name}</h2><p className="latin">{herb.latinName}</p>{herb.description&&<p>{herb.description}</p>}</div>
     </section>
     {herb.curated&&herb.completeIntroduction&&<section className="paper-card atlas-section editorial-introduction"><h3>认识{herb.name}</h3>{herb.completeIntroduction.split('\n\n').map((paragraph,index)=><p key={index}>{paragraph}</p>)}</section>}
     <section className="paper-card atlas-section"><h3><BookOpen size={19}/>植物身份</h3><dl className="atlas-dl">
      <HerbLatinNames herb={herb}/>
      {!!herb.aliases.length&&<><dt>植物别名</dt><dd>{herb.aliases.join('、')}</dd></>}
      {(herb.family||herb.genus)&&<><dt>科 / 属</dt><dd>{[herb.family,herb.genus].filter(Boolean).join(' / ')}</dd></>}
      {herb.taxonomySystem&&<><dt>分类来源</dt><dd>{herb.taxonomySystem}</dd></>}
     </dl></section>
     {[herb.distribution,herb.habitat,herb.elevation,herb.flowering,herb.fruiting,herb.sporeSeason].some(Boolean)&&
      <section className="paper-card atlas-section" id="distribution"><h3><MapPin size={19}/>分布与生长环境</h3><dl className="atlas-dl">
       {([['分布',herb.distribution],['生境',herb.habitat],['海拔',herb.elevation],['花期',herb.flowering],['果期',herb.fruiting],['孢子期',herb.sporeSeason]] as const).filter(([,value])=>value?.trim()).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl></section>}
     {!!herb.features?.length&&<section className="paper-card atlas-section"><h3><Sprout size={19}/>植物形态</h3><dl className="atlas-dl atlas-features">{herb.features.map(feature=><div key={feature.label}><dt>{feature.label}</dt><dd>{feature.value}</dd></div>)}</dl></section>}
     {!!herb.sources?.length&&<section className="paper-card atlas-section"><h3>资料来源</h3>{herb.updatedAt&&<p className="atlas-muted">资料日期：{herb.updatedAt}</p>}
      <ul className="atlas-sources">{herb.sources.filter(source=>safeURL(source.url)).map(source=><li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.name}</a></li>)}</ul>
     </section>}
    </div><aside className="paper-card atlas-guide atlas-detail-guide"><h3>观察与对照</h3><p>{herb.observation||'结合叶、花、果与生长环境观察植物，可通过所列资料来源进一步阅读。'}</p><Link className="text-link" to={returnTo}>返回草药图鉴</Link>{herb.imageCredit&&<><hr/><h4>图片来源与许可</h4><p>{herb.imageCredit.title}</p><a className="text-link" href={herb.imageCredit.sourceUrl} target="_blank" rel="noreferrer">查看原图与作者 →</a><p><a href={herb.imageCredit.licenseUrl} target="_blank" rel="noreferrer">{herb.imageCredit.license}</a><br/>{herb.imageCredit.modifications}</p></>}<hr/><p>识别结果仅供参考，请勿据此自行采食或用药。</p></aside></div>
    {related.length>0 && <section className="similar-section"><div className="section-title"><Sprout/><div><h2>同科植物</h2><p>按科分类浏览，不代表形态相似或易混淆关系。</p></div></div><div className="recommend-grid">{related.map(item => <HerbCard key={item.id} herb={item} compact/>)}</div></section>}
  </div>
}
