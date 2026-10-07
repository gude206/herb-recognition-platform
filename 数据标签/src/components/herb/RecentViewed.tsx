import { useEffect, useState } from 'react'
import { ArrowRight, Clock3 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getRecentHistory } from '../../api/herb'
import type { Herb } from '../../types/herb'
import { PlantImage } from './PlantImage'
export function RecentViewed() { const [items,setItems]=useState<Herb[]>([]); useEffect(()=>{void getRecentHistory().then(setItems)},[]); const list=items.length?items.slice(0,3):[]; return <section className="paper-card recent-card"><div className="mini-heading"><Clock3 size={20}/><h3>最近浏览</h3><Link to="/herbs">查看全部 <ArrowRight size={13}/></Link></div>{list.length?list.map(herb=><Link className="recent-item" key={herb.id} to={`/herbs/${herb.id}`}><PlantImage herb={herb}/><span><strong>{herb.name}</strong><small>{herb.latinName}</small></span><ArrowRight size={15}/></Link>):<div className="recent-empty"><span>尚无浏览记录</span><Link to="/herbs">去图鉴看看 <ArrowRight size={14}/></Link></div>}</section> }
