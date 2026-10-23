import asyncio
from dataclasses import replace

import pytest

from qqbot.config import ADMIN, DEFAULT_PROMPT, Settings
from qqbot.llm import ModelError
from qqbot.service import Service
from qqbot.store import Store


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def complete(self, messages, *, summary=False):
        self.calls.append((messages, summary))
        if self.fail:
            raise ModelError('模拟失败')
        return '称呼：小明；喜欢猫；还在等待考试结果。' if summary else '我在呢，今天过得怎么样？'


@pytest.fixture
def service(tmp_path):
    store = Store(str(tmp_path / 'test.db'))
    result = Service(store, FakeLLM(), Settings())
    yield result
    store.close()


async def test_permissions(service):
    s = service
    assert await s.handle(123, '你好') is None
    assert await s.handle(ADMIN, '你好', private=False) is None
    assert await s.handle(ADMIN, '你好', self_id=ADMIN) is None
    assert not s.llm.calls
    assert '不可移除' in await s.handle(ADMIN, f'/whitelist remove {ADMIN}')
    await s.handle(ADMIN, '/whitelist add 123')
    assert '123' in await s.handle(ADMIN, '/whitelist list')
    assert '只有超级管理员' in await s.handle(123, '/prompt set hack')
    assert '只有超级管理员' in await s.handle(123, '/whitelist add 456')
    assert '未知命令' in await s.handle(123, '/missing')
    assert not s.llm.calls
    await s.handle(123, '你好')
    await s.handle(ADMIN, '/whitelist remove 123')
    assert await s.handle(123, '/help') is None
    assert len(s.store.history(123)) == 1


async def test_persistence_isolation_prompt_reset(tmp_path):
    path = str(tmp_path / 'persist.db')
    store, model = Store(path), FakeLLM()
    s = Service(store, model, Settings())
    await s.handle(ADMIN, '/whitelist add 123')
    await s.handle(ADMIN, '管理员秘密')
    await s.handle(123, '我的秘密')
    assert '管理员秘密' not in str(model.calls[-1])
    await s.handle(ADMIN, '/prompt set 新人设\n第二行')
    await s.handle(123, '下一轮')
    assert model.calls[-1][0][0]['content'] == '新人设\n第二行'
    store.compress(123, store.history(123)[0][0], '旧摘要')
    store.close()
    store = Store(path)
    s = Service(store, model, Settings())
    assert store.allowed(123)
    assert store.summary(123) == '旧摘要'
    assert len(store.history(123)) == 1
    assert store.prompt() == '新人设\n第二行'
    await s.handle(123, '/chat reset')
    assert not store.history(123) and not store.summary(123)
    assert len(store.history(ADMIN)) == 1
    assert store.prompt() == '新人设\n第二行'
    await s.handle(ADMIN, '/prompt reset')
    assert store.prompt() == DEFAULT_PROMPT
    store.close()


def populate(s, count):
    for i in range(count):
        s.store.append(ADMIN, f'问题{i}', f'回答{i}')


async def test_manual_repeated_compression_and_failure(service):
    s = service
    populate(s, 10)
    assert '压缩完成' in await s.handle(ADMIN, '/chat compress')
    assert len(s.store.history(ADMIN)) == 6
    assert s.store.summary(ADMIN)
    populate(s, 4)
    before = s.store.history(ADMIN), s.store.summary(ADMIN)
    s.llm.fail = True
    assert '原对话和摘要已保留' in await s.handle(ADMIN, '/chat compress')
    assert before == (s.store.history(ADMIN), s.store.summary(ADMIN))
    s.llm.fail = False
    await s.handle(ADMIN, '/chat compress')
    assert '已有摘要' in str(s.llm.calls[-1])
    assert len(s.store.history(ADMIN)) == 6
    assert '暂无可压缩' in await s.handle(ADMIN, '/chat compress')


async def test_auto_limits_and_errors(service):
    s = service
    s.config = replace(s.config, compress_rounds=20)
    populate(s, 21)
    await s.handle(ADMIN, '你好')
    assert [summary for _, summary in s.llm.calls] == [True, False]
    assert len(s.store.history(ADMIN)) == 7
    before = s.store.history(ADMIN)
    assert '太长' in await s.handle(ADMIN, '长' * 5000)
    assert before == s.store.history(ADMIN)
    s.llm.fail = True
    assert '模拟失败' in await s.handle(ADMIN, '失败')
    assert before == s.store.history(ADMIN)
    populate(s, 15)
    before = s.store.history(ADMIN)
    assert '自动压缩失败' in await s.handle(ADMIN, '再次')
    assert before == s.store.history(ADMIN)


async def test_token_trigger_and_still_over_budget(service):
    s = service
    s.config = replace(s.config, context_tokens=1500, compress_tokens=1400)
    for _ in range(8):
        s.store.append(ADMIN, '中' * 200, '文' * 200)
    assert '仍超出' in await s.handle(ADMIN, '短消息')
    assert [summary for _, summary in s.llm.calls] == [True]
    assert len(s.store.history(ADMIN)) == 6


@pytest.mark.parametrize('budget,compressed', [(240000, False), (240001, True)])
async def test_chat_240k_boundary_without_round_trigger(service, budget, compressed):
    s = service
    populate(s, 21)
    s.input_tokens = lambda uid, messages: budget if len(s.store.history(uid)) > 6 else 1000
    await s.handle(ADMIN, '继续聊')
    assert [summary for _, summary in s.llm.calls] == ([True, False] if compressed else [False])
    assert len(s.store.history(ADMIN)) == (7 if compressed else 22)
    assert s.config.context_tokens == 260000


async def test_240k_compression_failure_preserves_data(service):
    s = service
    populate(s, 8)
    s.input_tokens = lambda uid, messages: 240001
    before = s.store.history(ADMIN), s.store.summary(ADMIN)
    s.llm.fail = True
    assert '自动压缩失败' in await s.handle(ADMIN, '继续聊')
    assert before == (s.store.history(ADMIN), s.store.summary(ADMIN))
    assert [summary for _, summary in s.llm.calls] == [True]


def test_context_configuration_bounds():
    for changes in ({'compress_tokens': 260000}, {'compress_tokens': 0}, {'compress_rounds': -1}):
        with pytest.raises(ValueError):
            replace(Settings(), **changes)


async def test_chat_reset_serialization(service):
    s = service
    started, release = asyncio.Event(), asyncio.Event()
    async def waiting(messages, *, summary=False):
        started.set()
        await release.wait()
        return '完成'
    s.llm.complete = waiting
    chat = asyncio.create_task(s.handle(ADMIN, '慢请求'))
    await started.wait()
    reset = asyncio.create_task(s.handle(ADMIN, '/chat reset'))
    await asyncio.sleep(0)
    assert not reset.done()
    release.set()
    await asyncio.gather(chat, reset)
    assert not s.store.history(ADMIN) and not s.store.summary(ADMIN)


async def test_parallel_users_and_revocation(service):
    s = service
    s.store.grant(123, True)
    started, release = asyncio.Event(), asyncio.Event()
    async def waiting(messages, *, summary=False):
        started.set()
        await release.wait()
        return '完成'
    s.llm.complete = waiting
    chat = asyncio.create_task(s.handle(123, '慢请求'))
    await started.wait()
    await s.handle(ADMIN, '/whitelist remove 123')
    release.set()
    assert await chat is None
    assert not s.store.history(123)


async def test_compress_reset_serialization(service):
    s = service
    populate(s, 9)
    started, release = asyncio.Event(), asyncio.Event()
    async def waiting(messages, *, summary=False):
        assert summary
        started.set()
        await release.wait()
        return '摘要'
    s.llm.complete = waiting
    compress = asyncio.create_task(s.handle(ADMIN, '/chat compress'))
    await started.wait()
    reset = asyncio.create_task(s.handle(ADMIN, '/chat reset'))
    await asyncio.sleep(0)
    assert not reset.done()
    release.set()
    await asyncio.gather(compress, reset)
    assert not s.store.history(ADMIN) and not s.store.summary(ADMIN)
