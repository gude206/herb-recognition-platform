import { TriangleAlert } from 'lucide-react'
import type { Herb } from '../../types/herb'

export function IdentityWarning({className='atlas-warning'}:{originalLatinName?:string;acceptedLatinName?:string;className?:string}) {
  return <div className={className} role="alert"><strong><TriangleAlert size={14}/>植物身份存在冲突</strong><p>该模型类别的名称信息不一致，对应植物资料不予公开；本次结果不能作为物种判断依据。</p></div>
}

export function HerbLatinNames({herb}:{herb:Herb}) {
  return <><dt>来源学名</dt><dd>{herb.originalLatinName?.trim() || '暂无可靠资料'}</dd><dt>规范学名</dt><dd>{herb.acceptedLatinName?.trim() || '暂无可靠资料'}</dd></>
}
