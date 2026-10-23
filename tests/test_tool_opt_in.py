from unittest.mock import AsyncMock, Mock
import pytest
from qqbot.config import ADMIN, Settings
from qqbot.service import ChatReply, Service, tokens
from qqbot.store import Store

@pytest.fixture
def service(tmp_path):
    store = Store(str(tmp_path / 'commands.db'))
    model = Mock(complete=AsyncMock(return_value='我在呢。'))
    tasks = Mock(command=AsyncMock(return_value='已创建任务。'))
    result = Service(store, model, Settings(), tasks=tasks)
    yield result
    store.close()

async def test_legacy_backend_chat_never_enters_tasks(service):
    for text in ('你心里在想什么', '10分钟后提醒我喝水', '这句话里有 /tool 两个字', '/toolbox 查询'):
        assert await service.handle(ADMIN, text)
    service.tasks.command.assert_not_called()
    assert service.llm.complete.await_count == 3
    assert service.input_tokens(ADMIN, service.messages(ADMIN)) == tokens(service.messages(ADMIN))
    assert len(service.store.history(ADMIN)) == 3

async def test_explicit_task_is_isolated_from_companion_history(service):
    assert await service.handle(123, '/task run 查询天气') is None
    assert await service.handle(ADMIN, '/task run 查询天气', private=False) is None
    reply = await service.handle(ADMIN, '/task run 查询天气', self_id=99999)
    assert reply == '已创建任务。' and not isinstance(reply, ChatReply)
    service.tasks.command.assert_awaited_once_with(ADMIN, '/task', 'run 查询天气', bot_id='99999')
    service.llm.complete.assert_not_called()
    assert not service.store.history(ADMIN)

async def test_task_management_and_reminders_share_entry(service):
    for args in ('run 查询天气', 'list', 'remind in 5m 喝水'):
        await service.handle(ADMIN, '/task ' + args)
        service.tasks.command.assert_awaited_with(ADMIN, '/task', args, bot_id='')
    assert service.tasks.command.await_count == 3
