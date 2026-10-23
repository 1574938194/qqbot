import httpx
import pytest
from openai import AsyncOpenAI

from qqbot.config import Settings
from qqbot.llm import LLM, ModelError


async def test_plain_dialogue_has_no_tool_protocol_and_ignores_unsolicited_calls():
    import json
    def respond(request):
        body = json.loads(request.content)
        assert 'tools' not in body and 'tool_choice' not in body
        assert '结构化JSON协议' not in str(body['messages'])
        return httpx.Response(200, json={'id': 'plain', 'object': 'chat.completion', 'created': 0, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': '我在想你今天过得怎么样。', 'reasoning_content': '不发送',
                'tool_calls': [{'id': 'unexpected', 'type': 'function', 'function': {'name': 'shell', 'arguments': '{'}}]}}]})
    llm = LLM(Settings(api_key='test-only', llm_min_interval=0))
    await llm.client.close()
    llm.client = AsyncOpenAI(api_key='test-only', max_retries=0,
                            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        assert await llm.complete([{'role': 'user', 'content': '你心里在想什么'}]) == '我在想你今天过得怎么样。'
    finally:
        await llm.close()


@pytest.mark.parametrize('kind', ['success', 'empty', 'auth', 'timeout', 'length'])
async def test_model_responses(kind, caplog):
    def respond(request):
        if kind == 'timeout':
            raise httpx.ReadTimeout('secret-key and private chat', request=request)
        if kind == 'auth':
            return httpx.Response(401, json={'error': {'message': 'secret-key and private chat'}})
        return httpx.Response(200, json={
            'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': 'length' if kind == 'length' else 'stop',
                         'message': {'role': 'assistant', 'content': '' if kind == 'empty' else '最终正文', 'reasoning_content': '秘密思考'}}]})
    llm = LLM(Settings(api_key='secret-key'))
    await llm.client.close()
    llm.client = AsyncOpenAI(api_key='secret-key', max_retries=0,
                            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    if kind == 'success':
        assert await llm.complete([{'role': 'user', 'content': 'private chat'}]) == '最终正文'
    else:
        with pytest.raises(ModelError):
            await llm.complete([{'role': 'user', 'content': 'private chat'}])
    assert 'secret-key' not in caplog.text and 'private chat' not in caplog.text
    await llm.close()


async def test_proxy_rate_limit_bounded_retry(caplog):
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(502, json={'error': {'cause': 'rate_limited', 'message': 'secret-key private-text'}})
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '成功'}}]})
    llm = LLM(Settings(api_key='secret-key', llm_min_interval=0, llm_rate_backoff=.01, llm_rate_retries=2))
    await llm.client.close()
    llm.client = AsyncOpenAI(api_key='secret-key', max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    assert await llm.complete([{'role': 'user', 'content': 'private-text'}]) == '成功'
    assert len(calls) == 3
    assert 'secret-key' not in caplog.text and 'private-text' not in caplog.text
    await llm.close()
