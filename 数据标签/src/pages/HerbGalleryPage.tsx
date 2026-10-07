import { useEffect, useRef, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { BookOpen, Grid2X2, Leaf, List, MapPin, RotateCcw, Search, Sprout } from 'lucide-react'
import { PageHero } from '../components/common/PageHero'
import { SectionTitle } from '../components/common/SectionTitle'
import { HerbCard } from '../components/herb/HerbCard'
import { getHerbs, getHerbFilters } from '../api/herb'
import { readRecentHerbs } from '../utils/history'
import { galleryError } from '../utils/galleryError'
import type { Herb, HerbFilters } from '../types/herb'

export function HerbGalleryPage() {
  const [params,setParams] = useSearchParams()
  const latestParams = useRef(params)
  latestParams.current = params
  const [items,setItems] = useState<Herb[]>([]), [filters,setFilters] = useState<HerbFilters>()
  const [total,setTotal] = useState(0), [actualPage,setActualPage] = useState(1)
  const [loading,setLoading] = useState(true), [error,setError] = useState(''), [retry,setRetry] = useState(0)
  const [layout,setLayout] = useState<'grid'|'list'>('grid')
  const queryKey = params.toString(), q = params.get('q') || '', sort = params.get('sort') || 'class'
  useEffect(() => {let alive=true; void getHerbFilters().then(value => {if(alive)setFilters(value)}).catch(() => {});return () => {alive=false}},[retry])
  useEffect(() => {
    let alive=true; setLoading(true); setError('')
    const values = new URLSearchParams(queryKey)
    const timer = window.setTimeout(() => {
      void getHerbs({q: values.get('q') || '', family: values.get('family') || '', genus: values.get('genus') || '',
        region: values.get('region') || '', effect: values.get('effect') || '', property: values.get('property') || '',
        part: values.get('part') || '', sort: values.get('sort') || 'class',
        page: Math.max(1, Number(values.get('page')) || 1), page_size: 24, recent_ids: readRecentHerbs().join(',')})
        .then(value => {if(alive){setItems(value.items);setTotal(value.total);setActualPage(value.page || 1)}})
        .catch(reason => {if(alive){setItems([]);setError(galleryError(reason))}})
        .finally(() => {if(alive)setLoading(false)})
    },200)
    return () => {alive=false;window.clearTimeout(timer)}
  },[queryKey,retry])
  const update = (key:string,value:string) => {
    const next = new URLSearchParams(latestParams.current); if(value)next.set(key,value);else next.delete(key)
    if(key !== 'page')next.delete('page')
    latestParams.current = next
    setParams(next,{replace:key==='q'})
  }
  const reset = () => {latestParams.current = new URLSearchParams();setParams({})}
  const pages = Math.max(1,Math.ceil(total/24))
  return <div className="page-shell gallery-page">
    <PageHero eyebrow="本草图鉴 · 认识活体植物" title="草药图鉴" subtitle="观察叶、花、果与生长环境，了解药用植物的分布和药材来源。" variant="garden">
      <div className="hero-shortcuts"><a href="#filters"><MapPin/>按分布查找</a><a href="#filters"><Leaf/>按科属查找</a><a href="#herb-list"><Sprout/>浏览活体植物</a></div>
    </PageHero>
    <div className="gallery-layout">
      <aside className="paper-card filters-card" id="filters"><SectionTitle icon={<Search/>} title="筛选植物"/>
        <label className="filter-search"><Search size={16}/><input value={q} maxLength={200} onChange={e => update('q',e.target.value)} placeholder="名称、学名、别名、药材名或功效" aria-label="搜索草药或功效"/></label>
        <SelectFilter title="植物科名" values={filters?.families || []} value={params.get('family') || ''} change={v => update('family',v)}/>
        <SelectFilter title="植物属名" values={filters?.genera || []} value={params.get('genus') || ''} change={v => update('genus',v)}/>
        <SelectFilter title="分布地区" values={filters?.regions || []} value={params.get('region') || ''} change={v => update('region',v)}/>
        <details className="medicinal-filters"><summary>药材知识筛选</summary><p>按来源已记载的药材属性筛选。</p>
          <SelectFilter title="传统功效" values={filters?.effects || []} value={params.get('effect') || ''} change={v => update('effect',v)}/>
          <SelectFilter title="药性" values={filters?.properties || []} value={params.get('property') || ''} change={v => update('property',v)}/>
          <SelectFilter title="药用部位" values={filters?.parts || []} value={params.get('part') || ''} change={v => update('part',v)}/>
        </details>
        <button className="reset-button" onClick={reset}><RotateCcw size={15}/>重置筛选</button>
      </aside>
      <section className="gallery-main" id="herb-list">
        <div className="paper-card gallery-toolbar"><div className="collection-count"><BookOpen/><strong>找到 <b>{loading?'…':total}</b> 类植物</strong><span>图鉴共 {filters?.total ?? '…'} 类</span></div>
          <div className="toolbar-actions"><label className="sort-select">{sort==='name'?'名称排序':sort==='recent'?'最近浏览优先':'类别顺序'}<select value={sort} onChange={e => update('sort',e.target.value)} aria-label="排序方式"><option value="class">类别顺序</option><option value="name">名称排序</option><option value="recent">最近浏览优先</option></select></label>
            <button className={'view-button '+(layout==='grid'?'active':'')} aria-label="网格视图" aria-pressed={layout==='grid'} onClick={() => setLayout('grid')}><Grid2X2 size={17}/></button>
            <button className={'view-button '+(layout==='list'?'active':'')} aria-label="列表视图" aria-pressed={layout==='list'} onClick={() => setLayout('list')}><List size={18}/></button>
          </div>
        </div>
        {loading?<div className="loading-box" role="status">正在加载植物资料…</div>:error?<div className="empty-state paper-card" role="alert"><h3>暂时无法打开图鉴</h3><p>{error}</p><button className="button button-primary" onClick={() => setRetry(v => v+1)}>重新加载</button></div>:items.length?<><div className={'herb-grid '+(layout==='list'?'list-layout':'')}>{items.map(herb => <HerbCard key={herb.id} herb={herb}/>)}</div>
          <nav className="atlas-pagination" aria-label="图鉴分页"><button disabled={actualPage===1} onClick={() => update('page',String(actualPage-1))}>上一页</button><span>第 {actualPage} / {pages} 页</span><button disabled={actualPage===pages} onClick={() => update('page',String(actualPage+1))}>下一页</button></nav>
        </>:<div className="empty-state paper-card"><Search size={28}/><h3>没有找到匹配的植物</h3><p>试试调整关键词或清除筛选条件。</p><button className="button button-primary" onClick={reset}>重置筛选</button></div>}
      </section>
      <aside className="gallery-aside"><section className="paper-card atlas-guide"><SectionTitle icon={<Sprout/>} title="观察一株植物"/><p>先看生长形态，再对照叶、花、果和茎的特征。详情页也保留地下器官及孢子结构资料。</p><h4>分布与生境</h4><p>{filters ? filters.distributionCount+' 类有分布记录。' : ''}分布资料帮助了解生长区域，不能单独作为识别依据。</p><h4>图片与资料状态</h4><p>数据集参考图尚未经过器官及授权核实。缺少毒性记载不表示无毒。</p><Link className="text-link" to="/#recognize">上传植物图片识别 →</Link></section></aside>
    </div>
  </div>
}

function SelectFilter({title,values,value,change}:{title:string;values:string[];value:string;change:(v:string)=>void}) {
  return <label className="atlas-select-filter"><span>{title}</span><select value={value} onChange={e => change(e.target.value)}><option value="">全部</option>{values.map(v => <option value={v} key={v}>{v}</option>)}{value && !values.includes(value) && <option value={value}>{value}</option>}</select></label>
}
