"""History endpoints are isolated by an opaque browser token, not demo login."""
import math
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

import herb_catalog
import history_store
from auth_api import request_history_owner

router = APIRouter(prefix='/api/v1/history', tags=['MySQL 历史记录'])


history_owner = request_history_owner


class ConversationContext(BaseModel):
    herbId: str | None = Field(default=None, pattern=r'^tcmp-\d{3}$')
    name: str | None = Field(default=None, max_length=120)
    identityConflict: bool = False


class NewConversation(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9-]{1,80}$')
    context: ConversationContext = Field(default_factory=ConversationContext)


def verified_context(context):
    if not context.herbId:
        return {}
    row = herb_catalog.rows().get(context.herbId)
    if row is None:
        raise HTTPException(404, '未找到该植物参考')
    return dict(herbId=context.herbId, name=row['Chinese Name'].strip(),
                identityConflict=bool(herb_catalog.identity_metadata(row)['identity_conflict']))


class ImportedMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(default='',max_length=20000)
    image_record_id: uuid.UUID | None = None

    @model_validator(mode='after')
    def valid_content(self):
        if not self.content.strip() and not (self.role=='user' and self.image_record_id):raise ValueError('消息不能为空')
        if self.role=='assistant' and self.image_record_id:raise ValueError('图片附件只能属于用户消息')
        return self


class ImportedConversation(NewConversation):
    messages: list[ImportedMessage] = Field(max_length=2000)
    createdAt: float
    updatedAt: float

    @field_validator('createdAt', 'updatedAt')
    @classmethod
    def timestamp_in_range(cls, value):
        if not math.isfinite(value) or not 0 <= value <= 253402300799000:
            raise ValueError('无效的历史时间')
        return value

    @model_validator(mode='after')
    def complete_turns(self):
        if len(self.messages) % 2 or any(message.role != ('assistant' if index % 2 else 'user')
            for index, message in enumerate(self.messages)):
            raise ValueError('历史记录必须是完整的问答对')
        return self


class ImportRequest(BaseModel):
    conversations: list[ImportedConversation] = Field(max_length=100)


@router.get('/conversations')
def conversations(owner=Depends(history_owner), page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100),
                  q: str = Query('', max_length=200)):
    return history_store.list_conversations(owner, page, page_size, q.strip())


@router.post('/conversations', status_code=201)
def create_conversation(payload: NewConversation, owner=Depends(history_owner)):
    history_store.create_conversation(owner, payload.id, verified_context(payload.context))
    return dict(id=payload.id, saved=True)


@router.post('/import')
def import_history(payload: ImportRequest, owner=Depends(history_owner)):
    for conversation in payload.conversations:
        for message in conversation.messages:
            if message.image_record_id:history_store.recognition_image(owner,str(message.image_record_id))
    entries = [dict(id=item.id, context=verified_context(item.context),
                    createdAt=item.createdAt, updatedAt=item.updatedAt,
                    messages=[message.model_dump(mode='json') for message in item.messages]) for item in payload.conversations]
    return dict(imported=history_store.import_conversations(owner, entries))


@router.get('/recognitions')
def recognitions(owner=Depends(history_owner), q: str = Query('', max_length=200),
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=60)):
    return history_store.list_recognitions(owner, q.strip(), page, page_size)


@router.get('/recognitions/{record_id}/image')
def recognition_image(record_id: str, owner=Depends(history_owner)):
    path, mime = history_store.recognition_image(owner, record_id)
    return FileResponse(path, media_type=mime, headers={'Cache-Control': 'private, no-store'})
