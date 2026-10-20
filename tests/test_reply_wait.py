import asyncio
from types import SimpleNamespace

from qqbot.reply_wait import wait_reply


async def test_slow_reply_notice_and_deadline():
    cancelled = asyncio.Event()
    async def handle(*args, **kwargs):
        try:
            await asyncio.sleep(5)
        finally:
            cancelled.set()
    service = SimpleNamespace(handle=handle, store=SimpleNamespace(allowed=lambda uid: True),
                              config=SimpleNamespace(chat_notice_seconds=.01, chat_timeout=.04))
    notices = []
    async def notify(text):
        notices.append(text)
    result = await wait_reply(service, 1, 'text', 2, notify)
    assert len(notices) == 1 and '超时' in result
    assert cancelled.is_set()


async def test_fast_reply_silent_and_cancelled_caller():
    async def handle(*args, **kwargs):
        return '最终正文'
    service = SimpleNamespace(handle=handle, store=SimpleNamespace(allowed=lambda uid: True),
                              config=SimpleNamespace(chat_notice_seconds=.01, chat_timeout=.04))
    async def notify(text):
        raise AssertionError('快请求不应提示')
    assert await wait_reply(service, 1, 'text', 2, notify) == '最终正文'
    stopped = asyncio.Event()
    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(5)
        finally:
            stopped.set()
    service.handle = slow
    request = asyncio.create_task(wait_reply(service, 1, 'text', 2, notify))
    await asyncio.sleep(.001)
    request.cancel()
    await asyncio.gather(request, return_exceptions=True)
    assert stopped.is_set()
