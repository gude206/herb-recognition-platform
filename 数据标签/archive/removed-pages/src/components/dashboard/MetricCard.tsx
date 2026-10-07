import type { LucideIcon } from 'lucide-react'

export function MetricCard({icon:Icon,label,value,unit,note}:{icon:LucideIcon;label:string;value:string;unit:string;note:string}) {
  return <article className="dashboard-metric"><div className="dashboard-metric-icon"><Icon size={27} strokeWidth={1.9}/></div><div className="dashboard-metric-copy"><h3>{label}</h3><div className="dashboard-metric-number">{value}<span>{unit}</span></div><p>{note}</p></div><Icon className="dashboard-metric-watermark" size={72} strokeWidth={1}/></article>
}
