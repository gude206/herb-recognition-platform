import { useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, Eye, EyeOff, LockKeyhole, UserRound } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { authError, initializeAuth, login, logout, refreshAuth, register } from '../api/auth'
import { safeLoginTarget, useAccountSession } from '../api/session'
import { BrandLogo } from '../components/common/BrandLogo'

export function LoginPage() {
 const [params] = useSearchParams()
 const [role,setRole]=useState<'user'|'admin'>(params.get('role')==='admin'?'admin':'user')
 const [registering,setRegistering]=useState(false)
 const [account,setAccount]=useState('');const [name,setName]=useState('')
 const [password,setPassword]=useState('');const [confirm,setConfirm]=useState('')
 const [showPassword,setShowPassword]=useState(false);const [remember,setRemember]=useState(false)
 const [claim,setClaim]=useState(true);const [loading,setLoading]=useState(false);const [error,setError]=useState('')
 const session=useAccountSession()
 useEffect(()=>{void initializeAuth()},[])
 const switchRole=(next:'user'|'admin')=>{setRole(next);setRegistering(false);setPassword('');setConfirm('');setError('');setRemember(false)}
 const submit=async(event:FormEvent)=>{
  event.preventDefault();setError('')
  if(!account.trim()){setError('请输入用户名');return}
  if(registering&&password.length<12){setError('注册密码至少需要 12 位，可使用较长的短语');return}
  if(registering&&password!==confirm){setError('两次输入的密码不一致');return}
  setLoading(true)
  try{
   const response=registering?await register({account:account.trim(),name:name.trim(),password,claim_guest_history:claim}):await login({account:account.trim(),password,role,remember,claim_guest_history:claim})
   if(!response.user)throw new Error('未取得登录状态')
   // A full navigation clears requests and private history held by the previous account.
   window.location.assign(safeLoginTarget(params.get('next'),response.user.role))
  }catch(error){setError(authError(error))}finally{setLoading(false)}
 }
 const signOut=async()=>{setLoading(true);try{await logout();window.location.assign('/login?role='+role)}catch(error){setError(authError(error));setLoading(false)}}
 return <div className="login-page"><div className="login-scene"><div className="login-scroll"><span className="seal">中草药</span><b>本草传承<br/>识岐黄</b><i>传承千年本草智慧<br/>让中草药知识触手可及</i></div><div className="login-book"><span>本草<br/>纲目</span></div><div className="login-mortar"/><span className="scene-bamboo">竹<br/>影<br/>清<br/>风</span></div>
 <section className="login-panel paper-card"><div className="login-brand"><span><BrandLogo/></span><h1>中草药智能识别与知识平台</h1><p>识本草 · 传文化 · 智未来</p></div>
 <div className="login-tabs"><button type="button" className={role==='user'?'active':''} disabled={loading} onClick={()=>switchRole('user')}>用户登录</button><button type="button" className={role==='admin'?'active':''} disabled={loading} onClick={()=>switchRole('admin')}>管理员登录</button></div>
 {session.user?<div className="auth-current"><p>当前已登录：<strong>{session.user.name}</strong>（{session.user.role==='admin'?'管理员':'用户'}）</p><div><Link className="button button-primary" to="/profile">进入个人中心</Link>{session.user.role==='admin'&&<Link className="button button-light" to="/admin/articles">文章维护</Link>}<button type="button" className="button button-light" disabled={loading} onClick={()=>void signOut()}>退出并切换账号</button></div></div>:<>
 <h2 className="auth-form-title">{registering?'注册用户账号':role==='admin'?'管理员登录':'用户登录'}</h2>
 <form onSubmit={event=>void submit(event)}><label className="login-field"><UserRound size={19}/><input autoComplete="username" value={account} maxLength={40} disabled={loading} onChange={event=>setAccount(event.target.value)} placeholder="请输入用户名" aria-label="用户名" required/></label>
 {registering&&<label className="login-field"><UserRound size={19}/><input autoComplete="nickname" value={name} maxLength={80} disabled={loading} onChange={event=>setName(event.target.value)} placeholder="显示昵称（可选）" aria-label="显示昵称"/></label>}
 <label className="login-field"><LockKeyhole size={19}/><input autoComplete={registering?'new-password':'current-password'} type={showPassword?'text':'password'} value={password} maxLength={128} disabled={loading} onChange={event=>setPassword(event.target.value)} placeholder={registering?'设置密码，至少 12 位':'请输入密码'} aria-label="密码" required/><button type="button" onClick={()=>setShowPassword(!showPassword)} aria-label={showPassword?'隐藏密码':'显示密码'}>{showPassword?<EyeOff size={17}/>:<Eye size={17}/>}</button></label>
 {registering&&<label className="login-field"><LockKeyhole size={19}/><input autoComplete="new-password" type={showPassword?'text':'password'} value={confirm} maxLength={128} disabled={loading} onChange={event=>setConfirm(event.target.value)} placeholder="再次输入密码" aria-label="确认密码" required/></label>}
 {registering&&<p className="auth-help">用户名支持 3—40 位中文、字母、数字、下划线或短横线。注册仅创建普通用户。</p>}
 <div className="login-options">{!registering&&role==='user'&&<label><input type="checkbox" checked={remember} onChange={event=>setRemember(event.target.checked)}/>保持登录 30 天</label>}</div>
 <label className="auth-claim"><input type="checkbox" checked={claim} onChange={event=>setClaim(event.target.checked)}/><span>关联当前浏览器的访客历史<small>关联后，问答和识别记录仅由此账号访问。</small></span></label>
 <button className="button button-primary login-submit" disabled={loading||!session.ready}>{loading?'正在处理…':!session.ready?'正在读取登录状态…':registering?'注册并登录':'登录'} <ArrowRight size={17}/></button></form>
 {role==='user'?<p className="register-note">{registering?'已有账号？':'还没有账号？'} <button type="button" disabled={loading} onClick={()=>{setRegistering(!registering);setPassword('');setConfirm('');setError('')}}>{registering?'返回用户登录':'立即注册'}</button></p>:<p className="auth-help">管理员账号由本机初始化工具创建，不能通过公开注册获得管理员权限。</p>}
 </>}{session.error&&<div className="form-error" role="alert"><p>{session.error}</p><button type="button" className="button button-light" onClick={()=>void refreshAuth().catch(()=>{})}>重新读取登录状态</button></div>}{error&&<p className="form-error" role="alert">{error}</p>}
 </section></div>
}
