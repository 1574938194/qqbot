import asyncio
from types import SimpleNamespace
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from qqbot.config import ADMIN
from qqbot.profile import Profile
from qqbot.store import Store


async def test_identity_commands_persist_without_changing_source_prompt(tmp_path):
    path = str(tmp_path / 'db')
    store, bot = Store(path), Bot()
    try:
        original = '角色原文，旧名字仅用于测试。'
        store.set_prompt(original)
        profile = Profile(store)
        assert '只有超级管理员' in await profile.handle(bot, event('/profile name bad', uid=123))
        assert '只有超级管理员' in await profile.handle(bot, event('/profile nickname bad', uid=123))
        assert not store.identity() and not bot.calls
        assert '下轮对话生效' in await profile.handle(bot, event('/profile name 爱'))
        assert not bot.calls
        assert '爱' in await profile.handle(bot, event('/profile name'))
        assert '已更新' in await profile.handle(bot, event('/profile nickname 小爱'))
        assert bot.calls == [('set_qq_profile', {'nickname': '小爱'})]
        assert store.prompt() == original
        store.close()
        store = Store(path)
        assert store.identity() == {'role_name': '爱', 'role_nickname': '小爱'}
        assert '"正式名字": "爱"' in store.model_prompt()
        assert '"昵称": "小爱"' in store.model_prompt()
        assert original in store.model_prompt()
        assert store.model_prompt().startswith('管理员设置的当前身份')
        bot.fail = True
        profile = Profile(store)
        assert '未确认成功' in await profile.handle(bot, event('/profile nickname 失败名字'))
        assert store.identity()['role_nickname'] == '小爱'
    finally:
        store.close()


async def test_current_name_overrides_old_persona_and_history(tmp_path):
    from qqbot.config import Settings
    from qqbot.service import Service
    store = Store(str(tmp_path / 'db'))
    try:
        original = '你是小暖，按这个名字自我介绍。'
        store.set_prompt(original)
        store.append(ADMIN, '你叫什么', '我叫小暖。')
        store.set_identity(nickname='姚菱心')
        profile = Profile(store)
        assert '「梦梦」' in await profile.handle(Bot(), event('/profile name 梦梦'))
        messages = Service(store, None, Settings()).messages(ADMIN, '你叫什么名字')
        wire = messages
        assert messages[-2]['role'] == 'assistant'
        assert messages[-2]['content'] == '我叫小暖。'
        assert '当前身份资料已同步' not in str(messages)
        system = wire[0]['content']
        assert system.index('"正式名字": "梦梦"') < system.index(original)
        assert system.rindex('"正式名字": "梦梦"') > system.index(original)
        assert '以当前正式名字自我介绍' in system
        assert 'role_name' not in system and 'role_nickname' not in system
        assert store.prompt() == original
        assert store.identity()['role_nickname'] == '姚菱心'
        assert store.history(ADMIN)[0][2] == '我叫小暖。'
        assert '角色名：梦梦' in await Service(store, None, Settings()).handle(ADMIN, '/chat status')
    finally:
        store.close()


class Bot:
    self_id = '99999'

    def __init__(self):
        self.calls, self.fail = [], False

    async def call_api(self, action, **kwargs):
        self.calls.append((action, kwargs))
        await asyncio.sleep(0)
        if self.fail:
            raise RuntimeError('private-upstream-error')
        return {'file': 'C:/napcat/first.png'} if action == 'get_image' else {}


def event(text='', *, uid=ADMIN, group=False, images=()):
    message = Message(text)
    for image in images:
        message += MessageSegment.image(image)
    return SimpleNamespace(message_type='group' if group else 'private', user_id=uid,
                           message=message, get_plaintext=lambda: message.extract_plain_text())


async def test_profile_permissions_name(tmp_path):
    store, bot = Store(str(tmp_path / 'db')), Bot()
    try:
        profile = Profile(store)
        assert '只有超级管理员' in await profile.handle(bot, event('/profile nickname bad', uid=123))
        assert await profile.handle(bot, event('/profile avatar', group=True)) is None
        assert await profile.handle(bot, event('/profile avatar', uid=99999)) is None
        assert not bot.calls
        assert '当前角色名字' in await profile.handle(bot, event('/profile nickname'))
        assert '用法' in await profile.handle(bot, event('/profile nickname one\ntwo'))
        assert '已更新' in await profile.handle(bot, event('/profile nickname 小暖'))
        assert bot.calls == [('set_qq_profile', {'nickname': '小暖'})]
        assert not store.history(ADMIN)
    finally:
        store.close()


async def test_avatar_restart_first_image_and_deadline(tmp_path):
    path = str(tmp_path / 'db')
    store, bot = Store(path), Bot()
    clock = [1000.]
    try:
        profile = Profile(store, clock=lambda: clock[0])
        assert await profile.handle(bot, event(images=['ignored'])) is None
        assert '5分钟' in await profile.handle(bot, event('/profile avatar'))
        store.close()
        store = Store(path)
        profile = Profile(store, clock=lambda: clock[0])
        assert await profile.handle(bot, event(images=['other'], uid=123)) is None
        assert await profile.handle(bot, event(images=['group'], group=True)) is None
        assert await profile.handle(bot, event('普通文本')) is None
        replies = await asyncio.gather(profile.handle(bot, event(images=['first', 'second'])),
                                       profile.handle(bot, event(images=['third'])))
        assert replies == ['机器人头像已更新。', None]
        assert bot.calls == [('get_image', {'file': 'first'}),
                             ('set_qq_avatar', {'file': 'C:/napcat/first.png'})]
        await profile.handle(bot, event('/profile avatar'))
        clock[0] += 300
        assert await profile.handle(bot, event(images=['expired'])) is None
        assert len(bot.calls) == 2
        await profile.handle(bot, event('/profile avatar'))
        assert '已取消' in await profile.handle(bot, event('/profile avatar cancel'))
        assert await profile.handle(bot, event(images=['cancelled'])) is None
    finally:
        store.close()


async def test_avatar_failure_consumes_wait(tmp_path, caplog):
    store, bot = Store(str(tmp_path / 'db')), Bot()
    try:
        profile = Profile(store)
        await profile.handle(bot, event('/profile avatar'))
        bot.fail = True
        assert '本次等待已结束' in await profile.handle(bot, event(images=['first']))
        assert await profile.handle(bot, event(images=['second'])) is None
        assert 'private-upstream-error' not in caplog.text
        assert len(bot.calls) == 1
    finally:
        store.close()
