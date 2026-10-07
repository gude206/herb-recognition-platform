import type { EChartsOption } from 'echarts'
import type { DashboardSummary } from '../../types/dashboard'

export type DashboardChartsData = {
  effectStats: {name:string;value:number}[]
  propertyStats: {name:string;value:number}[]
  splitStats: {name:string;value:number}[]
  recentStats: number[]
}

export const dashboardChartColors = {green:'#1f7a58', palette:['#1f7a58','#3c9877','#68af91','#90c6ae','#badbcc'],warm:'#d97853'}
const axis = {axisLine:{show:false},axisTick:{show:false},axisLabel:{color:'#687871',fontSize:12,margin:11},splitLine:{lineStyle:{color:'rgba(30,80,60,.09)'}}}
const tooltip = {backgroundColor:'rgba(255,253,247,.98)',borderColor:'rgba(31,122,88,.16)',textStyle:{color:'#244437',fontSize:12}}

export function makeDashboardOptions(charts:DashboardChartsData,summary:DashboardSummary) {
  const bar: EChartsOption = {tooltip:{trigger:'axis',...tooltip},grid:{left:39,right:14,top:30,bottom:37},xAxis:{type:'category',data:charts.effectStats.map(d=>d.name),axisLine:{lineStyle:{color:'rgba(30,80,60,.12)'}},axisTick:{show:false},axisLabel:{color:'#42594c',fontSize:12,interval:0,margin:12}},yAxis:{type:'value',min:0,max:100,splitNumber:5,...axis},series:[{type:'bar',barWidth:'58%',data:charts.effectStats.map((d,i)=>({value:d.value,itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:dashboardChartColors.palette[i]},{offset:1,color:['#53a989','#80bea4','#a8d3bd','#c6e1d0','#d6e9db'][i]}]},borderRadius:[3,3,0,0]}})),label:{show:true,position:'top',fontSize:13,fontWeight:700,color:'#1c644b'}}]}
  const property: EChartsOption = {tooltip:{trigger:'item',...tooltip,formatter:'{b}：{c} 种 ({d}%)'},series:[{type:'pie',radius:['46%','70%'],center:['45%','51%'],startAngle:90,avoidLabelOverlap:true,label:{show:true,formatter:(p:any)=>`${p.name}\n${p.value} (${Math.round(p.percent)}%)`,color:'#3d554b',fontSize:11,lineHeight:16},labelLine:{length:9,length2:11,lineStyle:{width:1}},itemStyle:{borderColor:'#f8f6ef',borderWidth:1.5},data:charts.propertyStats.map((d,i)=>({...d,itemStyle:{color:['#1f7a58','#d97853','#e1a64b','#90c6ae','#3c9877'][i]}}))}]}
  const split: EChartsOption = {tooltip:{trigger:'item',...tooltip,formatter:'{b}：{c} 张 ({d}%)'},series:[{type:'pie',radius:['48%','73%'],center:['36%','51%'],startAngle:90,label:{show:true,position:'outside',formatter:'{d}%',color:'#325246',fontWeight:700,fontSize:12},labelLine:{length:8,length2:8,lineStyle:{color:'#8cbba3'}},itemStyle:{borderColor:'#f8f6ef',borderWidth:1.5},data:charts.splitStats.map((d,i)=>({...d,itemStyle:{color:['#1f7a58','#68af91','#badbcc'][i]}}))}]}
  const line: EChartsOption = {tooltip:{trigger:'axis',...tooltip},legend:{data:['准确率 (Accuracy)','损失值 (Loss)'],right:8,top:0,itemWidth:16,itemHeight:8,textStyle:{color:'#546a5d',fontSize:11}},grid:{left:39,right:14,top:37,bottom:29},xAxis:{type:'category',boundaryGap:false,data:['0','5','10','15','20','25','30','35','40','45','50'],...axis,splitLine:{show:false}},yAxis:{type:'value',min:0,max:1,interval:.2,...axis},series:[{name:'准确率 (Accuracy)',type:'line',smooth:.28,showSymbol:true,symbolSize:5,data:[.38,.61,.72,.79,.84,.87,.9,.92,.935,.944,.952],lineStyle:{color:'#1f7a58',width:2.4},itemStyle:{color:'#1f7a58'},areaStyle:{color:'rgba(31,122,88,.07)'}},{name:'损失值 (Loss)',type:'line',smooth:.28,showSymbol:true,symbolSize:5,data:[.78,.56,.39,.30,.24,.2,.17,.14,.12,.10,.08],lineStyle:{color:'#d97853',width:2},itemStyle:{color:'#d97853'}}]}
  const trend: EChartsOption = {tooltip:{trigger:'axis',...tooltip},grid:{left:47,right:16,top:27,bottom:27},xAxis:{type:'category',boundaryGap:false,data:['04-10','04-11','04-12','04-13','04-14','04-15','04-16'],...axis,splitLine:{show:false}},yAxis:{type:'value',min:0,max:2000,interval:500,...axis},series:[{type:'line',smooth:.2,symbol:'circle',symbolSize:7,data:charts.recentStats,lineStyle:{color:'#1f7a58',width:2.3},itemStyle:{color:'#1f7a58',borderColor:'#fffdf7',borderWidth:1.4},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(80,166,123,.30)'},{offset:1,color:'rgba(80,166,123,.015)'}]}},label:{show:true,position:'top',color:'#344b3f',fontSize:10,formatter:(params:any)=>Number(params.value).toLocaleString()}}]}
  return {bar,property,split,line,trend,summary}
}
