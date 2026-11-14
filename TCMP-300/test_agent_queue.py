import asyncio,os,unittest
from unittest.mock import Mock,patch
from fastapi import HTTPException
import agent_queue,agent_worker,agent_service

class QueueTests(unittest.TestCase):
    def test_image_jobs_have_priority_and_wait_is_bounded(self):
        app=Mock();app.send_task.return_value.get.return_value={'prediction':{}}
        with patch.object(agent_queue,'application',return_value=app):
            self.assertEqual(asyncio.run(agent_queue.dispatch_tool('recognize_plant_image',{'image_record_id':'id'},'owner')),{'prediction':{}})
        self.assertEqual(app.send_task.call_args.kwargs['priority'],0)
        app.send_task.return_value.get.assert_called_once_with(timeout=120)
    def test_worker_allowlist_blocks_unknown_operations(self):
        self.assertEqual(agent_worker.execute_tool.run('run_shell',{},'owner')['code'],404)
    def test_worker_uses_direct_tool_instead_of_recursively_enqueuing(self):
        with patch.dict(os.environ,MYSQL_ENABLED='false',AGENT_QUEUE_ENABLED='true'), \
             patch.object(agent_service,'settings',return_value={'model':'test'}), \
             patch.object(agent_queue,'dispatch_tool',side_effect=AssertionError('nested dispatch')):
            result=agent_worker.execute_tool.run('search_plants',{'query':'紫苏'},'owner')
        self.assertTrue(any(x['id']=='tcmp-298' for x in result['items']))
    def test_broker_failure_is_sanitized(self):
        app=Mock();app.send_task.side_effect=RuntimeError('redis://secret-password@example.test')
        with patch.object(agent_queue,'application',return_value=app):
            with self.assertRaises(HTTPException) as caught:asyncio.run(agent_queue.dispatch_tool('search_plants',{},'owner'))
        self.assertEqual(caught.exception.status_code,503);self.assertNotIn('secret-password',str(caught.exception.detail))
