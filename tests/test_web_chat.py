import asyncio
import base64
import json
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image

from qqbot.config import ADMIN, Settings
from qqbot.profile import Profile
from qqbot.prompt_upload import MAX_BYTES, PromptUpload
from qqbot.service import Service
from qqbot.store import Store
from qqbot.web_chat import WEB_BOT_ID, WebChat
from qqbot.media import Media


@pytest.fixture
def setup(tmp_path):
    store = Store(str(tmp_path / 'web.db'))
    llm = SimpleNamespace(complete=AsyncMock(return_value='<script>正文</script>'))
    service = Service(store, llm, Settings())
    profile = Profile(store)
    upload = PromptUpload(store, service.config.context_tokens)
    media = SimpleNamespace(command=AsyncMock(return_value=b'RIFF-test-wave'))
    bots = {}
    app = FastAPI()
    web = WebChat(app, lambda: (service, profile, media, upload), lambda: bots)
    yield app, web, service, upload, media, bots
    store.close()


def client_for(app, host='127.0.0.1', base='http://127.0.0.1:18080'):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app, client=(host, 1234)), base_url=base)


async def test_local_page_token_and_cross_site_protection(setup):
    app, web, service, *_ = setup
    async with client_for(app) as client:
        page = await client.get('/debug')
        assert page.status_code == 200
        assert web.token in page.text and 'textContent=text' in page.text
        assert "frame-ancestors 'none'" in page.headers['content-security-policy']
        assert page.headers['cache-control'] == 'no-store'
        assert (await client.get('/debug/state')).status_code == 403
        headers = {'X-Debug-Token': web.token}
        assert (await client.get('/debug/state', headers=headers)).status_code == 200
        for extra in ({'Origin': 'https://evil.test'}, {'Sec-Fetch-Site': 'cross-site'}, {'Host': 'evil.test'}):
            response = await client.post('/debug/chat', headers={**headers, **extra}, json={'text': '/reset'})
            assert response.status_code == 403
        assert not service.llm.complete.called
    async with client_for(app, host='8.8.8.8') as client:
        assert (await client.get('/debug')).status_code == 403
    async with client_for(app, base='http://localhost:18080') as client:
        assert (await client.get('/debug')).status_code == 200


async def test_shared_context_offline_chat_and_commands(setup):
    app, web, service, upload, media, bots = setup
    service.store.append(ADMIN, 'QQ 之前的话', 'QQ 回复')
    service.store.append(123, '其他用户私密', '其他用户回复')
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        state = (await client.get('/debug/state')).json()
        assert not state['qq_online'] and state['history'] == [['QQ 之前的话', 'QQ 回复']]
        reply = (await client.post('/debug/chat', json={'text': '网页普通对话'})).json()
        assert reply['reply'] == '<script>正文</script>'
        messages = service.llm.complete.call_args.args[0]
        assert 'QQ 之前的话' in str(messages) and '其他用户私密' not in str(messages)
        assert '结构化JSON协议' not in str(messages)
        assert len(service.store.history(ADMIN)) == 2
        for command in ('/help', '/status', '/missing', '/setname 调试名字', '/avatar', '/speaker list'):
            assert (await client.post('/debug/chat', json={'text': command})).status_code == 200
        assert len(service.store.history(ADMIN)) == 2
        assert service.llm.complete.call_count == 1
        assert service.store.identity()['role_name'] == '调试名字'
        assert not service.store.db.execute("SELECT 1 FROM settings WHERE key LIKE 'avatar_pending:%'").fetchone()
        service.store.compress(ADMIN, service.store.history(ADMIN)[0][0], '摘要')
        await client.post('/debug/chat', json={'text': '/reset'})
        assert not service.store.history(ADMIN) and not service.store.summary(ADMIN)
        assert service.store.history(123)


async def test_prompt_capture_and_audio_no_chat_history(setup):
    app, web, service, upload, media, bots = setup
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        await client.post('/debug/chat', json={'text': '/setprompt'})
        assert (await client.get('/debug/state')).json()['prompt_pending']
        assert upload.deadline('1946794276') is None
        raw = '  测试人设\r\n保留原文  '
        await client.post('/debug/chat', json={'text': raw})
        assert service.store.prompt() == raw
        assert not upload.deadline(WEB_BOT_ID)
        response = (await client.post('/debug/chat', json={'text': '/say 你好'})).json()
        assert base64.b64decode(response['audio'][0]) == b'RIFF-test-wave'
        assert not service.llm.complete.called and not service.store.history(ADMIN)


async def test_live_nickname_and_task_transport_id(setup):
    app, web, service, _, _, bots = setup
    bot = SimpleNamespace(self_id='1946794276', call_api=AsyncMock())
    bots[bot.self_id] = bot
    service.tasks = SimpleNamespace(chat=AsyncMock(return_value='任务完成'))
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        await client.post('/debug/chat', json={'text': '/setnickname 新昵称'})
        bot.call_api.assert_awaited_once_with('set_qq_profile', nickname='新昵称')
        assert service.store.identity()['role_nickname'] == '新昵称'
        result = (await client.post('/debug/chat', json={'text': '/tool 调试任务'})).json()
        assert result['reply'] == '任务完成'
        assert service.tasks.chat.call_args.kwargs['bot_id'] == bot.self_id
        assert not service.store.history(ADMIN)


async def test_web_busy_and_qq_reset_share_service_lock(setup):
    app, web, service, *_ = setup
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        entered.set()
        await release.wait()
        return '回复'

    service.llm.complete.side_effect = slow
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        pending = asyncio.create_task(client.post('/debug/chat', json={'text': '慢消息'}))
        await entered.wait()
        assert (await client.post('/debug/chat', json={'text': '重复提交'})).status_code == 409
        reset = asyncio.create_task(service.handle(ADMIN, '/reset', self_id=1946794276))
        await asyncio.sleep(.01)
        assert not reset.done()
        release.set()
        assert (await pending).status_code == 200
        await reset
        assert not service.store.history(ADMIN)


async def test_bad_and_oversized_input(setup):
    app, web, service, *_ = setup
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        for value in ({}, {'text': ''}, {'text': 123}, [], None):
            response = await client.post('/debug/chat', content=json.dumps(value), headers={'Content-Type': 'application/json'})
            assert response.status_code == 400
        assert (await client.post('/debug/chat', content='plain')).status_code == 415
        assert (await client.post('/debug/chat', json={'text': 'a' * (MAX_BYTES + 2000)})).status_code == 413
        assert not service.llm.complete.called


def attachment(name, content):
    return {'name': name, 'data': base64.b64encode(content).decode('ascii')}


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'gb18030'])
async def test_prompt_file_exact_bytes_decoding_no_model_or_history(setup, encoding):
    app, web, service, upload, *_ = setup
    service.store.set_prompt('原人设')
    service.store.append(ADMIN, '之前的对话', '之前的回复')
    content = '  新人设\r\n第二行\r\n  '
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        await client.post('/debug/chat', json={'text': '/setprompt'})
        result = await client.post('/debug/chat', json={'files': [attachment('角色.MD', content.encode(encoding))]})
        assert result.status_code == 200 and '已更新' in result.json()['reply']
        assert not result.json()['prompt_pending']
        assert service.store.prompt() == content
        assert service.store.history(ADMIN)[0][1:] == ('之前的对话', '之前的回复')
        assert not service.llm.complete.called


async def test_images_without_qq_use_vision_and_keep_prompt_waiting(setup):
    app, web, service, upload, _, bots = setup
    png = io.BytesIO()
    Image.new('RGB', (20, 20), 'blue').save(png, format='PNG')
    service.llm.create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
        finish_reason='stop', message=SimpleNamespace(content='蓝色方块', reasoning_content='不要发送'))]))
    media = Media(service.store, service.llm, service.config)
    previous = web.runtime
    web.runtime = lambda: (service, previous()[1], media, upload)
    service.store.set_prompt('原人设')
    try:
        async with client_for(app) as client:
            client.headers['X-Debug-Token'] = web.token
            await client.post('/debug/chat', json={'text': '/setprompt'})
            result = await client.post('/debug/chat', json={'text': '是什么颜色？',
                'files': [attachment('a.png', png.getvalue()), attachment('b.png', png.getvalue())]})
            assert result.status_code == 200 and result.json()['prompt_pending']
            assert service.store.prompt() == '原人设' and not bots
            vision = service.llm.create.call_args.kwargs
            assert len(vision['messages'][1]['content']) == 3
            assert vision['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
            assert '蓝色方块' in str(service.llm.complete.call_args.args[0])
            assert '不要发送' not in result.json()['reply']
            assert len(service.store.history(ADMIN)) == 1
            assert '图片识别' in service.store.history(ADMIN)[0][1]
    finally:
        await media.close()


async def test_text_attachment_chat_and_expired_prompt_does_not_replace(setup):
    app, web, service, upload, *_ = setup
    service.store.set_prompt('原人设')
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        await client.post('/debug/chat', json={'text': '/setprompt'})
        upload.clock = lambda: 1e12
        result = await client.post('/debug/chat', json={'text': '总结这个文件',
            'files': [attachment('笔记.txt', '周末去公园'.encode())]})
        assert result.status_code == 200 and not result.json()['prompt_pending']
        assert service.store.prompt() == '原人设'
        assert '周末去公园' in service.store.history(ADMIN)[0][1]
        assert '结构化JSON协议' not in str(service.llm.complete.call_args)


async def test_invalid_files_preserve_prompt_and_waiting(setup):
    app, web, service, upload, *_ = setup
    service.store.set_prompt('原人设')
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        await client.post('/debug/chat', json={'text': '/setprompt'})
        for files in ([attachment('x.exe', b'bad')], [attachment('x.md', b'x' * (MAX_BYTES + 1))],
                      [{'name': 'x.md', 'data': 'invalid base64!'}], [attachment('x.md', b'a')] * 2):
            assert (await client.post('/debug/chat', json={'files': files})).status_code == 400
        for content in (b'\0binary', b'   '):
            reply = (await client.post('/debug/chat', json={'files': [attachment('x.md', content)]})).json()
            assert reply['prompt_pending']
        assert (await client.post('/debug/chat', json={'text': '/setprompt', 'files': [attachment('x.md', b'a')]})).status_code == 400
        assert service.store.prompt() == '原人设' and not service.store.history(ADMIN)
        assert not service.llm.complete.called
