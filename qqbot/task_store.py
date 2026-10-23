import json
import time
import uuid

from .scheduling import next_due


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


class TaskStore:
    """与聊天共用连接；每次事务内均无 await。"""
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, uid INTEGER NOT NULL, bot_id TEXT NOT NULL DEFAULT '',
          instruction TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
          next_run REAL, interval_seconds INTEGER, daily_time TEXT,
          created_at REAL NOT NULL, updated_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS tasks_due ON tasks(state,next_run);
        CREATE TABLE IF NOT EXISTS task_runs (
          id TEXT PRIMARY KEY, task_id TEXT NOT NULL, state TEXT NOT NULL,
          messages TEXT NOT NULL DEFAULT '[]', iterations INTEGER NOT NULL DEFAULT 0,
          result TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL, updated_at REAL NOT NULL,
          notify_index INTEGER NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS task_steps (
          run_id TEXT NOT NULL, call_id TEXT NOT NULL, name TEXT NOT NULL,
          arguments TEXT NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '',
          side_effect INTEGER NOT NULL, created_at REAL NOT NULL,
          PRIMARY KEY(run_id,call_id));
        CREATE TABLE IF NOT EXISTS task_notes (
          uid INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
          PRIMARY KEY(uid,key));
        CREATE TABLE IF NOT EXISTS task_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          kind TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL);
        ''')

    def rows(self, sql, args=()):
        cursor = self.db.execute(sql, args)
        keys = [c[0] for c in cursor.description]
        return [dict(zip(keys, row)) for row in cursor.fetchall()]

    def create(self, uid, instruction, kind, due, interval=None, daily=None, bot_id=''):
        task_id, now = uuid.uuid4().hex[:12], time.time()
        with self.db:
            self.db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            (task_id, uid, str(bot_id), instruction, kind, 'scheduled', due, interval, daily, now, now))
        return self.get(uid, task_id)

    def get(self, uid, task_id):
        rows = self.rows('SELECT * FROM tasks WHERE uid=? AND id=?', (uid, task_id))
        return rows[0] if rows else None

    def list(self, uid, limit=30, *, include_finished=False):
        condition = '' if include_finished else " AND state IN ('scheduled','running','paused','waiting_input')"
        return self.rows('SELECT * FROM tasks WHERE uid=?' + condition + ' ORDER BY created_at DESC LIMIT ?', (uid, limit))

    def prune(self, before, *, uid=None, task_ids=None):
        """事务清理终态任务及审计；待投递通知和可恢复执行不删除。"""
        condition = "t.state IN ('succeeded','failed','cancelled') AND t.updated_at<=?"
        args = [before]
        if uid is not None:
            condition += ' AND t.uid=?'
            args.append(uid)
        if task_ids is not None:
            if not task_ids:
                return 0
            condition += ' AND t.id IN (' + ','.join('?' for _ in task_ids) + ')'
            args.extend(task_ids)
        condition += """ AND NOT EXISTS (SELECT 1 FROM task_runs r WHERE r.task_id=t.id AND
          (r.state IN ('running','queued') OR (r.notified=0 AND r.state IN ('succeeded','failed','paused','waiting_input'))))"""
        with self.db:
            ids = [r['id'] for r in self.rows('SELECT t.id FROM tasks t WHERE ' + condition, args)]
            for task_id in ids:
                for table in ('task_steps', 'task_events'):
                    self.db.execute(f'DELETE FROM {table} WHERE run_id IN (SELECT id FROM task_runs WHERE task_id=?)', (task_id,))
                self.db.execute('DELETE FROM task_runs WHERE task_id=?', (task_id,))
                self.db.execute('DELETE FROM tasks WHERE id=?', (task_id,))
        return len(ids)

    def count_active(self, uid):
        return self.db.execute("SELECT COUNT(*) FROM tasks WHERE uid=? AND state IN ('scheduled','running','paused','waiting_input')", (uid,)).fetchone()[0]

    def latest_run(self, task_id):
        rows = self.rows('SELECT * FROM task_runs WHERE task_id=? ORDER BY created_at DESC LIMIT 1', (task_id,))
        return rows[0] if rows else None

    def run(self, run_id):
        rows = self.rows('SELECT * FROM task_runs WHERE id=?', (run_id,))
        return rows[0] if rows else None

    def steps(self, run_id):
        return self.rows('SELECT * FROM task_steps WHERE run_id=? ORDER BY created_at,rowid', (run_id,))

    def claim(self, task, messages):
        now = time.time()
        with self.db:
            updated = self.db.execute("UPDATE tasks SET state='running',updated_at=? WHERE id=? AND state='scheduled'", (now, task['id'])).rowcount
            if not updated:
                return None
            previous = self.latest_run(task['id'])
            if previous and previous['state'] == 'queued':
                run_id = previous['id']
                self.db.execute("UPDATE task_runs SET state='running',updated_at=? WHERE id=?", (now, run_id))
            else:
                run_id = uuid.uuid4().hex[:12]
                self.db.execute('INSERT INTO task_runs(id,task_id,state,messages,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                                (run_id, task['id'], 'running', encoded(messages), now, now))
        return run_id

    def due(self, now):
        return self.rows("SELECT * FROM tasks WHERE state='scheduled' AND next_run<=? ORDER BY next_run LIMIT 100", (now,))

    def plan(self, run_id, messages, calls, side_effects):
        now = time.time()
        with self.db:
            self.db.execute('INSERT INTO task_events(run_id,kind,content,created_at) VALUES (?,?,?,?)',
                            (run_id, 'model', encoded(messages[-1]), now))
            self.db.execute('UPDATE task_runs SET messages=?,iterations=iterations+1,updated_at=? WHERE id=?', (encoded(messages), now, run_id))
            for call in calls:
                self.db.execute('INSERT INTO task_steps VALUES (?,?,?,?,?,?,?,?)',
                                (run_id, call['id'], call['function']['name'], call['function']['arguments'], 'planned', '',
                                 int(call['function']['name'] in side_effects), now))

    def checkpoint(self, run_id, messages):
        with self.db:
            self.db.execute('UPDATE task_runs SET messages=?,updated_at=? WHERE id=?', (encoded(messages), time.time(), run_id))
            self.db.execute('INSERT INTO task_events(run_id,kind,content,created_at) VALUES (?,?,?,?)',
                            (run_id, 'checkpoint', encoded(messages), time.time()))

    def begin_tool(self, run_id, call_id):
        with self.db:
            self.db.execute("UPDATE task_steps SET state='running' WHERE run_id=? AND call_id=?", (run_id, call_id))

    def tool_result(self, run_id, call_id, result, messages, *, failed=False):
        with self.db:
            self.db.execute('UPDATE task_steps SET state=?,result=? WHERE run_id=? AND call_id=?',
                            ('failed' if failed else 'succeeded', result, run_id, call_id))
            self.db.execute('UPDATE task_runs SET messages=?,updated_at=? WHERE id=?', (encoded(messages), time.time(), run_id))

    def finish(self, task_id, run_id, state, *, result='', error='', now=None):
        now = time.time() if now is None else now
        task = self.rows('SELECT * FROM tasks WHERE id=?', (task_id,))[0]
        # 已被取消/暂停的任务不能因旧请求返回而重新变为成功。
        if task['state'] != 'running':
            return
        due = next_due(task, now=now)
        with self.db:
            self.db.execute('UPDATE task_runs SET state=?,result=?,error=?,updated_at=?,notify_index=0,notified=0 WHERE id=?', (state, result, error, now, run_id))
            self.db.execute('UPDATE tasks SET state=?,next_run=?,updated_at=? WHERE id=?',
                            ('scheduled' if due else state, due, now, task_id))

    def control(self, uid, task_id, action):
        task = self.get(uid, task_id)
        if not task:
            raise ValueError('未找到你的任务。')
        run = self.latest_run(task_id)
        if action in ('cancel', 'pause'):
            if task['state'] in ('succeeded', 'failed', 'cancelled'):
                raise ValueError('任务已经结束；可用 retry 创建新一轮执行。')
            state = 'cancelled' if action == 'cancel' else 'paused'
            with self.db:
                self.db.execute('UPDATE tasks SET state=?,updated_at=? WHERE id=?', (state, time.time(), task_id))
                if action == 'cancel':
                    self.db.execute('UPDATE task_runs SET notified=1 WHERE task_id=?', (task_id,))
                if run and run['state'] in ('running', 'queued'):
                    self.db.execute('UPDATE task_runs SET state=?,updated_at=? WHERE id=?', (state, time.time(), run['id']))
        elif action in ('resume', 'retry'):
            if task['state'] not in ('paused', 'failed', 'cancelled', 'succeeded'):
                raise ValueError('任务仍在等待或执行中。')
            if action == 'resume' and run and run['error'] == 'waiting_input':
                raise ValueError('任务正在等你补充信息，请用 /task reply 任务ID 回答内容。')
            if action == 'resume' and task['state'] in ('succeeded', 'cancelled'):
                raise ValueError('已完成或取消的任务请用 retry 开始新一轮；resume 仅恢复暂停或失败的执行。')
            with self.db:
                self.db.execute("UPDATE tasks SET state='scheduled',next_run=?,updated_at=? WHERE id=?", (time.time(), time.time(), task_id))
                if action == 'resume' and run and run['state'] in ('paused', 'failed'):
                    self.db.execute("UPDATE task_runs SET state='queued',notified=1,error='',updated_at=? WHERE id=?", (time.time(), run['id']))
                    # 不确定的副作用明确反馈给模型，由用户主动恢复后从检查状态开始。
                    messages = json.loads(run['messages'])
                    for step in self.steps(run['id']):
                        if step['state'] == 'running':
                            result = '进程中断，之前这次工具的执行结果不确定。用户已主动恢复；先检查实际状态，不要直接重复副作用操作。'
                            messages.append({'role': 'tool', 'tool_call_id': step['call_id'], 'content': result})
                            self.db.execute("UPDATE task_steps SET state='failed',result=? WHERE run_id=? AND call_id=?", (result, run['id'], step['call_id']))
                    self.db.execute('UPDATE task_runs SET messages=? WHERE id=?', (encoded(messages), run['id']))
        else:
            raise ValueError('未知任务操作。')
        return self.get(uid, task_id)

    def wait_for_input(self, task_id, run_id, question):
        with self.db:
            self.db.execute("UPDATE tasks SET state='waiting_input',updated_at=? WHERE id=? AND state='running'", (time.time(), task_id))
            self.db.execute("UPDATE task_runs SET state='waiting_input',result=?,error='waiting_input',notify_index=0,notified=0,updated_at=? WHERE id=?", (question, time.time(), run_id))

    def reply(self, uid, task_id, content):
        task = self.get(uid, task_id)
        run = self.latest_run(task_id) if task else None
        if not task or not run or run['error'] != 'waiting_input' or task['state'] not in ('waiting_input', 'paused'):
            raise ValueError('未找到正在等你回复的任务。')
        messages = json.loads(run['messages'])
        messages.append({'role': 'user', 'content': '用户补充信息：' + content})
        with self.db:
            self.db.execute("UPDATE task_runs SET state='queued',error='',result='',messages=?,notified=1,updated_at=? WHERE id=?", (encoded(messages), time.time(), run['id']))
            self.db.execute("UPDATE tasks SET state='scheduled',next_run=?,updated_at=? WHERE id=?", (time.time(), time.time(), task_id))

    def migrate_dsh(self):
        """仅升级首次暂停旧 agent，保留旧步骤和提醒，不自动重放副作用。"""
        if self.db.execute("SELECT 1 FROM settings WHERE key='dsh_migrated'").fetchone():
            return
        with self.db:
            self.db.execute("UPDATE task_runs SET state='paused',error='已迁移 DSH，请检查旧任务副作用后显式恢复。',notified=1 WHERE task_id IN (SELECT id FROM tasks WHERE kind='agent' AND state IN ('scheduled','running','paused','waiting_input')) AND state IN ('queued','running','waiting_input')")
            self.db.execute("UPDATE tasks SET state='paused' WHERE kind='agent' AND state IN ('scheduled','running','waiting_input')")
            self.db.execute("INSERT INTO settings VALUES ('dsh_migrated','true')")

    def recover(self):
        """恢复仅发生在机器人启动时；未知副作用暂停，其余从已存检查点恢复。"""
        for task in self.rows("SELECT * FROM tasks WHERE state='running'"):
            run = self.latest_run(task['id'])
            uncertain = run and any(s['state'] == 'running' and s['side_effect'] for s in self.steps(run['id']))
            with self.db:
                self.db.execute('UPDATE tasks SET state=?,next_run=? WHERE id=?',
                                ('paused' if uncertain else 'scheduled', time.time(), task['id']))
                if run:
                    self.db.execute('UPDATE task_runs SET state=?,error=? WHERE id=?',
                                    ('paused' if uncertain else 'queued', '进程中断，工具结果不确定，请检查后 /task resume。' if uncertain else '', run['id']))
                    if not uncertain:
                        self.db.execute("UPDATE task_steps SET state='planned' WHERE run_id=? AND state='running'", (run['id'],))

    def notifications(self):
        return self.rows("""SELECT r.*,t.uid,t.bot_id,t.instruction FROM task_runs r JOIN tasks t ON t.id=r.task_id
            WHERE r.notified=0 AND r.state IN ('succeeded','failed','paused','waiting_input') ORDER BY r.created_at LIMIT 30""")

    def delivered(self, run_id, index, done=False):
        with self.db:
            self.db.execute('UPDATE task_runs SET notify_index=?,notified=? WHERE id=?', (index, int(done), run_id))

    def note(self, uid, key, value=None):
        if value is not None:
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO task_notes VALUES (?,?,?)', (uid, key, value))
        row = self.db.execute('SELECT value FROM task_notes WHERE uid=? AND key=?', (uid, key)).fetchone()
        return row[0] if row else '未找到笔记。'

    def note_keys(self, uid):
        return [row[0] for row in self.db.execute('SELECT key FROM task_notes WHERE uid=? ORDER BY key LIMIT 100', (uid,))]
