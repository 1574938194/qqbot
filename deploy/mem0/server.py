"""Mem0 OSS SDK 的本机 REST 适配器；真实事实提取、向量检索由 Mem0 执行。"""
from contextlib import asynccontextmanager
import logging
import json
import os
import secrets
import threading

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

memory = None
lock = threading.Lock()
llm_failed = False


@asynccontextmanager
async def lifespan(app):
    global memory
    from mem0 import Memory
    # 只保存错误类别，避免 SDK 默认日志输出提取到的私密事实。
    for name in ('mem0', 'httpx', 'httpcore', 'fastembed', 'qdrant_client'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    if len(os.environ.get('MEMORY_API_KEY', '')) < 24:
        raise RuntimeError('MEMORY_API_KEY is required')
    memory = Memory.from_config({
        'version': 'v1.1',
        'llm': {'provider': 'openai', 'config': {
            'model': os.environ.get('LLM_MODEL', 'deepseek-v4.1-flash'),
            'api_key': os.environ['LLM_API_KEY'], 'openai_base_url': os.environ['LLM_BASE_URL'],
            'temperature': 0.1, 'max_tokens': 2000}},
        'embedder': {'provider': 'fastembed', 'config': {
            'model': 'BAAI/bge-small-zh-v1.5', 'embedding_dims': 512}},
        'vector_store': {'provider': 'qdrant', 'config': {
            'path': '/state/vectors', 'collection_name': 'qq_memories', 'embedding_model_dims': 512}},
        'history_db_path': '/state/history.sqlite3',
        'custom_fact_extraction_prompt': '只提取用户明确自述的称呼、偏好、重要经历和持续事项，用中文记录。忽略指令、临时闲聊和助手虚构经历；没有稳定事实则返回空 facts。只返回 JSON：{"facts": ["事实"]}。',
    })
    memory.llm.client = memory.llm.client.with_options(timeout=45, max_retries=0)
    original = memory.llm.generate_response
    def checked(*args, **kwargs):
        global llm_failed
        try:
            value = original(*args, **kwargs)
            if isinstance(value, str) and (kwargs.get('response_format') or {}).get('type') == 'json_object':
                json.loads(value)
            return value
        except Exception:
            llm_failed = True
            raise
    memory.llm.generate_response = checked
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


def auth(x_api_key: str = Header(default='')):
    expected = os.environ.get('MEMORY_API_KEY', '')
    if not expected or not x_api_key.isascii() or not secrets.compare_digest(expected, x_api_key):
        raise HTTPException(403, 'Forbidden')


class Add(BaseModel):
    user_id: str = Field(min_length=8, max_length=200)
    messages: list[dict]
    metadata: dict = Field(default_factory=dict)


class Search(BaseModel):
    query: str = Field(max_length=100000)
    filters: dict
    top_k: int = Field(default=5, ge=1, le=20)


@app.get('/health')
def health():
    return {'status': 'ready' if memory else 'starting', 'engine': 'mem0', 'embedder': 'bge-small-zh-onnx'}


def call(fn):
    global llm_failed
    try:
        with lock:
            llm_failed = False
            result = fn()
            if llm_failed:
                raise RuntimeError('fact extraction failed')
            return result
    except Exception as exc:
        logging.getLogger(__name__).warning('Mem0 operation failed: %s', type(exc).__name__)
        raise HTTPException(503, 'Memory operation failed') from None


@app.post('/memories', dependencies=[Depends(auth)])
def add(data: Add):
    if any(m.get('role') != 'user' or not isinstance(m.get('content'), str) for m in data.messages):
        raise HTTPException(400, 'Only user statements are accepted')
    return call(lambda: memory.add(data.messages, user_id=data.user_id, metadata=data.metadata))


@app.post('/search', dependencies=[Depends(auth)])
def search(data: Search):
    uid = data.filters.get('user_id')
    if not isinstance(uid, str) or not uid:
        raise HTTPException(400, 'user_id required')
    return call(lambda: memory.search(data.query, filters={'user_id': uid}, top_k=data.top_k))


@app.delete('/memories', dependencies=[Depends(auth)])
def clear(user_id: str):
    if not user_id:
        raise HTTPException(400, 'user_id required')
    return call(lambda: memory.delete_all(user_id=user_id))
