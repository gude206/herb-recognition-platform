import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'
echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])
export function ChartPanel({option,className=''}:{option:EChartsOption;className?:string}) { const ref=useRef<HTMLDivElement>(null); useEffect(()=>{if(!ref.current)return;const chart=echarts.init(ref.current);chart.setOption(option);const resize=new ResizeObserver(()=>chart.resize());resize.observe(ref.current);return()=>{resize.disconnect();chart.dispose()}},[option]);return <div ref={ref} className={`chart-panel ${className}`} aria-label="数据图表"/> }
