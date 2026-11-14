import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { loadSource } from './load-source.mjs'
const { sendChat }=await loadSource('src/api/chat.ts')
const { AgentToolCalls }=await loadSource('src/components/chat/AgentChat.tsx')
const {chatSessionsReducer}=await loadSource('src/utils/chatSessions.ts')

test('Agent stream decodes split UTF8, emits execution progress and retains final tool results',async()=>{
 const originalFetch=global.fetch,originalWindow=global.window
 const events=[{type:'progress',tool:'search_plants',state:'running'},{type:'result',data:{answer:'紫苏叶片有锯齿',tool_calls:[{name:'search_plants',status:'success'}]}}]
 const bytes=new TextEncoder().encode(events.map(x=>JSON.stringify(x)).join('\n')+'\n')
 let requested
 global.window={setTimeout,clearTimeout}
 global.fetch=async(url,options)=>{requested={url,options};return new Response(new ReadableStream({start(controller){for(let i=0;i<bytes.length;i+=7)controller.enqueue(bytes.slice(i,i+7));controller.close()}}))}
 try {
  const progress=[];const answer=await sendChat({message:'查紫苏'},undefined,x=>progress.push(x))
  assert.equal(answer.answer,'紫苏叶片有锯齿');assert.equal(answer.tool_calls[0].name,'search_plants')
  assert.match(progress[0],/正在检索植物资料/)
  assert.match(requested.url,/agent\/chat\/stream$/);assert.equal(requested.options.credentials,'include')
  assert.match(requested.options.headers['X-History-Token'],/^[a-f0-9]{64}$/)
 } finally {global.fetch=originalFetch;if(originalWindow===undefined)delete global.window;else global.window=originalWindow}
})

test('tool progress is isolated by request identity and clears on completion',()=>{
 const sessions={one:{messages:[],question:'',pendingQuestion:'问题',error:'',requestId:2}}
 assert.equal(chatSessionsReducer(sessions,{type:'progress',key:'one',requestId:1,message:'过期'}),sessions)
 const running=chatSessionsReducer(sessions,{type:'progress',key:'one',requestId:2,message:'正在识别'})
 const complete=chatSessionsReducer(running,{type:'success',key:'one',requestId:2,answer:'紫苏',tool_calls:[{name:'recognize_plant_image',status:'success'}]})
 assert.equal(complete.one.progress,undefined);assert.equal(complete.one.messages[1].tool_calls[0].name,'recognize_plant_image')
})

test('tool output renders as escaped text with a user-facing execution label',()=>{
 const markup=renderToStaticMarkup(createElement(AgentToolCalls,{calls:[{id:'one',name:'search_plants',status:'success',result:{text:'<script>alert(1)</script>'},arguments:{}}]}))
 assert.match(markup,/检索植物资料/);assert.doesNotMatch(markup,/<script>/);assert.match(markup,/&lt;script&gt;/)
})
