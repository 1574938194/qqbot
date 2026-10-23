import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from qqbot.config import ADMIN, Settings
from qqbot.llm import ModelError
from qqbot.qwenpaw_client import QwenPaw, QwenReply, final_content
from qqbot.qwenpaw_media import collect, local_path
from qqbot.service import Service
from qqbot.store import Store


def response(text='任务已完成', *, status='completed'):
    return {'object': 'response', 'status': status, 'output': [
        {'role': 'assistant', 'type': 'reasoning', 'status': 'completed', 'content': [{'type': 'text', 'text': '隐藏思考'}]},
        {'role': 'assistant', 'type': 'function_call', 'status': 'completed', 'content': [{'type': 'text', 'text': '隐藏协议'}]},
        {'role': 'assistant', 'type': 'message', 'status': 'completed', 'content': [{'type': 'text', 'text': text}]}]}


def test_final_body_excludes_reasoning_and_tools():
    result = response()
    result['output'].append({'role': 'assistant', 'type': 'message', 'status': 'completed',
        'content': [{'type': 'file', 'file_url': 'file:///state/result.txt', 'filename': 'result.txt'}]})
    reply = final_content(result)
    assert isinstance(reply, QwenReply) and reply == '任务已完成'
    assert len(reply.parts) == 1 and reply.parts[0]['filename'] == 'result.txt'
    assert '隐藏' not in reply
    with pytest.raises(ModelError):
        final_content(response(status='failed'))


def test_native_file_tool_output_only_yields_explicit_successful_attachment():
    result = response('报告已完成')
    call = {'type': 'plugin_call', 'role': 'assistant', 'status': 'completed', 'content': [
        {'type': 'data', 'data': {'call_id': 'file-1', 'name': 'send_file_to_user', 'arguments': '隐藏参数'}}]}
    sent = {'type': 'plugin_call_output', 'role': 'tool', 'status': 'completed', 'content': [
        {'type': 'data', 'data': {'call_id': 'file-1', 'name': 'send_file_to_user', 'state': 'success',
            'output': json.dumps([{'type': 'data', 'source': {'type': 'url',
                'url': 'file:///state/qwenpaw/workspaces/qq-12345/files/report.txt', 'media_type': 'text/plain'}},
                {'type': 'text', 'text': '隐藏工具正文'}])}}]}
    result['output'] = [call, sent] + result['output']
    reply = final_content(result)
    assert reply == '报告已完成' and len(reply.parts) == 1
    assert reply.parts[0]['type'] == 'file'
    sent['content'][0]['data']['state'] = 'error'
    assert not final_content(result).parts
    sent['content'][0]['data']['state'] = 'success'
    call['content'][0]['data']['call_id'] = 'different'
    assert not final_content(result).parts


@pytest.fixture
def setup(tmp_path):
    store = Store(str(tmp_path / 'test.db'))
    config = Settings(agent_backend='qwenpaw', qwenpaw_token='test-token', qwenpaw_files=str(tmp_path))
    llm = SimpleNamespace(complete=AsyncMock())
    tasks = SimpleNamespace(tools=SimpleNamespace(shell_enabled=lambda: True), command=AsyncMock(return_value='任务已完成'))
    service = Service(store, llm, config, tasks=tasks)
    app = FastAPI()
    calls = []
    current = {'response': response(), 'entered': None, 'release': None}

    @app.post('/api/qqbot/sync')
    async def sync(request: Request):
        assert request.headers['x-qqbot-token'] == 'test-token'
        calls.append(('sync', await request.json()))
        return {'agent_id': 'qq-' + str(ADMIN)}

    @app.post('/api/agents/{agent_id}/console/chat')
    async def chat(agent_id: str, request: Request):
        calls.append(('chat', agent_id, await request.json()))
        if current['entered']:
            current['entered'].set()
            await current['release'].wait()
        async def stream():
            yield 'data: ' + json.dumps(current['response'], ensure_ascii=False) + '\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream')

    @app.post('/api/agents/{agent_id}/console/chat/stop')
    async def stop(agent_id: str, request: Request):
        calls.append(('stop', agent_id, dict(request.query_params)))
        current['response'] = response(status='cancelled')
        if current['release']:
            current['release'].set()
        return {'stopped': True}

    service.qwen.client = lambda **kwargs: httpx.AsyncClient(transport=httpx.ASGITransport(app),
        base_url='http://127.0.0.1:8088', headers={'X-QQBot-Token': 'test-token'})
    yield service, calls, current
    store.close()


async def test_natural_tasks_use_qwenpaw_and_preserve_prompt_and_isolation(setup):
    service, calls, _ = setup
    prompt = '  原文人设\r\n保留换行  \r\n'
    service.store.set_prompt(prompt)
    service.store.append(ADMIN, '迁移前的问题', '迁移前的回复')
    service.store.append(12345, '其他用户的秘密', '不能共享')
    assert await service.handle(12345, '未授权用户任务') is None
    assert await service.handle(ADMIN, '帮我打开网页并写一份报告') == '任务已完成'
    data = calls[0][1]
    assert data['prompt'] == prompt and data['execute'] is True
    assert data['history'] == [{'用户': '迁移前的问题', '助手': '迁移前的回复'}]
    assert '其他用户' not in json.dumps(data, ensure_ascii=False)
    assert not service.llm.complete.called
    assert len(service.store.history(ADMIN)) == 2
    await service.handle(ADMIN, '接着刚才的报告修改标题')
    chats = [c for c in calls if c[0] == 'chat']
    assert chats[0][2]['session_id'] == chats[1][2]['session_id']
    assert len([c for c in calls if c[0] == 'sync']) == 1


async def test_commands_and_failed_response_not_saved(setup):
    service, calls, state = setup
    assert await service.handle(ADMIN, '/task run 帮我写文件') == '任务已完成'
    assert not service.store.history(ADMIN)
    assert service.tasks.command.called and not calls
    count = len(calls)
    assert '未知命令' in await service.handle(ADMIN, '/unknown')
    assert len(calls) == count
    state['response'] = response(status='failed')
    assert '未正常完成' in await service.handle(ADMIN, '再做一个任务')
    assert not service.store.history(ADMIN)


async def test_reset_waits_for_chat_then_clears_both_histories(setup):
    service, calls, state = setup
    state['entered'], state['release'] = asyncio.Event(), asyncio.Event()
    chat = asyncio.create_task(service.handle(ADMIN, '写一个文件'))
    await state['entered'].wait()
    reset = asyncio.create_task(service.handle(ADMIN, '/chat reset'))
    await asyncio.sleep(.01)
    assert not reset.done()
    state['release'].set()
    await chat
    assert '已清空' in await reset
    assert not service.store.history(ADMIN) and not service.store.summary(ADMIN)
    assert calls[-1][0] == 'sync' and calls[-1][1]['reset'] is True
    assert calls[-1][1]['history'] == []


async def test_stop_interrupts_without_waiting_for_user_lock(setup):
    service, calls, state = setup
    state['entered'], state['release'] = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(service.handle(ADMIN, '执行长任务'))
    await state['entered'].wait()
    assert '已停止' in await asyncio.wait_for(service.handle(ADMIN, '/task stop'), 1)
    assert '未正常完成' in await task
    assert not service.store.history(ADMIN)
    assert calls[-1][0] == 'stop'


async def test_whitelisted_user_tools_disabled_in_backend(setup):
    service, calls, _ = setup
    service.store.grant(12345, True)
    await service.handle(12345, '你好')
    assert calls[0][1]['uid'] == 12345 and calls[0][1]['execute'] is False
    assert calls[1][1] == 'qq-12345'


async def test_artifact_file_scope_and_size(tmp_path):
    config = Settings(qwenpaw_files=str(tmp_path))
    own = tmp_path / 'qwenpaw/workspaces' / ('qq-' + str(ADMIN)) / 'files'
    own.mkdir(parents=True)
    (own / '报告.txt').write_text('实际成果', encoding='utf-8')
    source = f'file:///state/qwenpaw/workspaces/qq-{ADMIN}/files/报告.txt'
    part = {'type': 'file', 'file_url': source, 'filename': '../报告.txt'}
    files = await collect(ADMIN, [part, part], config)
    assert len(files) == 1 and files[0]['name'] == '报告.txt'
    assert files[0]['data'].decode() == '实际成果'
    with pytest.raises(ValueError):
        local_path(12345, source, config)
    with pytest.raises(ModelError):
        await collect(ADMIN, [{**part, 'file_url': 'file:///etc/passwd'}], config)


@pytest.mark.parametrize('url', ['https://example.com', 'http://8.8.8.8:8088', 'http://127.0.0.1:8088/path'])
def test_qwenpaw_endpoint_is_loopback_only(url):
    with pytest.raises(ValueError, match='QWENPAW_BASE_URL'):
        Settings(qwenpaw_base_url=url)
