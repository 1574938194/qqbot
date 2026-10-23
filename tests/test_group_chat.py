from types import SimpleNamespace
from unittest.mock import AsyncMock

from nonebot.adapters.onebot.v11 import Message, MessageSegment
import pytest

from qqbot.config import ADMIN, Settings
from qqbot.group_chat import GROUP, GroupChat, accept_target_invite, addressed
from qqbot.service import Service
from qqbot.store import Store


@pytest.fixture
def setup(tmp_path):
    store = Store(str(tmp_path/'private.sqlite3'))
    store.set_prompt('PRIVATE PERSONA MUST NOT LEAK')
    store.append(ADMIN, 'PRIVATE MEMORY MUST NOT LEAK', '私聊回复')
    llm = SimpleNamespace(complete=AsyncMock(return_value='群内回复'))
    memory = SimpleNamespace(recall=AsyncMock(), flush=AsyncMock())
    private = Service(store, llm, Settings(db_path=str(tmp_path/'private.sqlite3')), memory)
    group = GroupChat(private, SimpleNamespace(describe=AsyncMock(return_value='图片有蓝色方块')))
    bot = SimpleNamespace(self_id='1946794276', send_group_msg=AsyncMock(), send_private_msg=AsyncMock())
    yield group, bot, private
    group.close();store.close()


def event(text='你好', *, uid=ADMIN, gid=GROUP, at='1946794276', image=False):
    message = Message(MessageSegment.text(text))
    if at:
        message += MessageSegment.at(at)
    if image:
        message += MessageSegment.image('fixture.png')
    return SimpleNamespace(message_type='group', group_id=gid, user_id=uid, message=message,
        get_plaintext=message.extract_plain_text)


def test_original_mention_survives_adapter_stripping_and_quote_is_not_mention():
    item=event()
    item.original_message=item.message.copy()
    item.message=Message('你好')
    assert addressed(item,'1946794276')
    item.original_message=Message('引用机器人但未 @')
    item.to_me=True
    assert not addressed(item,'1946794276')


async def test_only_admin_direct_mention_in_target_group_triggers(setup):
    group, bot, private = setup
    for item in (event(at=None), event(at='all'), event(uid=12345), event(gid=1), event(uid=1946794276)):
        await group.handle(bot, item)
    assert not private.llm.complete.called and not bot.send_group_msg.called
    assert not group.service.store.history(ADMIN)
    await group.handle(bot,event())
    messages=private.llm.complete.call_args.args[0]
    assert 'PRIVATE' not in str(messages)
    assert len(group.service.store.history(ADMIN)) == 1
    assert len(private.store.history(ADMIN)) == 1
    assert not private.memory.recall.called and not private.memory.flush.called
    bot.send_private_msg.assert_not_called()
    assert bot.send_group_msg.call_args.kwargs['group_id'] == GROUP


async def test_group_commands_cannot_expose_private_prompt_or_tools(setup):
    group, bot, private = setup
    for text in ('/prompt show', '/setprompt', '/tool 执行命令', '/whitelist list', '/say 你好'):
        await group.handle(bot,event(text))
    assert not private.llm.complete.called
    assert all('PRIVATE' not in str(c) for c in bot.send_group_msg.call_args_list)
    await group.handle(bot,event('记住本群的话题'))
    await group.handle(bot,event('/reset'))
    assert not group.service.store.history(ADMIN)
    assert private.store.history(ADMIN)


async def test_group_image_only_processed_after_authorized_mention(setup):
    group, bot, private = setup
    await group.handle(bot,event('看看图',image=True,at=None))
    group.media.describe.assert_not_called()
    await group.handle(bot,event('看看图',image=True))
    group.media.describe.assert_awaited_once()
    assert '蓝色方块' in str(private.llm.complete.call_args)


async def test_only_specific_group_invites_are_accepted_without_speaking():
    bot=SimpleNamespace(set_group_add_request=AsyncMock(), send_group_msg=AsyncMock())
    for kind,sub,gid in (('friend','invite',GROUP),('group','add',GROUP),('group','invite',1)):
        assert not await accept_target_invite(bot,SimpleNamespace(request_type=kind,sub_type=sub,group_id=gid,flag='fixture'))
    bot.set_group_add_request.assert_not_called()
    assert await accept_target_invite(bot,SimpleNamespace(request_type='group',sub_type='invite',group_id=GROUP,flag='fixture'))
    bot.set_group_add_request.assert_awaited_once_with(flag='fixture',sub_type='invite',approve=True)
    bot.send_group_msg.assert_not_called()
