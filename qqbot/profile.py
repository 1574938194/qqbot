"""管理员资料命令独立于模型及聊天锁，头像等待期限持久化。"""
import asyncio
import logging
import time
from collections import defaultdict

from .config import ADMIN

PROFILE_HELP = '\n/setname 角色名\n/setnickname 昵称（同步QQ昵称）\n/name 昵称（同 /setnickname）\n/avatar（5分钟内下一张私聊图片设为头像）\n/avatar cancel'


class Profile:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.locks = defaultdict(asyncio.Lock)

    def deadline(self, bot_id):
        row = self.store.db.execute('SELECT value FROM settings WHERE key=?',
                                    ('avatar_pending:' + str(bot_id),)).fetchone()
        return float(row[0]) if row else None

    def clear(self, bot_id):
        with self.store.db:
            self.store.db.execute('DELETE FROM settings WHERE key=?', ('avatar_pending:' + str(bot_id),))

    async def handle(self, bot, event):
        """返回 None 表示不是资料命令；返回字符串表示事件已处理。"""
        if event.message_type != 'private' or event.user_id == int(bot.self_id):
            return None
        images = [segment for segment in event.message if segment.type == 'image']
        pure_text = all(segment.type == 'text' for segment in event.message)
        text = event.get_plaintext().strip() if pure_text else ''
        parts = text.split(maxsplit=1)
        command = parts[0].lower() if parts else ''
        if command not in ('/setname', '/setnickname', '/name', '/nickname', '/avatar') and not images:
            return None
        if event.user_id != ADMIN:
            return '只有超级管理员可以修改机器人资料。' if command else None
        async with self.locks[str(bot.self_id)]:
            if command == '/avatar':
                args = parts[1].strip() if len(parts) == 2 else ''
                if args == 'cancel':
                    self.clear(bot.self_id)
                    return '已取消等待头像图片。'
                if args:
                    return '用法：/avatar 或 /avatar cancel'
                with self.store.db:
                    self.store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',
                        ('avatar_pending:' + str(bot.self_id), str(self.clock() + 300)))
                return '请在5分钟内私聊发送图片，收到的第一张图片将设为机器人头像。取消请用 /avatar cancel。'
            if command in ('/setname', '/setnickname', '/name', '/nickname'):
                if len(parts) == 1:
                    identity = self.store.identity()
                    return ('当前角色名字：' + identity.get('role_name', '未单独设置')
                            + '\n当前昵称：' + identity.get('role_nickname', '未单独设置'))
                name = parts[1].strip() if len(parts) == 2 else ''
                if not name or len(name) > 32 or any(ord(char) < 32 for char in name):
                    return f'用法：{command} 新名字（1至32个字符，不含换行）'
                if command == '/setname':
                    self.store.set_identity(name=name)
                    return f'角色名字已更新为「{name}」，已保存，下轮对话生效。'
                try:
                    async with asyncio.timeout(20):
                        await bot.call_api('set_qq_profile', nickname=name)
                    self.store.set_identity(nickname=name)
                    return '机器人昵称已更新。'
                except Exception as exc:
                    logging.getLogger(__name__).warning('nickname update failed: %s', type(exc).__name__)
                    return '昵称更新未确认成功，请检查QQ资料后重试；超时请求可能已经生效。'
            deadline = self.deadline(bot.self_id)
            if deadline is None:
                return None
            # 第一张图片先消耗等待资格，防止并发消息及失败重试误用第二张。
            self.clear(bot.self_id)
            if self.clock() >= deadline:
                return None  # 等待过期后的图片恢复普通视觉聊天，不再消耗为头像。
            try:
                async with asyncio.timeout(20):
                    image = images[0].data
                    info = await bot.call_api('get_image', file=image['file'])
                    source = info.get('file') or info.get('url')
                    if not isinstance(source, str) or not source:
                        raise ValueError('image source missing')
                    await bot.call_api('set_qq_avatar', file=source)
                return '机器人头像已更新。'
            except Exception as exc:
                logging.getLogger(__name__).warning('avatar update failed: %s', type(exc).__name__)
                return '头像更新未确认成功，本次等待已结束。请检查头像；需要重试时重新发送 /avatar。'
