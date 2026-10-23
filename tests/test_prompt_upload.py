import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from qqbot.config import ADMIN
from qqbot.prompt_upload import MAX_BYTES, PromptUpload, decode_text, download_file
from qqbot.store import Store


def event(text='', *, uid=ADMIN, group=False, file=None):
    message = Message(MessageSegment.text(text)) if text else Message()
    if file is not None:
        message.append(MessageSegment('file', file))
    return SimpleNamespace(message_type='group' if group else 'private', user_id=uid,
                           message=message, get_plaintext=message.extract_plain_text)


@pytest.fixture
def setup(tmp_path):
    store = Store(str(tmp_path / 'db'))
    store.set_prompt('旧人设')
    store.set_identity(name='梦梦')
    store.append(ADMIN, '原聊天', '原回复')
    bot = SimpleNamespace(self_id='99999', call_api=AsyncMock(return_value={'url': 'https://file.qq.com/prompt'}))
    clock = [1000.]
    downloader = AsyncMock(return_value=b'new file\r\nsecond line\r\n')
    receiver = PromptUpload(store, 260000, clock=lambda: clock[0], downloader=downloader)
    yield receiver, store, bot, clock
    store.close()


async def test_permissions_commands_and_exact_multiline_text(setup):
    receiver, store, bot, clock = setup
    assert '超级管理员' in await receiver.message(bot, event('/prompt upload', uid=123))
    assert await receiver.message(bot, event('/prompt upload', group=True)) is None
    assert '5分钟' in await receiver.message(bot, event('/prompt upload'))
    assert await receiver.message(bot, event('unauthorized', uid=123)) is None
    assert await receiver.message(bot, event('/help')) is None
    content = '  新人设\r\n第二行\n  '
    assert '已更新' in await receiver.message(bot, event(content))
    assert store.prompt() == content
    assert store.identity() == {'role_name': '梦梦'}
    assert len(store.history(ADMIN)) == 1
    assert receiver.deadline(bot.self_id) is None
    assert await receiver.message(bot, event('普通聊天')) is None


async def test_restart_expiry_cancel_and_per_bot_scope(setup):
    receiver, store, bot, clock = setup
    await receiver.message(bot, event('/prompt upload'))
    receiver = PromptUpload(store, 260000, clock=lambda: clock[0])
    other = SimpleNamespace(self_id='88888')
    assert await receiver.message(other, event('不属于此机器人')) is None
    clock[0] += 300
    assert await receiver.message(bot, event('已过期')) is None
    assert receiver.deadline(bot.self_id) is None and store.prompt() == '旧人设'
    await receiver.message(bot, event('/prompt upload'))
    assert '已取消' in await receiver.message(bot, event('/prompt cancel'))
    assert await receiver.message(bot, event('取消后')) is None


async def test_file_message_and_offline_notice(setup):
    receiver, store, bot, clock = setup
    await receiver.message(bot, event('/prompt upload'))
    assert '已更新' in await receiver.message(bot, event(file={'name': '人物.MD', 'file_id': 'abc', 'size': 25}))
    bot.call_api.assert_awaited_once_with('get_private_file_url', file_id='abc')
    assert store.prompt() == 'new file\r\nsecond line\r\n'
    await receiver.message(bot, event('/prompt upload'))
    notice = SimpleNamespace(notice_type='offline_file', user_id=ADMIN,
                             file={'name': 'prompt.txt', 'size': 25, 'url': 'https://file.qq.com/prompt'})
    assert '已更新' in await receiver.notice(bot, notice)
    assert len(store.history(ADMIN)) == 1


async def test_failed_file_keeps_prompt_and_waiting_and_logs_no_content(setup, caplog):
    receiver, store, bot, clock = setup
    await receiver.message(bot, event('/prompt upload'))
    for file in ({'name': 'bad.exe'}, {'name': 'big.txt', 'size': MAX_BYTES + 1}):
        assert '原人设已保留' in await receiver.message(bot, event(file=file))
    assert not bot.call_api.await_count and not receiver.download.await_count
    receiver.download.side_effect = RuntimeError('PRIVATE_PROMPT_AND_URL_SECRET')
    assert '原人设已保留' in await receiver.message(bot, event(file={'name': 'bad.md', 'url': 'https://file.qq.com/private'}))
    assert 'PRIVATE_PROMPT_AND_URL_SECRET' not in caplog.text
    assert store.prompt() == '旧人设' and receiver.deadline(bot.self_id)
    receiver.download.side_effect = None
    receiver.context_tokens = 20
    assert '原人设已保留' in await receiver.message(bot, event('长' * 30))
    assert '已更新' in await receiver.message(bot, event('短'))


async def test_only_first_concurrent_file_consumes_waiting(setup):
    receiver, store, bot, clock = setup
    await receiver.message(bot, event('/prompt upload'))
    first = event(file={'name': 'first.md', 'url': 'https://file.qq.com/first'})
    second = event(file={'name': 'second.txt', 'url': 'https://file.qq.com/second'})
    replies = await asyncio.gather(receiver.message(bot, first), receiver.message(bot, second))
    assert '已更新' in replies[0] and replies[1] is None
    assert receiver.download.await_count == 1


def test_decoding_preserves_content_and_rejects_binary():
    text = '  中文\r\n下一行\n'
    for encoding in ('utf-8', 'utf-16', 'gb18030'):
        assert decode_text(text.encode(encoding)) == text
    with pytest.raises(ValueError):
        decode_text(b'\x00binary')


async def test_download_rejects_local_addresses(monkeypatch):
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, 'getaddrinfo', AsyncMock(return_value=[(None, None, None, None, ('127.0.0.1', 80))]))
    with pytest.raises(ValueError, match='private'):
        await download_file('http://example.com/prompt.txt')
