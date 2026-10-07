import { TriangleAlert } from 'lucide-react'
import type { Herb } from '../../types/herb'

export function IdentityWarning({originalLatinName,acceptedLatinName,className='atlas-warning'}:{originalLatinName?:string;acceptedLatinName?:string;className?:string}) {
  return <div className={className} role="alert"><strong><TriangleAlert size={14}/>植物身份存在冲突</strong><p>原始中文名、学名与分类资料不一致，需核实身份后再用于物种判断。</p>{originalLatinName && <p>原始学名：{originalLatinName}</p>}{acceptedLatinName && <p>图鉴规范学名：{acceptedLatinName}</p>}</div>
}

export function HerbLatinNames({herb}:{herb:Herb}) {
  return <><dt>原始学名</dt><dd>{herb.originalLatinName?.trim() || '暂无可靠资料'}</dd><dt>规范学名</dt><dd>{herb.acceptedLatinName?.trim() || '暂无可靠资料'}</dd></>
}
