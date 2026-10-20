import time

from qqbot.config import ADMIN, Settings
from qqbot.store import Store
from qqbot.tasks import Tasks


async def test_list_hides_finished_and_keeps_history(tmp_path):
    store = Store(str(tmp_path / 'db.sqlite3'))
    tasks = Tasks(store, None, Settings(task_workspace=str(tmp_path / 'files')))
    try:
        active = tasks.repo.create(ADMIN, '待处理', 'reminder', time.time() + 100)
        done = tasks.repo.create(ADMIN, '提醒验收', 'reminder', time.time())
        run = tasks.repo.claim(done, [])
        tasks.repo.finish(done['id'], run, 'succeeded', result='完成')
        tasks.repo.delivered(run, 1, done=True)
        assert '提醒验收' not in await tasks.command(ADMIN, '/task', 'list')
        assert '待处理' in await tasks.command(ADMIN, '/task', 'list')
        assert '提醒验收' in await tasks.command(ADMIN, '/task', 'list all')
        assert [t['id'] for t in tasks.repo.list(ADMIN)] == [active['id']]
        assert not tasks.repo.list(123, include_finished=True)
    finally:
        await tasks.close()
        store.close()


async def test_cleanup_preserves_pending_recurring_and_artifacts(tmp_path):
    store = Store(str(tmp_path / 'db.sqlite3'))
    tasks = Tasks(store, None, Settings(task_workspace=str(tmp_path / 'files')))
    try:
        now = time.time()
        old = now - 8 * 86400
        def terminal(text, delivered):
            task = tasks.repo.create(ADMIN, text, 'agent', old)
            run = tasks.repo.claim(task, [])
            tasks.repo.finish(task['id'], run, 'succeeded', now=old)
            tasks.repo.db.execute('INSERT INTO task_events(run_id,kind,content,created_at) VALUES (?,?,?,?)', (run, 'model', 'audit', old))
            tasks.repo.db.execute('INSERT INTO task_steps VALUES (?,?,?,?,?,?,?,?)', (run, 'call', 'calculate', '{}', 'succeeded', '2', 0, old))
            tasks.repo.db.commit()
            if delivered:
                tasks.repo.delivered(run, 1, done=True)
            return task, run
        expired, run = terminal('旧任务', True)
        pending, pending_run = terminal('未投递', False)
        recurring = tasks.repo.create(ADMIN, '循环提醒', 'reminder', old, interval=60)
        paused = tasks.repo.create(ADMIN, '暂停任务', 'agent', old)
        tasks.repo.control(ADMIN, paused['id'], 'pause')
        tasks.repo.note(ADMIN, '独立笔记', '保留')
        artifact = tasks.tools.directory(ADMIN, expired['id']) / 'result.txt'
        artifact.write_text('保留成果', encoding='utf-8')
        tasks.cleanup()
        assert tasks.repo.get(ADMIN, expired['id']) is None
        assert not tasks.repo.run(run) and not tasks.repo.steps(run)
        assert not tasks.repo.rows('SELECT * FROM task_events WHERE run_id=?', (run,))
        assert tasks.repo.run(pending_run)
        assert tasks.repo.get(ADMIN, recurring['id'])['state'] == 'scheduled'
        assert tasks.repo.get(ADMIN, paused['id'])['state'] == 'paused'
        assert tasks.repo.note(ADMIN, '独立笔记') == '保留' and artifact.exists()
        tasks.repo.delivered(pending_run, 1, done=True)
        tasks.next_cleanup = 0
        tasks.cleanup()
        assert tasks.repo.get(ADMIN, pending['id']) is None
    finally:
        await tasks.close()
        store.close()
