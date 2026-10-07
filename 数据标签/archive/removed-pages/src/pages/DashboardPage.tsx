import { useEffect, useMemo, useState } from 'react'
import { Activity, Image as ImageIcon, MessageCircle, Sprout, Target } from 'lucide-react'
import { DashboardHero } from '../components/dashboard/DashboardHero'
import { MetricCard } from '../components/dashboard/MetricCard'
import { DashboardPrimaryCharts, PerformanceCard, HerbRanking, TrendChart, ResourceOverview } from '../components/dashboard/DashboardSections'
import { makeDashboardOptions, type DashboardChartsData } from '../components/dashboard/dashboardChartTheme'
import { getDashboardCharts, getDashboardSummary } from '../api/dashboard'
import { mockHerbs } from '../data/mockHerbs'
import { dashboardSummary, effectStats, propertyStats, recentStats, splitStats } from '../data/mockDashboard'
import type { DashboardSummary } from '../types/dashboard'

export function DashboardPage() {
  const [summary,setSummary] = useState<DashboardSummary>(dashboardSummary)
  const [charts,setCharts] = useState<DashboardChartsData>({effectStats,propertyStats,splitStats,recentStats})
  useEffect(()=>{void Promise.all([getDashboardSummary(),getDashboardCharts()]).then(([s,c])=>{setSummary(s);setCharts(c)})},[])
  const options = useMemo(()=>makeDashboardOptions(charts,summary),[charts,summary])
  return <div className="page-shell dashboard-page">
    <DashboardHero/>
    <div className="dashboard-content">
      <div className="dashboard-metrics-grid">
        <MetricCard icon={Sprout} label="草药类别" value={summary.herbCount.toLocaleString()} unit="种" note="涵盖常见中草药"/>
        <MetricCard icon={ImageIcon} label="图像总量" value={summary.imageCount.toLocaleString()} unit="张" note="高质量多角度图像"/>
        <MetricCard icon={Target} label="模型准确率" value={`${summary.accuracy}%`} unit="" note="基于测试集评估"/>
        <MetricCard icon={Activity} label="今日识别次数" value={summary.todayRecognitions.toLocaleString()} unit="次" note="较昨日持续增长"/>
        <MetricCard icon={MessageCircle} label="问答交互" value={summary.chatCount.toLocaleString()} unit="次" note="累计知识问答"/>
      </div>
      <DashboardPrimaryCharts options={options} charts={charts} summary={summary}/>
      <div className="dashboard-secondary-grid">
        <PerformanceCard option={options.line} summary={summary}/>
        <HerbRanking herbs={mockHerbs}/>
        <TrendChart option={options.trend}/>
        <ResourceOverview/>
      </div>
      <div className="dashboard-data-note"><span>数据更新时间：2026-04-16 18:00</span><span>模型版本：HerbVision v1.2</span><span>评估结果基于测试数据集，仅供教学与科普展示。</span></div>
    </div>
  </div>
}
