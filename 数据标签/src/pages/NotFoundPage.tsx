import { Link } from 'react-router-dom'
export function NotFoundPage() { return <div className="page-shell empty-state paper-card"><span className="eyebrow">404 · 页面暂未找到</span><h1>循着草木，再回首页</h1><Link to="/" className="button button-primary">返回首页</Link></div> }
