"""Optional Redis/Celery tool execution; direct mode remains explicit for local use."""
import asyncio,os
from functools import lru_cache
from pathlib import Path
from celery import Celery
from dotenv import dotenv_values
from fastapi import HTTPException

def config():return {**dotenv_values(Path(__file__).with_name('.env')),**os.environ}
def queue_enabled():return str(config().get('AGENT_QUEUE_ENABLED','false')).lower() in {'true','1','yes'}

@lru_cache(maxsize=1)
def application():
    cfg=config()
    app=Celery('herb_agent',broker=cfg.get('CELERY_BROKER_URL','redis://127.0.0.1:6379/0'),
               backend=cfg.get('CELERY_RESULT_BACKEND','redis://127.0.0.1:6379/1'),include=['agent_worker'])
    app.conf.update(task_serializer='json',result_serializer='json',accept_content=['json'],
        result_expires=300,task_soft_time_limit=110,task_time_limit=120,worker_prefetch_multiplier=1,
        task_acks_late=True,task_reject_on_worker_lost=True,task_default_queue='herb_tools',
        broker_connection_retry_on_startup=True,broker_transport_options={'priority_steps':list(range(10)),'queue_order_strategy':'priority'})
    return app

async def dispatch_tool(name,arguments,owner):
    def wait():
        try:
            result=application().send_task('herb.execute_tool',args=[name,arguments,owner],
                         priority=0 if name=='recognize_plant_image' else 5,expires=120)
            value=result.get(timeout=120)
            if value.get('_error'):raise HTTPException(value['code'],value['message'])
            return value
        except HTTPException:raise
        except Exception:raise HTTPException(503,'工具队列暂时不可用，请稍后重试') from None
    return await asyncio.to_thread(wait)
