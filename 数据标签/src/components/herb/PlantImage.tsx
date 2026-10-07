import { useState } from 'react'
import { Leaf } from 'lucide-react'
import type { Herb } from '../../types/herb'

export function PlantImage({herb, className = ''}: {herb: Herb; className?: string}) {
  const [failedURL, setFailedURL] = useState('')
  return <figure className={'plant-image '+className}>
    {herb.image && herb.image !== failedURL
      ? <img src={herb.image} alt={herb.name + '数据集参考图'} loading="lazy" onError={() => setFailedURL(herb.image)}/>
      : <div className="plant-image-placeholder"><Leaf size={36}/><span>植物图片待补充</span></div>}
    {herb.imageStatus === 'dataset_reference' && <figcaption>数据集参考图 · 待核对</figcaption>}
  </figure>
}
