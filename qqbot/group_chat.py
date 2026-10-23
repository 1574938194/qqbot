"""单群、仅管理员明确 @ 触发的被动回复；上下文与私聊隔离。"""
from dataclasses import replace
from pathlib import Path

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from .config import ADMIN
from .image_generation import ImageReply
from .reply_wait import wait_reply
from .service import Service
from .store import Store

GROUP = 707318959
GROUP_HELP = '群内仅回复管理员 @ 我的消息。支持文字、图片及 /help、/chat status、/chat compress、/chat reset；管理设置请私聊。'


def addressed(event, bot_id):
    return (event.message_type == 'group' and getattr(event, 'group_id', None) == GROUP
        and event.user_id == ADMIN and event.user_id != int(bot_id)
        and any(s.type == 'at' and str(s.data.get('qq')) == str(bot_id)
            for s in getattr(event, 'original_message', event.message)))


async def accept_target_invite(bot, event):
    if (getattr(event, 'request_type', '') == 'group'
        and getattr(event, 'sub_type', '') == 'invite'
        and getattr(event, 'group_id', None) == GROUP):
        await bot.set_group_add_request(flag=event.flag, sub_type='invite', approve=True)
        return True
    return False


class GroupChat:
    def __init__(self, private_service, media):
        self.private, self.media = private_service, media
        config = replace(private_service.config, agent_backend='legacy', memory_backend='none',
            tasks_enabled=False, db_path=str(Path(private_service.config.db_path).with_name(f'group-{GROUP}.sqlite3')))
        store = Store(config.db_path)
        store.set_prompt('你是群聊中的中文 AI 助手，语气自然、友好、简洁。只依据本群管理员明确 @ 你的消息作答。'
            '不要引用或猜测私聊内容，不编造后台操作。群里不主动发言，不发送问候或提醒。')
        self.service = Service(store, private_service.llm, config, image_generator=private_service.image_generator)

    async def handle(self, bot, event):
        if not addressed(event, bot.self_id):
            return
        if any(s.type not in ('text', 'image', 'at', 'reply') for s in event.message):
            return
        identity = self.private.store.identity()
        self.service.store.set_identity(name=identity.get('role_name', 'AI 助手'), nickname=identity.get('role_nickname', ''))
        text = event.get_plaintext().strip()
        images = [s for s in event.message if s.type == 'image']

        async def send(text):
            for start in range(0, len(text), self.service.config.message_chars):
                await bot.send_group_msg(group_id=GROUP, message=Message(MessageSegment.text(text[start:start+self.service.config.message_chars])))

        if text.startswith('/'):
            command = text.split(maxsplit=1)[0].lower()
            if command == '/help':
                await send(GROUP_HELP)
                return
            if text not in ('/chat', '/chat status', '/chat compress', '/chat reset'):
                await send(GROUP_HELP)
                return
        prepare = (lambda: self.media.describe(bot, images, text)) if images and self.media else None
        reply = await wait_reply(self.service, ADMIN, text, int(bot.self_id), send, prepare=prepare)
        if isinstance(reply, ImageReply):
            for raw in reply.images:
                await bot.send_group_msg(group_id=GROUP, message=Message(MessageSegment.image(raw)))
        elif reply:
            await send(str(reply))

    def close(self):
        self.service.store.close()
