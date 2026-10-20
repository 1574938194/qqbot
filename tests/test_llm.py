import httpx
import pytest
from openai import AsyncOpenAI

from qqbot.config import Settings
from qqbot.llm import LLM, ModelError


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


async def test_tool_roundtrip_discards_reasoning():
    requests = []
    def respond(request):
        import json
        payload = json.loads(request.content)
        requests.append(payload)
        message = ({'role': 'assistant', 'content': None, 'reasoning_content': '不可输出的思考',
                    'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'calculate', 'arguments': '{"expression":"2+3"}'}}]}
                   if len(requests) == 1 else {'role': 'assistant', 'content': '结果5', 'reasoning_content': '不可输出的思考'})
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls' if len(requests) == 1 else 'stop', 'message': message}]})
    llm = LLM(Settings(api_key='test-only', llm_tool_mode='native', llm_min_interval=0))
    await llm.client.close()
    llm.client = AsyncOpenAI(api_key='test-only', max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    tools = [{'type': 'function', 'function': {'name': 'calculate', 'parameters': {'type': 'object', 'properties': {'expression': {'type': 'string'}}}}}]
    messages = [{'role': 'user', 'content': '计算2+3'}]
    turn = await llm.respond(messages, tools=tools)
    assert turn.tool_calls[0]['function']['name'] == 'calculate'
    assert 'reasoning_content' not in turn.message()
    messages.extend([turn.message(), {'role': 'tool', 'tool_call_id': 'call_1', 'content': '5'}])
    final = await llm.respond(messages, tools=tools)
    assert final.content == '结果5'
    assert '不可输出的思考' not in str(requests)
    await llm.close()


@pytest.mark.parametrize('mode', ['json', 'single'])
async def test_compatible_tool_protocols(mode):
    import json
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            if mode == 'json':
                assert 'tools' not in payload
                message = {'role': 'assistant', 'content': json.dumps({'tool_calls': [{'name': 'calculate', 'arguments': {'expression': '2+3'}}]})}
            else:
                assert payload['tools'][0]['function']['name'] == 'invoke_tool'
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function',
                    'function': {'name': 'invoke_tool', 'arguments': json.dumps({'name': 'calculate', 'arguments_json': '{"expression":"2+3"}'})}}]}
        else:
            if mode == 'json':
                assert all(m['role'] != 'tool' for m in payload['messages'])
                assert '代码执行的工具结果' in payload['messages'][-1]['content']
            else:
                assert payload['messages'][-2]['tool_calls'][0]['function']['name'] == 'invoke_tool'
            message = {'role': 'assistant', 'content': json.dumps({'final': '结果5'}, ensure_ascii=False) if mode == 'json' else '结果5'}
        message['reasoning_content'] = '秘密思考'
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': message}]})
    llm = LLM(Settings(api_key='test', llm_tool_mode=mode, llm_min_interval=0))
    await llm.client.close()
    llm.client = AsyncOpenAI(api_key='test', max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    from qqbot.task_tools import TOOLS
    messages = [{'role': 'system', 'content': '测试'}, {'role': 'user', 'content': '计算2+3'}]
    first = await llm.respond(messages, tools=TOOLS)
    assert first.tool_calls[0]['function']['name'] == 'calculate'
    messages.extend([first.message(), {'role': 'tool', 'tool_call_id': first.tool_calls[0]['id'], 'content': '5'}])
    final = await llm.respond(messages, tools=TOOLS)
    assert final.content == '结果5' and not final.tool_calls
    assert '秘密思考' not in str(requests)
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


@pytest.mark.parametrize('body,allow_plain,expected', [
    ('我叫小暖呀，很高兴陪你聊天。', True, '我叫小暖呀，很高兴陪你聊天。'),
    ('[CQ:at,qq=123]按普通文本发送', True, '[CQ:at,qq=123]按普通文本发送'),
    ('我叫小暖呀。', False, None),
    ('{"final":"我叫小暖呀。"}', True, '我叫小暖呀。'),
    ('{"final":', True, None),
    ('{"tool_calls": [', True, None),
    ('下面调用工具：{"tool_calls":[]}', True, None),
    ('```json\n{"tool_calls":\n```', True, None),
    ('["正文"]', True, None),
])
async def test_chat_plain_body_fallback_rejects_broken_protocol(body, allow_plain, expected):
    def respond(request):
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': body, 'reasoning_content': '不可发送的思考'}}]})
    llm = LLM(Settings(api_key='test', llm_min_interval=0))
    await llm.client.close()
    llm.client = AsyncOpenAI(api_key='test', max_retries=0,
                            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    from qqbot.task_tools import TOOLS
    try:
        if expected is None:
            with pytest.raises(ModelError):
                await llm.respond([{'role': 'user', 'content': '你叫什么名字呀'}], tools=TOOLS, allow_plain=allow_plain)
        else:
            result = await llm.respond([{'role': 'user', 'content': '你叫什么名字呀'}], tools=TOOLS, allow_plain=allow_plain)
            assert result.content == expected and not result.tool_calls
            assert '不可发送的思考' not in result.content
    finally:
        await llm.close()
