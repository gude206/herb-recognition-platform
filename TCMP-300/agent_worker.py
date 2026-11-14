"""Celery worker: only an allowlisted tool name and validated owner data are accepted."""
import asyncio
from functools import lru_cache
from fastapi import HTTPException
from agent_queue import application
app=application()

@lru_cache(maxsize=1)
def predictor():
    from api import Predictor,DEFAULT_CHECKPOINT
    return Predictor(str(DEFAULT_CHECKPOINT))

@app.task(name='herb.execute_tool')
def execute_tool(name,arguments,owner):
    from agent_service import build_tools,settings,TOOL_NAMES
    if name not in TOOL_NAMES:return {'_error':True,'code':404,'message':'ToolNotFound'}
    # The API owns the retry budget; workers neither requeue nor dispatch recursively.
    tools={t.name:t for t in build_tools(settings(),owner,predictor() if name=='recognize_plant_image' else None,[],allow_queue=False,retry=False)}
    try:
        value=asyncio.run(tools[name].ainvoke(arguments))
        if 'error' in value:return {'_error':True,'code':value['code'],'message':value['error']}
        return value
    except HTTPException as error:return {'_error':True,'code':error.status_code,'message':str(error.detail)}
