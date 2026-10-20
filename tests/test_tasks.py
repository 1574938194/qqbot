import asyncio
import json
import time
from dataclasses import replace

import pytest

from qqbot.config import ADMIN, Settings
from qqbot.llm import ModelError, ModelTurn
from qqbot.scheduling import SHANGHAI, display_time, duration, next_due, schedule
from qqbot.service import Service
from qqbot.store import Store
from qqbot.tasks import Tasks
from qqbot.task_tools import SIDE_EFFECTS, ToolError


def tool(name, args, call_id='call_1'):
    return {'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}


class ScriptedModel:
    def __init__(self, turns=()):
        self.turns = list(turns)
        self.calls = []
        self.summaries = []

    async def respond(self, messages, *, tools=None, allow_plain=False):
        self.calls.append((json.loads(json.dumps(messages)), tools))
        if not self.turns:
            raise AssertionError('Unexpected model call')
        result = self.turns.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def complete(self, messages, *, summary=False):
        assert summary
        self.summaries.append(messages)
        return '执行检查点：已保存工具资料，继续完成当前任务，保留来源和文件路径。'


@pytest.fixture
async def manager(tmp_path):
    store = Store(str(tmp_path / 'tasks.db'))
    config = Settings(task_workspace=str(tmp_path / 'workspace'), task_poll_seconds=.01)
    model = ScriptedModel()
    sent = []
    async def sender(uid, text, bot_id):
        sent.append((uid, text, bot_id))
    tasks = Tasks(store, model, config, sender=sender)
    tasks.test_sent = sent
    yield tasks
    await tasks.close()
    store.close()


async def finish_tick(tasks):
    await tasks.tick()
    await asyncio.gather(*(worker for _, worker in tasks.running.values()), return_exceptions=True)
    await tasks.tick()


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


async def test_multistep_tools_artifacts_and_state(manager):
    t = manager
    t.llm.turns = [
        ModelTurn('', [tool('calculate', {'expression': '(12+8)*3'})]),
        ModelTurn('', [tool('write_file', {'path': 'report.txt', 'content': '计算结果是60'}, 'call_2'),
                       tool('note_set', {'key': '报告结果', 'value': '60'}, 'call_3')]),
        ModelTurn('已完成计算，结果为60，报告保存在 report.txt。', []),
    ]
    task = t.create(ADMIN, '计算后保存结果和笔记', bot_id='99999')
    await finish_tick(t)
    assert t.repo.get(ADMIN, task['id'])['state'] == 'succeeded'
    run = t.repo.latest_run(task['id'])
    assert run['iterations'] == 3 and run['notified']
    assert [s['state'] for s in t.repo.steps(run['id'])] == ['succeeded'] * 3
    assert (t.tools.directory(ADMIN, task['id']) / 'report.txt').read_text(encoding='utf-8') == '计算结果是60'
    assert t.repo.note(ADMIN, '报告结果') == '60'
    assert '60' in t.details(ADMIN, task['id'], steps=True)
    assert t.test_sent[0][0] == ADMIN and t.test_sent[0][2] == '99999'
    assert not t.store.history(ADMIN)  # 后台任务不会在 /reset 后恢复陪伴历史


async def test_reminder_recurrence_and_no_model(manager):
    t = manager
    task = t.create(ADMIN, '喝水', kind='reminder', mode='every', when='1m')
    with t.repo.db:
        t.repo.db.execute('UPDATE tasks SET next_run=? WHERE id=?', (time.time()-600, task['id']))
    await finish_tick(t)
    assert not t.llm.calls
    saved = t.repo.get(ADMIN, task['id'])
    assert saved['state'] == 'scheduled' and saved['next_run'] > time.time()
    assert '提醒：喝水' in t.test_sent[0][1]
    await t.tick()
    assert len(t.test_sent) == 1
    assert 'cancelled' in t.control(ADMIN, task['id'], 'cancel')


async def test_permissions_natural_creation_and_reset(manager):
    t = manager
    service = Service(t.store, t.llm, t.config, tasks=t)
    assert await service.handle(123, '/task run test') is None
    assert await service.handle(ADMIN, '/task run test', private=False) is None
    t.store.grant(123, True)
    assert '只有超级管理员' in await service.handle(123, '/tools shell on')
    t.llm.turns = [ModelTurn('', [tool('task_create', {'instruction': '提醒喝水', 'kind': 'reminder', 'mode': 'in', 'when': '10m'})]),
                   ModelTurn('已安排，10分钟后提醒你。', [])]
    reply = await service.handle(123, '10分钟后提醒我喝水', self_id=99999)
    assert '已安排' in reply
    task = t.repo.list(123)[0]
    assert task['bot_id'] == '99999'
    assert '未找到你的任务' in await service.handle(ADMIN, f"/task show {task['id']}")
    assert '未找到你的任务' in await service.handle(ADMIN, f"/task cancel {task['id']}")
    await service.handle(123, '/reset')
    assert not t.store.history(123)
    assert t.repo.get(123, task['id'])['state'] == 'scheduled'
    await service.handle(ADMIN, '/whitelist remove 123')
    assert t.repo.get(123, task['id'])['state'] == 'cancelled'
    assert await service.handle(123, '/task list') is None


async def test_cancel_inflight_model_and_pause(manager):
    t = manager
    started, release = asyncio.Event(), asyncio.Event()
    async def respond(messages, *, tools=None, allow_plain=False):
        started.set()
        await release.wait()
        return ModelTurn('不该写入的旧结果', [])
    t.llm.respond = respond
    task = t.create(ADMIN, '慢任务')
    await t.tick()
    await started.wait()
    t.control(ADMIN, task['id'], 'pause')
    await asyncio.gather(*(w for _, w in t.running.values()), return_exceptions=True)
    assert t.repo.latest_run(task['id'])['state'] == 'paused'
    assert not t.repo.latest_run(task['id'])['result']
    t.control(ADMIN, task['id'], 'cancel')
    await t.tick()
    release.set()
    assert t.repo.get(ADMIN, task['id'])['state'] == 'cancelled'


async def test_notification_retry_cursor_and_restart(manager):
    t = manager
    t.config = replace(t.config, message_chars=20)
    t.tools.config = t.config
    task = t.create(ADMIN, '很长的提醒' * 30, kind='reminder')
    sent, failed = [], False
    async def sender(uid, text, bot_id):
        nonlocal failed
        if len(sent) == 1 and not failed:
            failed = True
            raise RuntimeError('disconnected')
        sent.append(text)
    t.sender = sender
    await finish_tick(t)
    run = t.repo.latest_run(task['id'])
    assert run['notify_index'] == 1 and not run['notified']
    t.notification_retry.clear()  # 模拟重连/进程重启后的重试
    await t.notify()
    assert t.repo.run(run['id'])['notified']
    expected = f"任务 {task['id']} [succeeded]\n提醒：" + task['instruction']
    assert ''.join(sent) == expected


@pytest.mark.parametrize('side_effect', [False, True])
async def test_restart_checkpoint_and_unknown_effect(tmp_path, side_effect):
    path = str(tmp_path / 'persist.db')
    config = Settings(task_workspace=str(tmp_path / 'files'))
    store, model = Store(path), ScriptedModel()
    t = Tasks(store, model, config)
    task = t.create(ADMIN, '保存并检查结果')
    messages = t.initial_messages(task)
    run_id = t.repo.claim(task, messages)
    call = tool('write_file', {'path': 'result.txt', 'content': '已写入'}) if side_effect else tool('calculate', {'expression': '2+3'})
    messages.append(ModelTurn('', [call]).message())
    t.repo.plan(run_id, messages, [call], SIDE_EFFECTS)
    t.repo.begin_tool(run_id, call['id'])
    if side_effect:
        (t.tools.directory(ADMIN, task['id']) / 'result.txt').write_text('已写入', encoding='utf-8')
    await t.close()
    store.close()
    store = Store(path)
    model.turns = [ModelTurn('完成检查', [])]
    t = Tasks(store, model, config)
    t.repo.recover()
    if side_effect:
        assert t.repo.get(ADMIN, task['id'])['state'] == 'paused'
        await t.tick()
        assert not model.calls
        t.control(ADMIN, task['id'], 'resume')
    else:
        assert t.repo.get(ADMIN, task['id'])['state'] == 'scheduled'
    await finish_tick(t)
    assert t.repo.latest_run(task['id'])['id'] == run_id
    assert t.repo.latest_run(task['id'])['state'] == 'succeeded'
    if side_effect:
        assert '执行结果不确定' in str(model.calls[-1])
        assert t.repo.steps(run_id)[0]['state'] == 'failed'
    else:
        assert t.repo.steps(run_id)[0]['result'] == '5'
    await t.close()
    store.close()


async def test_model_failure_limits_and_compaction(manager):
    t = manager
    t.llm.turns = [ModelError('模型超时')]
    task = t.create(ADMIN, '会失败的任务')
    await finish_tick(t)
    assert t.repo.get(ADMIN, task['id'])['state'] == 'failed'
    assert '模型超时' in t.details(ADMIN, task['id'])
    t.control(ADMIN, task['id'], 'retry')
    t.config = replace(t.config, task_max_steps=1)
    t.llm.turns = [ModelTurn('', [tool('calculate', {'expression': '1+1'})])]
    await finish_tick(t)
    assert '达到任务模型轮数上限' in t.details(ADMIN, task['id'])
    task2 = t.create(ADMIN, '整理长资料')
    run_id = t.repo.claim(task2, t.initial_messages(task2))
    messages = t.initial_messages(task2) + [{'role': 'tool', 'tool_call_id': 'old', 'content': '长资料' * 5000}]
    compacted = await t.compact(task2, run_id, messages, t.tools.schemas(ADMIN))
    assert t.llm.summaries and len(compacted) == 5
    assert '检查点' in str(compacted)
    assert json.loads(t.repo.run(run_id)['messages']) == compacted


async def test_note_isolation_and_tool_errors_are_recoverable(manager):
    t = manager
    t.store.grant(123, True)
    task = t.create(ADMIN, '遇到错误再计算')
    t.llm.turns = [ModelTurn('', [tool('shell', {'language': 'python', 'code': 'print(1)'})]),
                   ModelTurn('', [tool('calculate', {'expression': '3*7'}, 'call_2')]),
                   ModelTurn('计算结果21，本机命令未启用。', [])]
    await finish_tick(t)
    steps = t.repo.steps(t.repo.latest_run(task['id'])['id'])
    assert [s['state'] for s in steps] == ['failed', 'succeeded']
    t.repo.note(ADMIN, 'secret', '管理员笔记')
    assert t.repo.note(123, 'secret') == '未找到笔记。'
    assert t.repo.note_keys(123) == []


async def test_ask_user_reply_preserves_tool_protocol(manager):
    t = manager
    t.llm.turns = [ModelTurn('', [tool('ask_user', {'question': '报告需要中文还是英文？'}),
                                      tool('write_file', {'path': 'premature.txt', 'content': '不应写入'}, 'call_2')]),
                   ModelTurn('', [tool('write_file', {'path': 'report.txt', 'content': '中文报告'}, 'call_3')]),
                   ModelTurn('中文报告已保存。', [])]
    task = t.create(ADMIN, '帮我写报告，语言需要询问我')
    await finish_tick(t)
    assert t.repo.get(ADMIN, task['id'])['state'] == 'waiting_input'
    assert '报告需要中文还是英文' in t.test_sent[0][1]
    assert not (t.tools.directory(ADMIN, task['id']) / 'premature.txt').exists()
    t.store.grant(123, True)
    with pytest.raises(ValueError):
        t.repo.reply(123, task['id'], '英文')
    run_id = t.repo.latest_run(task['id'])['id']
    assert '补充信息已保存' in await t.command(ADMIN, '/task', 'reply ' + task['id'] + ' 中文')
    await finish_tick(t)
    assert t.repo.get(ADMIN, task['id'])['state'] == 'succeeded'
    assert t.repo.latest_run(task['id'])['id'] == run_id
    messages = t.llm.calls[1][0]
    assistant_index = next(i for i, m in enumerate(messages) if m.get('tool_calls'))
    assert [m['role'] for m in messages[assistant_index+1:assistant_index+4]] == ['tool', 'tool', 'user']
    assert 'report.txt' in await t.command(ADMIN, '/task', 'files ' + task['id'])
    assert '中文报告' in await t.command(ADMIN, '/task', 'file ' + task['id'] + ' report.txt')
    assert run_id in await t.command(ADMIN, '/task', 'runs ' + task['id'])


async def test_scheduler_continues_while_notification_waits(manager):
    t = manager
    started, release = asyncio.Event(), asyncio.Event()
    async def slow_sender(uid, text, bot_id):
        started.set()
        await release.wait()
    t.sender = slow_sender
    t.create(ADMIN, '第一条', kind='reminder')
    t.start()
    await asyncio.wait_for(started.wait(), 2)
    second = t.create(ADMIN, '第二条', kind='reminder')
    for _ in range(100):
        if t.repo.get(ADMIN, second['id'])['state'] == 'succeeded':
            break
        await asyncio.sleep(.01)
    assert t.repo.get(ADMIN, second['id'])['state'] == 'succeeded'
    release.set()


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


async def test_resume_failed_model_uses_existing_checkpoint(manager):
    t = manager
    task = t.create(ADMIN, '先计算，再完成任务')
    t.llm.turns = [ModelTurn('', [tool('calculate', {'expression': '12*3'})]), ModelError('代理限流')]
    await finish_tick(t)
    run = t.repo.latest_run(task['id'])
    assert run['state'] == 'failed'
    assert len(t.repo.steps(run['id'])) == 1
    t.llm.turns = [ModelTurn('计算结果36，已完成。', [])]
    t.control(ADMIN, task['id'], 'resume')
    await finish_tick(t)
    final = t.repo.latest_run(task['id'])
    assert final['id'] == run['id'] and final['state'] == 'succeeded'
    assert len(t.repo.steps(run['id'])) == 1
    assert '36' in str(t.llm.calls[-1][0])
