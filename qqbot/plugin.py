from nonebot import get_bots, get_driver, on_message, on_notice, on_request
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment, NoticeEvent, RequestEvent

from .config import Settings, ADMIN
from .llm import LLM
from .service import Service, ChatReply
from .store import Store
from .memory import Memory
from .tasks import Tasks
from .process_lock import ProcessLock
from .reply_wait import wait_reply
from .profile import Profile
from .media import Media
from .prompt_upload import PromptUpload
from .llm import ModelError
from .web_chat import WebChat
from .image_generation import ImageGenerator, ImageReply
from .qwenpaw_client import QwenReply
from .qwenpaw_media import collect as collect_qwen_files, send_files as send_qwen_files
from .group_chat import GroupChat, accept_target_invite
from fastapi import HTTPException, Request
import json
import secrets
import logging

service: Service | None = None
process_lock: ProcessLock | None = None
profile: Profile | None = None
media: Media | None = None
prompt_upload: PromptUpload | None = None
group_chat: GroupChat | None = None
matcher = on_message(priority=10, block=False)
file_notice = on_notice(priority=10, block=False)
group_invite = on_request(priority=10, block=False)
web_chat = WebChat(get_driver().server_app, lambda: (service, profile, media, prompt_upload), get_bots)


@get_driver().server_app.get('/health')
async def health():
    return {'status': 'ready' if service else 'starting', 'connected_bots': sorted(get_bots()),
            'tasks_enabled': bool(service and service.tasks)}


async def task_sender(uid, text, bot_id):
    bots = get_bots()
    bot = bots.get(bot_id) if bot_id else (next(iter(bots.values())) if len(bots) == 1 else None)
    if bot is None:
        raise RuntimeError('机器人未连接，等待重连后投递。')
    await bot.send_private_msg(user_id=uid, message=Message(MessageSegment.text(text)))


@get_driver().server_app.post('/internal/qwenpaw/deliver')
async def qwenpaw_deliver(request: Request):
    token = service.config.qwenpaw_token if service else ''
    supplied = request.headers.get('x-qqbot-token', '')
    if not token or not supplied.isascii() or not secrets.compare_digest(token, supplied):
        raise HTTPException(403, '拒绝访问。')
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, '内容过大。')
    try:
        data = json.loads(raw)
        uid, parts = data['uid'], data['parts']
        if type(uid) is not int or not isinstance(parts, list) or len(parts) > 100 or not all(isinstance(p, dict) for p in parts):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, '消息参数错误。') from None
    if not service.store.allowed(uid):
        raise HTTPException(403, '用户无权限。')
    bots = get_bots()
    if len(bots) != 1:
        raise HTTPException(503, 'QQ 未连接。')
    bot = next(iter(bots.values()))
    try:
        files = await collect_qwen_files(uid, parts, service.config)
        for part in parts:
            if part.get('type') in ('text', 'refusal'):
                text = part.get('text', part.get('refusal', ''))
                if isinstance(text, str):
                    for offset in range(0, len(text), service.config.message_chars):
                        await task_sender(uid, text[offset:offset+service.config.message_chars], bot.self_id)
        await send_qwen_files(bot, uid, files)
    except Exception as exc:
        logging.getLogger(__name__).warning('QwenPaw delivery failure: %s', type(exc).__name__)
        raise HTTPException(502, '结果投递失败，请检查 QQ 连接及成果文件。') from None
    return {'ok': True}


@get_driver().on_startup
async def startup():
    global service, process_lock, profile, media, prompt_upload, group_chat
    config = Settings.load()
    process_lock = ProcessLock(config.db_path)
    llm = LLM(config)
    store = Store(config.db_path)
    prompt_upload = PromptUpload(store, config.context_tokens)
    profile = Profile(store)
    media = Media(store, llm, config)
    tasks = Tasks(store, llm, config, sender=task_sender) if config.tasks_enabled else None
    service = Service(store, llm, config, Memory(store, llm, config), tasks, ImageGenerator(config))
    service.memory.start()
    group_chat = GroupChat(service, media)
    if tasks:
        tasks.start()


@get_driver().on_shutdown
async def shutdown():
    if service:
        if service.tasks:
            await service.tasks.close()
        await service.llm.close()
        if media:
            await media.close()
        await service.memory.close()
        if group_chat:
            group_chat.close()
        service.store.close()
    if process_lock:
        process_lock.close()


@matcher.handle()
async def receive(bot: Bot, event: MessageEvent):
    if service and event.message_type == 'group':
        if group_chat:
            await group_chat.handle(bot, event)
        return
    if not service or event.message_type != "private" or event.user_id == int(bot.self_id):
        return
    if not service.store.allowed(event.user_id):
        return
    profile_reply = await prompt_upload.message(bot, event) if prompt_upload else None
    if profile_reply is None:
        profile_reply = await profile.handle(bot, event) if profile else None
    if profile_reply is not None:
        for start in range(0, len(profile_reply), service.config.message_chars):
            await bot.send_private_msg(user_id=event.user_id, message=Message(MessageSegment.text(profile_reply[start:start + service.config.message_chars])))
        return
    # 人设/头像接收优先；其余聊天支持文本与图片，暂不接收语音等其他输入类型。
    if any(segment.type not in ('text', 'image') for segment in event.message):
        return
    if not service.store.allowed(event.user_id):
        return
    async def notify(text):
        for start in range(0, len(text), service.config.message_chars):
            if not service.store.allowed(event.user_id):
                break
            await bot.send_private_msg(user_id=event.user_id, message=Message(MessageSegment.text(text[start:start + service.config.message_chars])))
    async def send_audio(audio):
        if service.store.allowed(event.user_id):
            await bot.send_private_msg(user_id=event.user_id, message=Message(MessageSegment.record(audio)))
    images = [segment for segment in event.message if segment.type == 'image']
    text = event.get_plaintext()
    if media and not images and text.strip().split(maxsplit=1)[:1] and text.strip().split(maxsplit=1)[0].lower() in ('/voice', '/say', '/speaker'):
        try:
            result = await media.command(event.user_id, text)
            if isinstance(result, bytes):
                await send_audio(result)
            elif result:
                await notify(result)
        except Exception as exc:
            logging.getLogger(__name__).warning('voice command failure: %s', type(exc).__name__)
            await notify(str(exc) if isinstance(exc, ModelError) else '语音发送失败，请稍后重试。')
        return
    prepare = (lambda: media.describe(bot, images, text)) if images and media else None
    reply = await wait_reply(service, event.user_id, text, int(bot.self_id), notify, prepare=prepare)
    if reply:
        if isinstance(reply, ImageReply):
            for raw in reply.images:
                if service.store.allowed(event.user_id):
                    await bot.send_private_msg(user_id=event.user_id, message=Message(MessageSegment.image(raw)))
            return
        mode = media.voice_mode(event.user_id) if media and isinstance(reply, (ChatReply, QwenReply)) else 'off'
        if mode != 'on':
            await notify(reply)
        if isinstance(reply, QwenReply) and reply.parts and service.store.allowed(event.user_id):
            try:
                await send_qwen_files(bot, event.user_id, await collect_qwen_files(event.user_id, reply.parts, service.config))
            except Exception as exc:
                logging.getLogger(__name__).warning('QwenPaw artifact failure: %s', type(exc).__name__)
                await notify('任务附件暂未发送成功，请在 QwenPaw 网页查看原文件。')
        if mode != 'off':
            try:
                for start in range(0, len(reply), service.config.tts_max_chars):
                    if not service.store.allowed(event.user_id):
                        break
                    await send_audio(await media.synthesize(reply[start:start + service.config.tts_max_chars], uid=event.user_id))
            except Exception as exc:
                logging.getLogger(__name__).warning('voice reply failure: %s', type(exc).__name__)
                if mode == 'on':
                    await notify(reply)
                await notify('语音生成或发送失败，已保留文字回复。可用 /voice off 关闭语音。')


@file_notice.handle()
async def receive_prompt_file(bot: Bot, event: NoticeEvent):
    if not service or not prompt_upload:
        return
    reply = await prompt_upload.notice(bot, event)
    if reply:
        for start in range(0, len(reply), service.config.message_chars):
            await bot.send_private_msg(user_id=ADMIN, message=Message(MessageSegment.text(reply[start:start + service.config.message_chars])))


@group_invite.handle()
async def receive_group_invite(bot: Bot, event: RequestEvent):
    try:
        await accept_target_invite(bot, event)
    except Exception as exc:
        logging.getLogger(__name__).warning('Target group invite failure: %s', type(exc).__name__)
