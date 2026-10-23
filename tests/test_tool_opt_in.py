from unittest.mock import AsyncMock, Mock

import pytest

from qqbot.config import ADMIN, Settings
from qqbot.service import ChatReply, Service, tokens
from qqbot.store import Store


@pytest.fixture
def service(tmp_path):
    store = Store(str(tmp_path / 'opt-in.db'))
    model = Mock(complete=AsyncMock(return_value='我在呢。'))
    tasks = Mock(chat=AsyncMock(return_value='工具处理完成。'), command=AsyncMock(return_value='已创建任务。'))
    result = Service(store, model, Settings(), tasks=tasks)
    yield result
    store.close()


async def test_normal_chat_never_enters_tools_or_tool_budget(service):
    for text in ('你心里在想什么', '10分钟后提醒我喝水', '这句话里有 /tool 两个字', '/toolbox 查询'):
        reply = await service.handle(ADMIN, text)
        assert reply is not None
    service.tasks.chat.assert_not_called()
    service.tasks.command.assert_not_called()
    assert service.llm.complete.await_count == 3
    assert service.input_tokens(ADMIN, service.messages(ADMIN)) == tokens(service.messages(ADMIN))
    assert len(service.store.history(ADMIN)) == 3


async def test_only_explicit_tool_command_enters_tool_loop(service):
    assert await service.handle(123, '/tool 查询天气') is None
    assert await service.handle(ADMIN, '/tool 查询天气', private=False) is None
    assert '用法' in await service.handle(ADMIN, '/tool')
    service.tasks.chat.assert_not_called()
    reply = await service.handle(ADMIN, '/tool 查询天气', self_id=99999)
    assert reply == '工具处理完成。' and not isinstance(reply, ChatReply)
    assert service.tasks.chat.call_args.kwargs['bot_id'] == '99999'
    assert service.tasks.chat.call_args.args[1][-1]['content'] == '查询天气'
    service.llm.complete.assert_not_called()
    assert not service.store.history(ADMIN)


async def test_task_entry_and_legacy_prefix_share_management_and_reminders(service):
    await service.handle(ADMIN, '/task run 查询天气')
    service.tasks.command.assert_awaited_with(ADMIN, '/task', 'run 查询天气', bot_id='')
    await service.handle(ADMIN, '/tool /task run 查询天气', self_id=99999)
    service.tasks.command.assert_awaited_with(ADMIN, '/task', 'run 查询天气', bot_id='99999')
    await service.handle(ADMIN, '/task list')
    await service.handle(ADMIN, '/remind in 5m 喝水')
    assert service.tasks.command.await_count == 4
