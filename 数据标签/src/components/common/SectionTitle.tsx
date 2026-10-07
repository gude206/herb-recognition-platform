import type { ReactNode } from 'react'
export function SectionTitle({icon,title,sub,action}:{icon:ReactNode;title:string;sub?:string;action?:ReactNode}) { return <div className="section-title"><div className="section-title-icon">{icon}</div><div><h2>{title}</h2>{sub&&<p>{sub}</p>}</div>{action&&<div className="section-title-action">{action}</div>}</div> }
