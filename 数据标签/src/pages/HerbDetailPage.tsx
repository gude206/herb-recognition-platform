import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, BookOpen, Leaf, MapPin, Sprout } from 'lucide-react'
import { PageHero } from '../components/common/PageHero'
import { HerbCard } from '../components/herb/HerbCard'
import { PlantImage } from '../components/herb/PlantImage'
import { HerbLatinNames, IdentityWarning } from '../components/herb/HerbIdentity'
import { getHerb, getHerbs } from '../api/herb'
import { addRecentHerb } from '../utils/history'
import type { Herb } from '../types/herb'
import { returnToFromState } from '../utils/atlasNavigation'

const available = (value?: string) => value?.trim() || '暂无可靠资料'
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
    {herb.identityConflict && <IdentityWarning/>}
    <div className="atlas-detail-layout">
      <div className="detail-main">
        <section className="paper-card detail-overview"><PlantImage herb={herb} className="detail-image"/><div className="detail-intro"><span className="eyebrow"><Leaf size={14}/>{herb.family}</span><h2>{herb.name}</h2><p className="latin">{herb.latinName}</p><p>{herb.description}</p><div className="tag-row"><span className="tag">{herb.reviewStatus || '审核状态未提供'}</span><span className="tag">{herb.identityStatus || '身份状态未提供'}</span></div><p className="atlas-muted">图片用于数据集对照，器官与授权状态待核对。</p></div></section>
        <section className="paper-card atlas-section"><h3><BookOpen size={19}/>植物身份</h3><dl className="atlas-dl">
          <HerbLatinNames herb={herb}/>
          <dt>植物别名</dt><dd>{available(herb.aliases.join('、'))}</dd><dt>规范科 / 属</dt><dd>{available(herb.family)} / {available(herb.genus)}</dd>
          <dt>原资料中文科属</dt><dd>{available(herb.familyChinese)} / {available(herb.genusChinese)}<small>原资料采用的分类体系可能与规范分类不同。</small></dd>
          <dt>分类状态</dt><dd>{available(herb.taxonomyStatus)}<small>{herb.taxonomySystem}</small></dd>
        </dl></section>
        <section className="paper-card atlas-section" id="distribution"><h3><MapPin size={19}/>分布与生长环境</h3><dl className="atlas-dl">
          <dt>活体分布</dt><dd>{available(herb.distribution)}<small>{herb.distributionStatus}</small></dd><dt>生境</dt><dd>{available(herb.habitat)}</dd>
          <dt>海拔</dt><dd>{available(herb.elevation)}</dd><dt>花期</dt><dd>{available(herb.flowering)}</dd><dt>果期</dt><dd>{available(herb.fruiting)}</dd>
          {herb.sporeSeason && <><dt>孢子期</dt><dd>{herb.sporeSeason}</dd></>}
        </dl><p className="atlas-muted">分布范围用于了解植物的生长区域，需结合多种形态特征识别。</p></section>
        <section className="paper-card atlas-section"><h3><Sprout size={19}/>活体识别特征</h3>
          {herb.features?.length ? <dl className="atlas-dl atlas-features">{herb.features.map(feature => <div key={feature.label}><dt>{feature.label}</dt><dd>{feature.value}</dd></div>)}</dl> : <p>{available(herb.morphology)}</p>}
          {herb.completeIntroduction && <details className="atlas-fulltext"><summary>阅读完整植物介绍</summary><p>{herb.completeIntroduction}</p></details>}
        </section>
        <section className="paper-card atlas-section"><h3><BookOpen size={19}/>药材与本草资料</h3><p>{available(herb.background)}</p>
          <dl className="atlas-dl"><dt>药材产区</dt><dd>{available(herb.medicinalRegions)}<small>药材产区与活体植物分布分别记录。</small></dd></dl>
          {herb.materials?.length ? <div className="atlas-materials">{herb.materials.map((material,index) => <article key={(material['药材ID'] || '')+index}>
            <h4>{material['药材名称'] || '药材记录'}</h4><p className="atlas-muted">{material['基原关联类型']} · {material['审核状态']}</p>
            <dl className="atlas-dl">{['药材来源原文','药用部位','加工状态','性味原文','归经','传统功效原文','传统应用','炮制品原文','毒性记载','使用注意原文'].map(field => <div key={field}><dt>{field.replace('原文','')}</dt><dd>{available(material[field])}</dd></div>)}</dl>
            <p className="atlas-muted">{material['药典核对状态']}</p>{safeURL(material['来源链接'] || '') && <a className="text-link" href={material['来源链接']} target="_blank" rel="noreferrer">查看药材来源 <ArrowRight size={14}/></a>}
          </article>)}</div> : <div className="atlas-prose"><h4>原资料药材记载</h4><p className="atlas-muted">尚未关联到独立药材条目，以下保留原资料记载。</p><dl className="atlas-dl">
            <dt>药用部位</dt><dd>{available(herb.medicinalPart.join('、'))}</dd>
            <dt>药性</dt><dd>{available(herb.natureText)}</dd><dt>药味</dt><dd>{available(herb.flavorText)}</dd>
            <dt>归经</dt><dd>{available(herb.meridianText)}</dd><dt>传统功效</dt><dd>{available(herb.traditionalEffects)}</dd>
          </dl></div>}
          {herb.traditionalUses.length>0 && <div className="atlas-prose"><h4>传统应用记载</h4>{herb.traditionalUses.map((text,i) => <p key={i}>{text}</p>)}</div>}
          {herb.medicinalIntroduction && <details className="atlas-fulltext"><summary>阅读完整药材介绍</summary><p>{herb.medicinalIntroduction}</p></details>}
          <p className="atlas-muted">传统本草记载用于知识展示，不作为自行用药依据。</p>
        </section>
        <section className="paper-card atlas-section"><h3>注意事项与易混淆记录</h3><dl className="atlas-dl">
          <dt>毒性记载</dt><dd>{available(herb.toxicity)}<small>缺少毒性资料不代表无毒。</small></dd>
          <dt>使用注意</dt><dd>{available(herb.precautions.join('\n'))}</dd>
          <dt>易混淆关系</dt><dd>尚无人工核实的对应关系。</dd>
          <dt>混淆风险记载</dt><dd>{available(herb.confusionRisk)}</dd><dt>核对状态</dt><dd>{available(herb.confusionStatus)}</dd>
        </dl>
          {(herb.confusion || herb.differences) && <details className="atlas-fulltext"><summary>查看来源比较摘录（待核实）</summary><p className="atlas-muted">摘录可能涉及器官之间的比较，尚未完成植物名称消歧，不作为易混淆植物名单。</p><dl className="atlas-dl"><dt>原名称摘录</dt><dd>{available(herb.confusion)}</dd><dt>比较原文</dt><dd>{available(herb.differences)}</dd></dl></details>}
          <p className="atlas-muted">未经人工复核的比较记录不能作为鉴定结论。</p></section>
        <section className="paper-card atlas-section"><h3>资料来源与核对状态</h3><p className="atlas-muted">更新日期：{herb.updatedAt || '未记录'} · {herb.reviewStatus || '未记录'}</p>
          <ul className="atlas-sources">{herb.sources?.map(source => <li key={source.url}>{safeURL(source.url) ? <a href={source.url} target="_blank" rel="noreferrer">{source.name} ↗</a> : <strong>{source.name}</strong>}<small>{source.version} · {source.locator}</small></li>)}</ul>
          {!!Object.keys(herb.fieldReview || {}).length && <details className="atlas-fulltext"><summary>查看字段核对说明</summary><dl className="atlas-dl">{Object.entries(herb.fieldReview || {}).map(([field,status]) => <div key={field}><dt>{field}</dt><dd>{status}</dd></div>)}</dl></details>}
          {herb.notes && <p className="atlas-warning">{herb.notes}</p>}
        </section>
      </div>
      <aside className="paper-card atlas-guide atlas-detail-guide"><h3>观察与对照</h3><p>观察生长形态、叶序和叶片，再结合花、果与茎的特征，按季节对照详情。</p><a className="text-link" href="#distribution">查看分布与生境 ↓</a><hr/><h4>资料状态</h4><p>{herb.reviewStatus || '未记录'}</p><p>部分字段仍缺少可靠来源，详情中已逐项标明。</p></aside>
    </div>
    {related.length>0 && <section className="similar-section"><div className="section-title"><Sprout/><div><h2>同科植物</h2><p>按科分类浏览，不代表形态相似或易混淆关系。</p></div></div><div className="recommend-grid">{related.map(item => <HerbCard key={item.id} herb={item} compact/>)}</div></section>}
  </div>
}
