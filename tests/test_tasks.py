import asyncio
import time
from unittest.mock import AsyncMock
import pytest
from qqbot.config import ADMIN, Settings
from qqbot.store import Store
from qqbot.tasks import Tasks
from qqbot.service import Service
from qqbot.scheduling import SHANGHAI, display_time, duration, next_due, schedule


@pytest.fixture
async def manager(tmp_path):
    store = Store(str(tmp_path / 'db'))
    tasks = Tasks(store, None, Settings(task_workspace=str(tmp_path / 'files')))
    tasks.agent.run = AsyncMock(return_value='DSH 已完成')
    yield tasks
    await tasks.close()
    store.close()


async def finish_tick(tasks):
    await tasks.tick(notify=False)
    await asyncio.gather(*(worker for _, worker in tasks.running.values()))
    await tasks.tick(notify=False)


async def test_dsh_admin_optin_background_and_history_isolation(manager):
    t = manager
    s = Service(t.store, None, t.config, tasks=t)
    assert '启用' in await s.handle(ADMIN, '/task run 写文件测试')
    await s.handle(ADMIN, '/task shell on')
    t.store.grant(123, True)
    assert '超级管理员' in await s.handle(123, '/task shell off')
    assert '仅供管理员' in await s.handle(123, '/tool 写文件测试')
    reply = await s.handle(ADMIN, '/tool 写文件测试', self_id=99999)
    assert 'DSH 任务' in reply
    task = t.repo.list(ADMIN)[0]
    assert task['instruction'] == '写文件测试'
    await finish_tick(t)
    t.agent.run.assert_awaited_once()
    run = t.repo.latest_run(task['id'])
    assert run['state'] == 'succeeded' and run['result'] == 'DSH 已完成'
    assert t.repo.steps(run['id'])[0]['name'] == 'dsh'
    assert not t.store.history(ADMIN)


async def test_reminders_keep_recurrence_and_delivery(manager):
    t = manager
    t.sender = AsyncMock()
    task = t.create(123, '喝水', kind='reminder') if t.store.allowed(123) else None
    assert task is None
    task = t.create(ADMIN, '喝水', kind='reminder', mode='every', when='1m', bot_id='99999')
    t.repo.db.execute('UPDATE tasks SET next_run=? WHERE id=?', (time.time()-1, task['id']))
    t.repo.db.commit()
    await finish_tick(t)
    assert not t.agent.run.called
    assert t.repo.get(ADMIN, task['id'])['state'] == 'scheduled'
    await t.notify()
    assert '提醒：喝水' in t.sender.call_args.args[1]


async def test_cancel_and_restart_uncertain_dsh_pauses(manager):
    t = manager
    t.tools.set_shell(ADMIN, True)
    entered = asyncio.Event()

    async def wait(*args):
        entered.set()
        await asyncio.Event().wait()

    t.agent.run.side_effect = wait
    task = t.create(ADMIN, '耗时操作')
    await t.tick(notify=False)
    await entered.wait()
    run = t.repo.latest_run(task['id'])
    assert t.repo.steps(run['id'])[0]['state'] == 'running'
    t.control(ADMIN, task['id'], 'pause')
    await asyncio.gather(*(worker for _, worker in t.running.values()), return_exceptions=True)
    assert t.repo.get(ADMIN, task['id'])['state'] == 'paused'
    t.control(ADMIN, task['id'], 'resume')
    t.agent.run.side_effect = None
    await finish_tick(t)
    assert t.repo.latest_run(task['id'])['id'] == run['id']
    assert t.repo.latest_run(task['id'])['state'] == 'succeeded'


async def test_task_files_preserve_legacy_artifacts_and_block_escape(manager):
    t = manager
    task = t.repo.create(ADMIN, '旧任务', 'agent', time.time())
    path = t.tools.directory(ADMIN, task['id'])
    (path / 'result.txt').write_text('原成果', encoding='utf-8')
    assert 'result.txt' in await t.command(ADMIN, '/task', 'files ' + task['id'])
    assert '原成果' in await t.command(ADMIN, '/task', 'file ' + task['id'] + ' result.txt')
    assert '越界' in await t.command(ADMIN, '/task', 'file ' + task['id'] + ' ../../secret')

def test_schedule_timezone_duration_and_misfire():
    from datetime import datetime
    now = datetime(2026, 10, 20, 9, 0, tzinfo=SHANGHAI).timestamp()
    assert duration('10m') == 600
    assert schedule('in', '10m', now=now)[0] == now + 600
    assert schedule('at', '2026-10-20T10:00', now=now)[0] == now + 3600
    assert schedule('daily', '08:00', now=now)[0] == now + 23 * 3600
    assert schedule('daily', '10:00', now=now)[0] == now + 3600
    assert '北京时间' in display_time(now)
    assert next_due({'next_run': now, 'interval_seconds': 60, 'daily_time': None}, now=now+301) == now+360
    for mode, when in [('at', '2020-01-01'), ('daily', '25:00'), ('every', '1s'), ('in', '0m'), ('bad', '')]:
        with pytest.raises(ValueError):
            schedule(mode, when, now=now)

def test_single_instance_database_lock(tmp_path):
    from qqbot.process_lock import ProcessLock
    path = str(tmp_path / 'single.db')
    first = ProcessLock(path)
    try:
        with pytest.raises(RuntimeError, match='已有机器人实例'):
            ProcessLock(path)
    finally:
        first.close()
    second = ProcessLock(path)
    second.close()

async def test_dsh_upgrade_pauses_old_agent_once_and_keeps_reminder(manager):
    t=manager
    agent=t.repo.create(ADMIN,'旧任务','agent',time.time())
    reminder=t.repo.create(ADMIN,'旧提醒','reminder',time.time())
    t.repo.db.execute("DELETE FROM settings WHERE key='dsh_migrated'");t.repo.db.commit()
    t.repo.migrate_dsh()
    assert t.repo.get(ADMIN,agent['id'])['state']=='paused'
    assert t.repo.get(ADMIN,reminder['id'])['state']=='scheduled'
    fresh=t.repo.create(ADMIN,'新任务','agent',time.time())
    t.repo.migrate_dsh()
    assert t.repo.get(ADMIN,fresh['id'])['state']=='scheduled'
