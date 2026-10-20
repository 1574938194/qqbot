"""给慢请求一次等待提示，并在期限内取消未完成请求。"""
import asyncio


async def wait_reply(service, uid, text, self_id, notify, *, prepare=None):
    deadline = asyncio.get_running_loop().time() + service.config.chat_timeout
    pending = asyncio.create_task(service.handle(uid, text, self_id=self_id, **({'prepare': prepare} if prepare else {})))
    try:
        done, _ = await asyncio.wait({pending}, timeout=service.config.chat_notice_seconds)
        if not done and service.store.allowed(uid):
            try:
                await asyncio.wait_for(notify('收到啦，模型响应有点慢，我还在等。'),
                                       max(.001, min(5, deadline - asyncio.get_running_loop().time())))
            except Exception:
                # 提示发送失败不丢弃仍在处理的最终请求。
                pass
        try:
            remaining = max(.001, deadline - asyncio.get_running_loop().time())
            return await asyncio.wait_for(pending, remaining)
        except TimeoutError:
            return '这次模型等待超时了，未完成的回复已取消，请稍后重试。如涉及任务创建，可先用 /task list 查询。'
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
