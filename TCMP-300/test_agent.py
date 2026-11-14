"""Exercise the actual LangChain graph with deterministic, non-billable models."""
import asyncio
import os
import unittest
from unittest.mock import patch,Mock,AsyncMock
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from api import app
import agent_service as service

class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self,tools,**kwargs):return self

class AgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,MYSQL_ENABLED='false');self.env.start();self.addCleanup(self.env.stop)
    async def invoke(self,name=None,args=None,**kwargs):
        messages=([AIMessage(content='',tool_calls=[dict(name=name,args=args or {},id='call1')])] if name else [])+[AIMessage(content='测试回答')]
        with patch.object(service,'model_for',return_value=ScriptedModel(responses=messages)):
            return await service.generate_agent('测试问题',{'model':'test-scripted'},None,[],kwargs.get('owner'),kwargs.get('predictor',Mock()))
    async def test_search_uses_public_catalogue(self):
        result=await self.invoke('search_plants',{'query':'紫苏'})
        self.assertEqual(result['tool_calls'][0]['name'],'search_plants')
        self.assertTrue(any(x['id']=='tcmp-298' for x in result['tool_calls'][0]['result']['items']))
    async def test_detail_retains_sources_and_hides_conflict(self):
        result=await self.invoke('plant_details',{'plant_id':'tcmp-298'})
        self.assertTrue(result['tool_calls'][0]['result']['sources'])
        result=await self.invoke('plant_details',{'plant_id':'tcmp-051'})
        self.assertEqual(result['tool_calls'][0]['result']['code'],404)
    async def test_classifier_tool_runs(self):
        with patch.object(service,'classify_text',new=AsyncMock(return_value={'label':'植物形态'})) as classify:
            result=await self.invoke('classify_plant_text',{'text':'叶片呈卵形，边缘有锯齿'})
        classify.assert_awaited_once();self.assertEqual(result['tool_calls'][0]['result']['label'],'植物形态')
    async def test_no_tool_is_valid_for_general_chat(self):
        self.assertEqual((await self.invoke())['tool_calls'],[])
    async def test_unknown_tool_is_reported(self):
        result=await self.invoke('nonexistent',{})
        self.assertEqual(result['tool_calls'][0]['result']['message'],'ToolNotFound')
    async def test_image_tool_denies_other_owner(self):
        predictor=Mock()
        with patch.object(service.history_store,'recognition_image',side_effect=HTTPException(404,'未找到该识别记录')):
            result=await self.invoke('recognize_plant_image',{'image_record_id':'00000000-0000-0000-0000-000000000001'},owner='other',predictor=predictor)
        predictor.predict.assert_not_called();self.assertEqual(result['tool_calls'][0]['result']['code'],404)
    async def test_image_tool_never_reads_arbitrary_paths(self):
        result=await self.invoke('recognize_plant_image',{'image_record_id':'C:/Users/private.png'},owner='owner')
        self.assertEqual(result['tool_calls'][0]['result']['code'],400)
    async def test_retry_budget_is_three_retries(self):
        operation=AsyncMock(side_effect=[HTTPException(503,'temporary')]*3+[{'ok':True}])
        self.assertEqual(await service.retry_tool(operation,sleep=AsyncMock()),{'ok':True})
        self.assertEqual(operation.await_count,4)
    async def test_access_errors_never_retry(self):
        operation=AsyncMock(side_effect=HTTPException(404,'missing'))
        with self.assertRaises(HTTPException):await service.retry_tool(operation,sleep=AsyncMock())
        self.assertEqual(operation.await_count,1)
    async def test_multi_round_uses_saved_tool_context(self):
        model=ScriptedModel(responses=[AIMessage(content='这是之前的图片')])
        history=[{'role':'assistant','content':'识别完成','references_json':'{"tool_calls":[{"name":"recognize_plant_image","arguments":{"image_record_id":"previous-image"}}]}'}]
        with patch.object(service,'model_for',return_value=model),patch.object(service,'create_agent',wraps=service.create_agent) as create:
            await service.generate_agent('它的叶片呢？',{'model':'test-scripted'},None,history,'owner',Mock())
        self.assertIn('previous-image',create.call_args.kwargs['system_prompt'])

class AgentAPITests(unittest.TestCase):
    def test_stream_progress_result_and_error_protocol(self):
        async def answer(*args):
            emit=args[-1]
            await emit({'type':'progress','tool':'search_plants','state':'running'})
            return {'answer':'查到了','references':[],'model':'test','tool_calls':[]}
        with patch.dict(os.environ,MYSQL_ENABLED='false'),patch.object(app.state,'predictor',Mock(),create=True), \
             patch.object(service,'settings',return_value={'model':'test'}),patch.object(service,'generate_agent',side_effect=answer):
            with patch.dict(os.environ,MYSQL_ENABLED='false'):
                client=TestClient(app);self.addCleanup(client.close)
                response=client.post('/api/v1/agent/chat/stream',json={'message':'查紫苏'})
                import json
                events=[json.loads(line) for line in response.text.splitlines()]
                self.assertEqual(events[-1]['type'],'result')
                self.assertTrue(any(e.get('tool')=='search_plants' for e in events))
                with patch.object(service,'generate_agent',side_effect=HTTPException(504,'请重试')):
                    response=client.post('/api/v1/agent/chat/stream',json={'message':'查紫苏'})
                    self.assertEqual(json.loads(response.text.splitlines()[-1])['code'],504)

    def test_input_boundaries_and_error_redaction(self):
        with patch.dict(os.environ,MYSQL_ENABLED='false'):
            client=TestClient(app)
            self.addCleanup(client.close)
            self.assertEqual(client.post('/api/v1/agent/chat',json={'message':' '}).status_code,422)
            self.assertEqual(client.post('/api/v1/agent/chat',content=b'x'*70000).status_code,413)
            with patch.object(service,'settings',side_effect=RuntimeError('sensitive-test-value-do-not-return')):
                result=client.post('/api/v1/agent/chat',json={'message':'你好'})
                self.assertEqual(result.status_code,502);self.assertNotIn('sensitive-test-value',result.text)

if __name__=='__main__':unittest.main()
