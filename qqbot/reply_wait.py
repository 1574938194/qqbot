"""给慢请求一次等待提示，并在期限内取消未完成请求。"""
import asyncio
from .image_generation import image_request


async def wait_reply(service, uid, text, self_id, notify, *, prepare=None):
    drawing = image_request(text) if prepare is None and getattr(service, 'image_generator', None) else None
    deadline = asyncio.get_running_loop().time() + (service.config.image_timeout + 10 if drawing else service.config.chat_timeout)
    if getattr(service, 'qwen', None) and not drawing:
        deadline = asyncio.get_running_loop().time() + service.config.qwenpaw_timeout + 30
    signing_in = text.strip() == '签到' and prepare is None
    managing_pool = text.strip().split(maxsplit=1)[:1] == ['/pool'] and prepare is None
    pending = asyncio.create_task(service.handle(uid, text, self_id=self_id, **({'prepare': prepare} if prepare else {})))
    try:
        done, _ = await asyncio.wait({pending}, timeout=service.config.chat_notice_seconds)
        if not done and service.store.allowed(uid):
            try:
                await asyncio.wait_for(notify('正在等待 buddyproxy 号池操作结果。' if managing_pool else '正在等待 buddyproxy 签到结果。' if signing_in else '收到，正在处理。执行中的任务可发送 /task stop 停止。' if getattr(service, 'qwen', None) else '收到啦，模型响应有点慢，我还在等。'),
                                       max(.001, min(5, deadline - asyncio.get_running_loop().time())))
            except Exception:
                # 提示发送失败不丢弃仍在处理的最终请求。
                pass
        try:
            remaining = max(.001, deadline - asyncio.get_running_loop().time())
            return await asyncio.wait_for(pending, remaining)
        except TimeoutError:
            if managing_pool:
                return '号池操作等待超时，请稍后用 /pool 查询当前状态。'
            if signing_in:
                return '签到等待超时，部分账号可能已签到，请稍后重试确认。'
            return '这次模型等待超时了，未完成的回复已取消，请稍后重试。如涉及任务创建，可先用 /task list 查询。'
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
