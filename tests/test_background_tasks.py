import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from qqbot.config import ADMIN, Settings
from qqbot.qwenpaw_client import QwenReply
from qqbot.service import Service
from qqbot.store import Store
from qqbot.task_intent import task_request
from qqbot.tasks import Tasks
from qqbot.web_chat import WebChat


@pytest.mark.parametrize('text,expected', [
    ('请用DSH开发一个Python CLI计算器', True), ('帮我搜索最新的Python新闻', True),
    ('请整理这个项目的文件', True), ('今天写代码很累', False), ('如何开发一个计算器', False),
    ('开发一个计算器需要多久？', False), ('只要解释代码，不要执行', False), ('/task list', False), ('帮我查一下AstrBot的功能', True), ('查一下我之前说过什么', False),
    ('\n以下JSON是用户上传的文本文件资料：{内容：请开发一个CLI项目}', False),
])
def test_background_intent(text, expected):
    assert task_request(text) is expected


@pytest.fixture
async def runtime(tmp_path):
    store = Store(str(tmp_path/'db'))
    config = Settings(agent_backend='qwenpaw', qwenpaw_token='test', qwenpaw_files=str(tmp_path),
                      task_workspace=str(tmp_path/'legacy'))
    tasks = Tasks(store, None, config, sender=AsyncMock())
    service = Service(store, None, config, tasks=tasks)
    tasks.tools.set_shell(ADMIN, True)
    entered, release = asyncio.Event(), asyncio.Event()

    async def chat(uid, text, **kwargs):
        if kwargs.get('task_id'):
            entered.set()
            await release.wait()
            return QwenReply('后台结果', [{'type': 'file', 'file_url': 'result.txt'}])
        return QwenReply('闲聊回复')

    fake = SimpleNamespace(chat=AsyncMock(side_effect=chat), stop=AsyncMock(return_value='停止'),
        reset=AsyncMock(), release_task=AsyncMock(),
        task_workspace=lambda uid, tid: tmp_path/'qwenpaw/workspaces'/('qq-'+str(uid))/'files/.tasks'/tid)
    service.qwen = tasks.qwen = fake
    yield service, tasks, entered, release
    release.set()
    await tasks.close()
    store.close()


async def test_queue_does_not_block_chat_or_commands_and_keeps_command_history_clean(runtime):
    service, tasks, entered, release = runtime
    reply = await service.handle(ADMIN, '请开发一个CLI计算器', self_id=99999)
    task = tasks.repo.list(ADMIN)[0]
    assert task['id'] in reply and task['kind'] == 'qwen'
    await tasks.tick(notify=False)
    await asyncio.wait_for(entered.wait(), 1)
    assert await asyncio.wait_for(service.handle(ADMIN, '今天过得怎么样'), 1) == '闲聊回复'
    assert task['id'] in await asyncio.wait_for(service.handle(ADMIN, '/task list'), 1)
    history = service.store.history(ADMIN)
    assert len(history) == 2 and all('/task list' not in h[1] for h in history)
    release.set()
    await asyncio.gather(*(w for _, w in tasks.running.values()))
    run = tasks.repo.latest_run(task['id'])
    assert run['state'] == 'succeeded' and tasks.repo.outputs(run['id'])
    assert len(service.store.history(ADMIN)) == 2  # 完成回传不会写回被清空的陪伴历史。
    assert '执行完成' in (await service.handle(ADMIN, '/task steps '+task['id']))


async def test_cancel_prevents_old_result_and_reset_preserves_independent_tasks(runtime):
    service, tasks, entered, release = runtime
    await service.handle(ADMIN, '/task run 开发一个CLI项目')
    task = tasks.repo.list(ADMIN)[0]
    await tasks.tick(notify=False)
    await entered.wait()
    await service.handle(ADMIN, '/chat reset')
    assert tasks.repo.get(ADMIN, task['id'])['state'] == 'running'
    assert task['id'] in await service.handle(ADMIN, '/task stop')
    release.set()
    await asyncio.gather(*(w for _, w in tasks.running.values()), return_exceptions=True)
    assert tasks.repo.get(ADMIN, task['id'])['state'] == 'cancelled'
    assert not service.store.history(ADMIN)
    assert not tasks.repo.outputs(tasks.repo.latest_run(task['id'])['id'])


async def test_delivery_checkpoint_retries_attachment_without_resending_text(runtime):
    _, tasks, _, release = runtime
    task = tasks.create(ADMIN, '创建项目文件')
    await tasks.tick(notify=False)
    release.set()
    await asyncio.gather(*(w for _, w in tasks.running.values()))
    run = tasks.repo.latest_run(task['id'])
    tasks.sender = AsyncMock(side_effect=[None, RuntimeError('offline'), None])
    await tasks.notify()
    assert tasks.repo.run(run['id'])['notify_index'] == 1
    assert tasks.repo.run(run['id'])['notified'] == 0
    tasks.notification_retry.clear()
    await tasks.notify()
    assert tasks.repo.run(run['id'])['notified'] == 1
    assert isinstance(tasks.sender.call_args_list[1].args[1], dict)
    assert isinstance(tasks.sender.call_args_list[2].args[1], dict)


async def test_restart_pauses_uncertain_work_and_resume_uses_saved_run(runtime):
    _, tasks, _, _ = runtime
    task = tasks.create(ADMIN, '开发一个CLI项目')
    run_id = tasks.repo.claim(task, tasks.initial_messages(task))
    tasks.repo.plan(run_id, tasks.initial_messages(task), [{'id':'x', 'function':{'name':'qwenpaw','arguments':'{}'}}], {'qwenpaw'})
    tasks.repo.begin_tool(run_id, 'x')
    tasks.repo.recover()
    assert tasks.repo.get(ADMIN, task['id'])['state'] == 'paused'
    tasks.control(ADMIN, task['id'], 'resume')
    assert tasks.repo.latest_run(task['id'])['id'] == run_id
    assert tasks.repo.latest_run(task['id'])['state'] == 'queued'


async def test_web_tasks_guard_ownership_and_artifact_download(runtime, tmp_path):
    service, tasks, _, release = runtime
    task = tasks.create(ADMIN, '创建项目文件')
    await tasks.tick(notify=False)
    release.set()
    await asyncio.gather(*(w for _, w in tasks.running.values()))
    run = tasks.repo.latest_run(task['id'])
    artifact = tmp_path/'qwenpaw/workspaces'/('qq-'+str(ADMIN))/'files/.tasks'/task['id']/'files/result.txt'
    artifact.parent.mkdir(parents=True)
    artifact.write_text('verified result')
    tasks.repo.save_outputs(run['id'], [{'type':'file','file_url':'file:///state/'+artifact.relative_to(tmp_path).as_posix()}])
    app = FastAPI()
    web = WebChat(app, lambda:(service,None,None,None), lambda:{})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('127.0.0.1',1)), base_url='http://127.0.0.1') as c:
        assert (await c.get('/debug/tasks')).status_code == 403
        headers = {'X-Debug-Token': web.token}
        data = (await c.get('/debug/tasks',headers=headers)).json()['tasks']
        assert data[0]['id'] == task['id'] and data[0]['outputs'][0]['name'] == 'result.txt'
        params = {'id':task['id'], 'run':run['id'], 'index':'0'}
        assert (await c.get('/debug/task-file',params=params,headers=headers)).status_code == 200
        params['run']='stale'
        assert (await c.get('/debug/task-file',params=params,headers=headers)).status_code == 404

async def test_failed_native_acceptance_is_not_delivered_as_success(runtime):
    _, tasks, _, release = runtime
    task = tasks.create(ADMIN, '开发一个CLI项目')
    tasks.workflow_state = lambda *args: {'status':'blocked'}
    await tasks.tick(notify=False)
    release.set()
    await asyncio.gather(*(w for _, w in tasks.running.values()))
    run = tasks.repo.latest_run(task['id'])
    assert run['state'] == 'failed' and not tasks.repo.outputs(run['id'])
    assert '验收' in run['error']


async def test_progress_is_deduplicated_and_stops_after_completion(runtime):
    _, tasks, entered, release = runtime
    task = tasks.create(ADMIN, '开发一个CLI项目')
    await tasks.tick(notify=False)
    await entered.wait()
    await tasks.notify_progress()
    await tasks.notify_progress()
    assert tasks.sender.await_count == 1
    run = tasks.repo.latest_run(task['id'])
    tasks.repo.progress(run['id'], '独立验收中')
    await tasks.notify_progress()
    assert tasks.sender.await_count == 2
    release.set()
    await asyncio.gather(*(w for _, w in tasks.running.values()))
    await tasks.notify_progress()
    assert tasks.sender.await_count == 2
