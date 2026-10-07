import { useState, type FormEvent } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { Leaf, Search, UserRound, Menu, X } from 'lucide-react'

const links = [{to:'/',label:'首页'},{to:'/herbs',label:'草药图鉴'},{to:'/knowledge',label:'本草科普'}]
export function Header() {
  const [query,setQuery] = useState(''); const [open,setOpen] = useState(false); const navigate=useNavigate()
  const submit = (event: FormEvent) => { event.preventDefault(); navigate(`/herbs${query.trim()?`?q=${encodeURIComponent(query.trim())}`:''}`); setOpen(false) }
  const user = localStorage.getItem('herb-user')
  return <header className="site-header"><div className="header-inner">
    <Link to="/" className="brand"><span className="brand-mark"><Leaf size={24}/></span><span>中草药智能识别与知识平台</span></Link>
    <button className="mobile-menu" aria-label="打开导航" onClick={()=>setOpen(!open)}>{open?<X/>:<Menu/>}</button>
    <div className={`header-content ${open?'is-open':''}`}>
      <nav className="main-nav">{links.map(link=><NavLink key={link.to} to={link.to} end={link.to==='/'} onClick={()=>setOpen(false)}>{link.label}</NavLink>)}</nav>
      <form className="header-search" onSubmit={submit}><Search size={18}/><input aria-label="搜索草药或功效" value={query} maxLength={200} onChange={event=>setQuery(event.target.value)} placeholder="搜索草药 / 功效 / 别名"/></form>
      <Link to={user?'/login':'/login'} className="user-link" aria-label="用户中心"><UserRound size={19}/></Link>
      <Link className="button button-primary header-login" to="/login">{user||'登录'}</Link>
    </div>
  </div></header>
}
