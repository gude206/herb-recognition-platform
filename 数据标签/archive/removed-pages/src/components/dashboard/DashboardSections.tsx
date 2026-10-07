import { Activity, BarChart3, BookOpen, Flame, Image as ImageIcon, Leaf, Network, Sprout, Target } from 'lucide-react'
import type { EChartsOption } from 'echarts'
import type { Herb } from '../../types/herb'
import { SectionTitle } from '../common/SectionTitle'
import { ChartPanel } from './ChartPanel'
import { PaperPanel, SealDecoration } from './DashboardDecorations'
import type { DashboardChartsData } from './dashboardChartTheme'
import type { DashboardSummary } from '../../types/dashboard'

export function DashboardPrimaryCharts({options,charts,summary}:{options:{bar:EChartsOption;property:EChartsOption;split:EChartsOption};charts:DashboardChartsData;summary:DashboardSummary}) {
  return <div className="dashboard-primary-grid">
    <PaperPanel className="dashboard-chart-card dashboard-effect-card"><SectionTitle icon={<Sprout/>} title="草药功效分类统计" sub="统计不同功效类别的草药数量，反映本平台的资源分布情况。"/><SealDecoration>本草</SealDecoration><div className="dashboard-chart-axis">数量（种）</div><ChartPanel option={options.bar}/></PaperPanel>
    <PaperPanel className="dashboard-chart-card dashboard-property-card"><SectionTitle icon={<Leaf/>} title="草药性味分布" sub="展示中草药在传统理论中的五种性味分布情况。"/><div className="dashboard-donut-wrap"><ChartPanel option={options.property}/><div className="dashboard-donut-center dashboard-property-center"><strong>{summary.herbCount}</strong><span>种草药</span></div><ul className="dashboard-flavor-legend">{charts.propertyStats.map((d,i)=><li key={d.name}><i style={{background:['#1f7a58','#d97853','#e1a64b','#90c6ae','#3c9877'][i]}}/>{d.name}<span>{d.value} ({Math.round(d.value/summary.herbCount*100)}%)</span></li>)}</ul></div></PaperPanel>
    <PaperPanel className="dashboard-chart-card dashboard-split-card"><SectionTitle icon={<BarChart3/>} title="图像数据集划分统计" sub="展示中草药图像数据集在训练、验证和测试集的分布情况。"/><SealDecoration>数据</SealDecoration><div className="dashboard-donut-wrap"><ChartPanel option={options.split}/><div className="dashboard-donut-center dashboard-split-center"><strong>{summary.imageCount.toLocaleString()}</strong><span>张图像</span></div><ul className="dashboard-split-legend">{charts.splitStats.map((d,i)=><li key={d.name}><i style={{background:['#1f7a58','#68af91','#badbcc'][i]}}/><span>{d.name}</span><strong>{d.value.toLocaleString()}</strong><em>({Math.round(d.value/summary.imageCount*100)}%)</em></li>)}</ul></div></PaperPanel>
  </div>
}

export function PerformanceCard({option,summary}:{option:EChartsOption;summary:DashboardSummary}) {
  return <PaperPanel className="dashboard-performance-card"><SectionTitle icon={<Target/>} title="模型识别性能评估" sub="展示模型在测试集上的各项评估指标及训练过程的变化趋势。"/><div className="dashboard-performance-metrics">{[[Target,'准确率',`${summary.accuracy}%`],[BarChart3,'精确率','94.8%'],[Network,'召回率','93.6%'],[BookOpen,'F1 值','94.2%']].map(([Icon,label,value])=>{const I=Icon as typeof Target;return <div key={String(label)}><span><I size={22}/></span><div><small>{String(label)}</small><strong>{String(value)}</strong></div></div>})}</div><div className="dashboard-performance-chart-title">模型训练过程 <span>（准确率与损失值）</span></div><ChartPanel option={option}/></PaperPanel>
}

export function HerbRanking({herbs}:{herbs:Herb[]}) {
  return <PaperPanel className="dashboard-ranking-card"><SectionTitle icon={<Flame/>} title="热门草药识别 TOP 5" sub="根据用户识别次数统计的热门中草药。"/><div className="dashboard-ranking-list">{herbs.slice(0,5).map((herb,index)=><div className="dashboard-ranking-row" key={herb.id}><b className={`rank rank-${index+1}`}>{index+1}</b><img src={herb.image} alt=""/><div><strong>{herb.name}</strong><span>{herb.effects.slice(0,2).map(effect=><small key={effect}>{effect}</small>)}</span></div><em>{[2842,2156,1893,1612,1493][index].toLocaleString()} <small>次</small></em></div>)}</div></PaperPanel>
}

export function TrendChart({option}:{option:EChartsOption}) {return <PaperPanel className="dashboard-trend-card"><SectionTitle icon={<Activity/>} title="近期识别趋势" sub="展示最近 7 天的草药识别次数变化趋势。"/><div className="dashboard-chart-axis">识别次数</div><ChartPanel option={option}/></PaperPanel>}

export function ResourceOverview() {
  const resources = [[BookOpen,'草药条目','300','条'],[Leaf,'药用部位','12','类'],[Target,'功效标签','58','类'],[Network,'化学成分','1,260','条'],[ImageIcon,'参考文献','856','篇']] as const
  return <PaperPanel className="dashboard-resources-card"><SectionTitle icon={<BookOpen/>} title="数据资源概览" sub="展示平台中草药知识库的主要数据资源情况。"/><div className="dashboard-resources-list">{resources.map(([Icon,label,value,unit])=><div key={label}><span className="dashboard-resource-icon"><Icon size={19}/></span><span>{label}</span><strong>{value}<small>{unit}</small></strong></div>)}</div></PaperPanel>
}
