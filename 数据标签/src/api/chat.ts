import { isAxiosError } from 'axios'
import { apiClient } from './client'
import { getHistoryToken } from './historyIdentity'
import { getSession } from './session'

export interface ToolCall { id: string; name: string; status: 'success'|'error'; arguments: Record<string,unknown>; result: unknown; elapsed_ms?: number }
export interface ChatMessage { role: 'user' | 'assistant'; content: string; tool_calls?: ToolCall[]; image_record_id?: string }
export interface ChatPayload { message: string; herb_id?: string; history?: ChatMessage[]; conversation_id?: string; image_record_id?: string }
export interface AgentAnswer { answer: string; references: string[]; model: string; conversation_id?: string; saved?: boolean; tool_calls?: ToolCall[] }
export async function sendChat(payload: ChatPayload, signal?: AbortSignal, onProgress?: (message:string)=>void): Promise<AgentAnswer> {
  try {
    if(typeof window!=='undefined')return await streamChat(payload,signal,onProgress)
    return (await apiClient.post('/api/v1/agent/chat', payload, { timeout: 195000, signal })).data.result
  } catch (error) {
    if(error instanceof Error&&!isAxiosError(error))throw error
    if (isAxiosError(error)) {
      const detail = error.response?.data?.msg || error.response?.data?.detail
      if (typeof detail === 'string') throw new Error(detail)
      if (error.response?.status === 422) throw new Error('问题或对话过长，请缩短后重试。')
      if (error.code === 'ECONNABORTED') throw new Error('AI 回答超时，请稍后重试。')
    }
    throw new Error('暂时无法连接问答服务，请检查后端是否启动。')
  }
}

async function streamChat(payload:ChatPayload,signal?:AbortSignal,onProgress?:(message:string)=>void):Promise<AgentAnswer> {
  const controller=new AbortController(),abort=()=>controller.abort()
  if(signal?.aborted)controller.abort()
  signal?.addEventListener('abort',abort,{once:true})
  const timeout=window.setTimeout(abort,195000)
  const names:Record<string,string>={search_plants:'检索植物资料',plant_details:'读取植物详情',recognize_plant_image:'识别植物图片',classify_plant_text:'分类植物文本'}
  try {
    const response=await fetch(new URL('/api/v1/agent/chat/stream',apiClient.defaults.baseURL).href,{
      method:'POST',credentials:'include',signal:controller.signal,
      headers:{'Content-Type':'application/json','X-History-Token':getHistoryToken(),'X-CSRF-Token':getSession().csrfToken||''},body:JSON.stringify(payload)})
    if(!response.ok){const error=await response.json();throw new Error(typeof error.msg==='string'?error.msg:'Agent 服务暂时不可用，请重试')}
    const reader=response.body?.getReader();if(!reader)throw new Error('浏览器未提供响应流，请刷新后重试')
    const decoder=new TextDecoder();let buffer=''
    try {
      while(true){
        const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done})
        if(buffer.length>2*1024*1024)throw new Error('回答内容过大，请缩小问题范围')
        const lines=buffer.split('\n');buffer=lines.pop()||''
        for(const line of lines){
          if(!line.trim())continue
          const event=JSON.parse(line)
          if(event.type==='error')throw new Error(event.message||'执行失败，请重试')
          if(event.type==='result')return event.data as AgentAnswer
          if(event.type==='progress')onProgress?.(event.state==='error'?'工具暂时不可用，正在整理结果…':event.tool?`${event.state==='running'?'正在':'已'}${names[event.tool]||'执行工具'}…`:'正在理解问题…')
        }
        if(done)break
      }
    } finally {await reader.cancel().catch(()=>{});reader.releaseLock()}
    throw new Error('回答连接中断，请稍后重试')
  } catch(error){
    if(controller.signal.aborted&&!signal?.aborted)throw new Error('AI 回答超时，请稍后重试。')
    if(error instanceof TypeError)throw new Error('无法连接 Agent 服务，请稍后重试。')
    throw error
  } finally {window.clearTimeout(timeout);signal?.removeEventListener('abort',abort)}
}
