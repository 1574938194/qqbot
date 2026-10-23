from nonebot import get_bots, get_driver, on_message, on_notice
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment, NoticeEvent

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
import logging

service: Service | None = None
process_lock: ProcessLock | None = None
profile: Profile | None = None
media: Media | None = None
prompt_upload: PromptUpload | None = None
matcher = on_message(priority=10, block=False)
file_notice = on_notice(priority=10, block=False)
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


@get_driver().on_startup
async def startup():
    global service, process_lock, profile, media, prompt_upload
    config = Settings.load()
    process_lock = ProcessLock(config.db_path)
    llm = LLM(config)
    store = Store(config.db_path)
    prompt_upload = PromptUpload(store, config.context_tokens)
    profile = Profile(store)
    media = Media(store, llm, config)
    tasks = Tasks(store, llm, config, sender=task_sender) if config.tasks_enabled else None
    service = Service(store, llm, config, Memory(store, llm, config), tasks, ImageGenerator(config))
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
        service.store.close()
    if process_lock:
        process_lock.close()


@matcher.handle()
async def receive(bot: Bot, event: MessageEvent):
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
        mode = media.voice_mode(event.user_id) if media and isinstance(reply, ChatReply) else 'off'
        if mode != 'on':
            await notify(reply)
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
