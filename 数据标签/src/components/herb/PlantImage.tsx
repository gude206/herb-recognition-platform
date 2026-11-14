import { useState } from 'react'
import type { Herb } from '../../types/herb'
import { PhotoCredit } from '../common/PhotoCredit'

export function PlantImage({herb, className = '', creditLinks=false}: {herb: Herb; className?: string; creditLinks?: boolean}) {
  const [failedURL, setFailedURL] = useState('')
  return <figure className={'plant-image '+className}>
    {herb.image && herb.image !== failedURL
      ? <><img src={herb.image} alt={herb.name + '实拍照片'} loading="lazy" onError={() => setFailedURL(herb.image)}/>{herb.imageCredit&&<figcaption><PhotoCredit credit={herb.imageCredit} linked={creditLinks}/></figcaption>}</>
      : <div className="plant-image-placeholder"><span>暂无图片</span></div>}
  </figure>
}
