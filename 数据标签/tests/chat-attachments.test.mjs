import test from 'node:test'
import assert from 'node:assert/strict'
import { loadSource } from './load-source.mjs'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
const {chatSessionsReducer,chatHistory}=await loadSource('src/utils/chatSessions.ts')
const {parseChatArchive,serializeChatArchive,newConversation,conversationTitle,chatConversationsReducer,conversationHistory}=await loadSource('src/utils/chatConversations.ts')
const image='00000000-0000-0000-0000-000000000001'
const {ChatUserMessage}=await loadSource('src/components/chat/AgentChat.tsx')

test('user messages place the image above text without an empty image-only text bubble',()=>{
 const combined=renderToStaticMarkup(createElement(ChatUserMessage,{message:{role:'user',content:'这是什么',image_record_id:image}}))
 assert.ok(combined.indexOf('chat-message-image')<combined.indexOf('user-bubble'))
 const imageOnly=renderToStaticMarkup(createElement(ChatUserMessage,{message:{role:'user',content:'',image_record_id:image}}))
 assert.match(imageOnly,/chat-message-image/);assert.doesNotMatch(imageOnly,/user-bubble/)
})

test('image-only messages move from pending attachment into sent history',()=>{
 const initial={one:{messages:[],question:'',pendingQuestion:'',error:''}}
 const pending=chatSessionsReducer(initial,{type:'start',key:'one',requestId:1,message:'',image_record_id:image})
 assert.equal(pending.one.pendingImageId,image)
 const sent=chatSessionsReducer(pending,{type:'success',key:'one',requestId:1,answer:'这是植物'})
 assert.equal(sent.one.pendingImageId,undefined)
 assert.deepEqual(sent.one.messages[0],{role:'user',content:'',image_record_id:image})
 assert.ok(chatHistory(sent.one)[0].content.length>0,'wire history is valid for subsequent turns')
})
test('refresh retains image IDs and image-only conversation titles',()=>{
 const conversation={...newConversation({},'one',100),messages:[{role:'user',content:'',image_record_id:image},{role:'assistant',content:'回答'}]}
 const restored=parseChatArchive(serializeChatArchive({activeId:'one',conversations:[conversation]}))
 assert.equal(restored.conversations[0].messages[0].image_record_id,image)
 assert.equal(conversationTitle(restored.conversations[0]),'图片识别')
})
test('completed text turns do not inherit an earlier image attachment',()=>{
 const previous={one:{messages:[{role:'user',content:'',image_record_id:image},{role:'assistant',content:'回答'}],question:'追问',pendingQuestion:'',error:''}}
 const started=chatSessionsReducer(previous,{type:'start',key:'one',requestId:2,message:'追问'})
 const done=chatSessionsReducer(started,{type:'success',key:'one',requestId:2,answer:'后续回答'})
 assert.equal(done.one.messages[2].image_record_id,undefined)
})
test('switching conversations and refreshing history retain an in-flight image-only turn',()=>{
 let archive={activeId:'one',conversations:[{...newConversation({},'one',100),requestId:1,pendingImageId:image}]}
 assert.equal(conversationHistory(archive).length,1)
 archive=chatConversationsReducer(archive,{type:'create',conversation:newConversation({},'two',200)})
 assert.equal(archive.conversations.length,2)
 archive=chatConversationsReducer(archive,{type:'hydrate',conversations:[newConversation({},'one',100)]})
 assert.equal(archive.conversations.find(x=>x.id==='one').pendingImageId,image)
 archive=chatConversationsReducer(archive,{type:'session',now:300,action:{type:'success',key:'one',requestId:1,answer:'回答'}})
 assert.equal(archive.conversations.find(x=>x.id==='one').messages[0].image_record_id,image)
})
