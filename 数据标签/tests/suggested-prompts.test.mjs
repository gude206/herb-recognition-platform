import test from 'node:test'
import assert from 'node:assert/strict'
import { loadSource } from './load-source.mjs'
const {CHAT_PROMPT_POOL,selectSuggestedPrompts,initialSuggestedPrompts,rememberSuggestedPrompts}=await loadSource('src/utils/suggestedPrompts.ts')

test('15 unique suggestions produce exactly 3 unique questions and avoid the previous group',()=>{
 assert.equal(CHAT_PROMPT_POOL.length,15)
 assert.equal(new Set(CHAT_PROMPT_POOL).size,15)
 const first=selectSuggestedPrompts([],()=>0.25)
 const next=selectSuggestedPrompts(first,()=>0.25)
 assert.equal(first.length,3);assert.equal(new Set(next).size,3)
 assert.ok(next.every(x=>CHAT_PROMPT_POOL.includes(x)&&!first.includes(x)))
})

test('refresh reads the previous suggestions; storage failure and malformed data stay usable',()=>{
 const original=global.sessionStorage
 let stored='invalid json'
 global.sessionStorage={getItem:()=>stored,setItem:(_,value)=>{stored=value}}
 try{
  const first=initialSuggestedPrompts();rememberSuggestedPrompts(first)
  assert.ok(initialSuggestedPrompts().every(x=>!first.includes(x)))
  stored=JSON.stringify(CHAT_PROMPT_POOL)
  assert.equal(initialSuggestedPrompts().length,3)
  global.sessionStorage={getItem:()=>{throw new Error('unavailable')},setItem:()=>{throw new Error('unavailable')}}
  assert.equal(initialSuggestedPrompts().length,3)
  assert.doesNotThrow(()=>rememberSuggestedPrompts(first))
 }finally{if(original===undefined)delete global.sessionStorage;else global.sessionStorage=original}
})
