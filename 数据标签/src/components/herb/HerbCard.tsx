import { ArrowUpRight, Leaf, MapPin } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import type { Herb } from '../../types/herb'
import { PlantImage } from './PlantImage'
import { galleryReturnTo, returnToFromState } from '../../utils/atlasNavigation'
export function HerbCard({herb,compact=false}:{herb:Herb;compact?:boolean}) {
  const location = useLocation()
  const returnTo = location.pathname === '/herbs' ? galleryReturnTo(location.pathname + location.search) : returnToFromState(location.state)
  return <Link className={'herb-card '+(compact?'herb-card-compact':'')} to={'/herbs/'+herb.id} state={{galleryReturnTo:returnTo}}>
    <PlantImage herb={herb}/><div className="herb-card-copy">
      <div className="herb-name-row"><h3>{herb.name}</h3><ArrowUpRight size={16}/></div>
      <p className="latin" title={herb.latinName}>{herb.latinName}</p>
      <div className="tag-row">{herb.family&&<span className="tag">{herb.familyChinese||herb.family}</span>}{herb.growthForm && <span className="tag">{herb.growthForm}</span>}</div>
      {!compact && <><p className="herb-description">{herb.description}</p><p className="card-distribution" title={herb.distribution}><MapPin size={13}/>{herb.distribution || ''}</p></>}
      <span className="herb-more"><Leaf size={14}/> 查看活体植物资料</span>
    </div>
  </Link>
}
