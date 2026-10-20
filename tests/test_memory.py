import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from qqbot.config import ADMIN, Settings
from qqbot.llm import ModelError
from qqbot.memory import Memory
from qqbot.service import Service
from qqbot.store import Store


class Model:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def complete(self, messages, *, summary=False):
        self.calls.append((messages, summary))
        if self.fail:
            raise ModelError('失败')
        return '用户喜欢猫。' if summary else '我在呢。'


@pytest.fixture
def setup_memory(tmp_path):
    resources = []
    def make(handler, backend='mem0', **kwargs):
        config = Settings(memory_backend=backend, memory_base_url='http://memory.test',
                          memory_api_key='secret-memory-key', **kwargs)
        store, llm = Store(str(tmp_path / f'{len(resources)}.db')), Model()
        memory = Memory(store, llm, config, transport=httpx.MockTransport(handler))
        service = Service(store, llm, config, memory)
        resources.append((store, memory))
        return service
    yield make
    for store, memory in resources:
        store.close()


async def test_mem0_isolation_reset_outbox_and_restart(setup_memory):
    calls, fail = [], False
    def handle(request):
        nonlocal fail
        assert request.headers['X-API-Key'] == 'secret-memory-key'
        data = json.loads(request.content) if request.content else {}
        calls.append((request.method, request.url.path, data, dict(request.url.params)))
        if fail:
            return httpx.Response(503, json={'error': 'secret-memory-key'})
        if request.url.path == '/search':
            assert data['top_k'] == 5
            return httpx.Response(200, json={'results': [
                {'memory': '我的长期偏好', 'user_id': data['filters']['user_id']},
                {'memory': '其他用户的秘密', 'user_id': 'another-user'}]})
        return httpx.Response(200, json={'results': []})
    s = setup_memory(handle)
    s.store.grant(123, True)
    await s.handle(ADMIN, '我很开心，喜欢猫')
    old_scope = s.memory.scope(ADMIN)
    assert s.store.pending_memory(ADMIN) == 0
    assert s.store.emotion(ADMIN)['mood'] == '开心'
    assert '我的长期偏好' in str(s.llm.calls[0])
    assert '其他用户的秘密' not in str(s.llm.calls[0])
    await s.handle(123, '我有点难过')
    assert s.memory.scope(123) != old_scope
    assert s.store.emotion(123)['mood'] == '低落'
    assert s.store.emotion(ADMIN)['mood'] == '开心'
    assert calls[1][2]['messages'] == [{'role': 'user', 'content': '我很开心，喜欢猫'}]
    fail = True
    await s.handle(ADMIN, '服务故障时的消息')
    assert s.store.pending_memory(ADMIN) == 1
    assert '待同步' in await s.handle(ADMIN, '/memory status')
    # 重建管理器模拟进程重启，持久化作用域与待办均可恢复。
    await s.memory.close()
    s.memory = Memory(s.store, s.llm, s.config, transport=httpx.MockTransport(handle))
    assert s.memory.scope(ADMIN) == old_scope
    assert s.store.pending_memory(ADMIN) == 1
    reset = await s.handle(ADMIN, '/reset')
    assert '外部清理尚有' in reset
    assert not s.store.emotion(ADMIN) and not s.store.history(ADMIN)
    assert s.memory.scope(ADMIN) != old_scope
    assert s.store.memory_jobs(ADMIN, s.memory.identity)[0][2] == 'clear'
    fail = False
    await s.handle(ADMIN, '/memory sync')
    assert s.store.pending_memory(ADMIN) == 0
    assert calls[-1][0] == 'DELETE' and calls[-1][3] == {'user_id': old_scope}
    assert s.store.history(123)
    await s.memory.close()


async def test_memory_errors_redacted_and_permissions(setup_memory, caplog):
    requests = []
    def broken(request):
        requests.append(request)
        raise httpx.ReadTimeout('secret-memory-key private-text', request=request)
    s = setup_memory(broken)
    assert await s.handle(123, 'private-text') is None
    assert await s.handle(ADMIN, 'private-text', private=False) is None
    assert not requests
    assert await s.handle(ADMIN, 'private-text') == '我在呢。'
    assert len(s.store.history(ADMIN)) == 1
    assert s.store.pending_memory(ADMIN) == 1
    assert 'secret-memory-key' not in caplog.text and 'private-text' not in caplog.text
    await s.memory.close()


async def test_letta_block_create_update_recall_delete(setup_memory):
    blocks, calls = {}, []
    def handle(request):
        assert request.headers['Authorization'] == 'Bearer secret-memory-key'
        path = request.url.path
        data = json.loads(request.content) if request.content else {}
        calls.append((request.method, path, data))
        if request.method == 'POST':
            block_id = 'block-test'
            blocks[block_id] = data
            return httpx.Response(200, json={'id': block_id, 'value': data['value']})
        block_id = path.rsplit('/', 1)[1]
        if request.method == 'GET':
            return httpx.Response(200, json={'id': block_id, 'value': blocks[block_id]['value']})
        if request.method == 'PATCH':
            blocks[block_id].update(data)
            return httpx.Response(200, json={'id': block_id, **blocks[block_id]})
        blocks.pop(block_id)
        return httpx.Response(204)
    s = setup_memory(handle, 'letta')
    await s.handle(ADMIN, '我喜欢猫')
    assert s.store.scope_ref(s.memory.scope(ADMIN)) == 'block-test'
    assert '用户喜欢猫' in (await s.memory.recall(ADMIN, '我喜欢什么'))[0]
    await s.handle(ADMIN, '我还喜欢读书')
    assert any(method == 'PATCH' for method, _, _ in calls)
    await s.handle(ADMIN, '/reset')
    assert not blocks and not s.store.pending_memory(ADMIN)
    await s.memory.close()


async def test_memory_budget_and_failed_chat_do_not_update_state(setup_memory):
    def handle(request):
        return httpx.Response(200, json={'results': [{'memory': '长' * 2000}]})
    s = setup_memory(handle, context_tokens=1300, compress_tokens=1200)
    s.llm.fail = True
    assert await s.handle(ADMIN, '我难过') == '失败'
    assert not s.store.emotion(ADMIN) and not s.store.pending_memory(ADMIN)
    s.llm.fail = False
    assert await s.handle(ADMIN, '我难过') == '我在呢。'
    # 检索资料挤占预算时舍弃检索，不删除正式历史或拒绝可容纳的输入。
    assert '长' * 100 not in str(s.llm.calls[-1])
    await s.memory.close()


async def test_reset_waits_for_external_write(setup_memory):
    started, release = asyncio.Event(), asyncio.Event()
    async def handle(request):
        if request.url.path == '/memories' and request.method == 'POST':
            started.set()
            await release.wait()
        return httpx.Response(200, json={'results': []})
    s = setup_memory(handle)
    chat = asyncio.create_task(s.handle(ADMIN, '我有点焦虑'))
    await started.wait()
    old_scope = s.memory.scope(ADMIN)
    reset = asyncio.create_task(s.handle(ADMIN, '/reset'))
    await asyncio.sleep(0)
    assert not reset.done()
    release.set()
    await asyncio.gather(chat, reset)
    assert not s.store.history(ADMIN) and not s.store.emotion(ADMIN)
    assert s.memory.scope(ADMIN) != old_scope
    await s.memory.close()
