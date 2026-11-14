import { useState, type FormEvent } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { Search, UserRound, Menu, X } from 'lucide-react'
import { useAccountSession } from '../../api/session'
import { logout } from '../../api/auth'
import { BrandLogo } from './BrandLogo'
import { UserAvatar } from './UserAvatar'

const links = [{to:'/',label:'首页'},{to:'/herbs',label:'草药图鉴'},{to:'/knowledge',label:'本草科普'}]
export function Header() {
  const [query,setQuery] = useState(''); const [open,setOpen] = useState(false); const navigate=useNavigate()
  const submit = (event: FormEvent) => { event.preventDefault(); navigate(`/herbs${query.trim()?`?q=${encodeURIComponent(query.trim())}`:''}`); setOpen(false) }
  const {user} = useAccountSession()
  const [logoutError,setLogoutError] = useState('')
  const signOut = async () => { try { await logout(); window.location.assign('/login') } catch { setLogoutError('退出失败，请重试') } }
  return <header className="site-header"><div className="header-inner">
    <Link to="/" className="brand"><span className="brand-mark"><BrandLogo/></span><span>中草药智能识别与知识平台</span></Link>
    <button className="mobile-menu" aria-label="打开导航" onClick={()=>setOpen(!open)}>{open?<X/>:<Menu/>}</button>
    <div className={`header-content ${open?'is-open':''}`}>
      <nav className="main-nav">{links.map(link=><NavLink key={link.to} to={link.to} end={link.to==='/'} onClick={()=>setOpen(false)}>{link.label}</NavLink>)}</nav>
      <form className="header-search" onSubmit={submit}><Search size={18}/><input aria-label="搜索植物或别名" value={query} maxLength={200} onChange={event=>setQuery(event.target.value)} placeholder="搜索植物 / 学名 / 别名"/></form>
      {user?.role==='admin'&&<Link className="auth-admin-link" to="/admin/articles">文章维护</Link>}
      {user?<Link to="/profile" className="header-account" aria-label="进入个人中心" onClick={()=>setOpen(false)}><UserAvatar user={user}/><span>{user.name}</span></Link>:<><Link to="/login" className="user-link" aria-label="用户登录"><UserRound size={19}/></Link><Link className="button button-primary header-login" to="/login">登录</Link></>}
      {user&&<button type="button" className="auth-logout" onClick={()=>void signOut()} title={logoutError||'退出当前账号'}>{logoutError||'退出'}</button>}
    </div>
  </div></header>
}
