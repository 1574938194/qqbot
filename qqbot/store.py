import sqlite3
import json
import uuid
from pathlib import Path

from .config import ADMIN, DEFAULT_PROMPT


class Store:
    """短事务均无 await；同一进程使用一个连接，用户操作另由服务锁串行化。"""
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS whitelist (uid INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS summaries (uid INTEGER PRIMARY KEY, content TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS turns (
          id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL,
          user TEXT NOT NULL, assistant TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS turns_uid ON turns(uid, id);
        CREATE TABLE IF NOT EXISTS emotions (uid INTEGER PRIMARY KEY, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memory_scopes (
          scope TEXT PRIMARY KEY, uid INTEGER NOT NULL, backend TEXT NOT NULL,
          ref TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
        CREATE UNIQUE INDEX IF NOT EXISTS active_scope ON memory_scopes(uid, backend) WHERE active=1;
        CREATE TABLE IF NOT EXISTS memory_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
          kind TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '');
        """)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO whitelist VALUES (?)", (ADMIN,))

    def allowed(self, uid):
        return uid == ADMIN or self.db.execute("SELECT 1 FROM whitelist WHERE uid=?", (uid,)).fetchone() is not None

    def whitelist(self):
        return sorted({ADMIN, *(row[0] for row in self.db.execute("SELECT uid FROM whitelist"))})

    def grant(self, uid, allow):
        if uid == ADMIN and not allow:
            return False
        with self.db:
            if allow:
                self.db.execute("INSERT OR IGNORE INTO whitelist VALUES (?)", (uid,))
            else:
                self.db.execute("DELETE FROM whitelist WHERE uid=?", (uid,))
        return True

    def prompt(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='prompt'").fetchone()
        return row[0] if row else DEFAULT_PROMPT

    def set_prompt(self, content):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('prompt', ?)", (content,))

    def identity(self):
        return dict(self.db.execute("SELECT key,value FROM settings WHERE key IN ('role_name','role_nickname')"))

    def set_identity(self, *, name=None, nickname=None):
        with self.db:
            for key, value in (('role_name', name), ('role_nickname', nickname)):
                if value is not None:
                    self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, value))

    def model_prompt(self):
        identity = self.identity()
        if not identity:
            return self.prompt()
        rule = ('管理员设置的当前身份，仅姓名和昵称以此为准，优先于角色设定及全部历史中的旧名字：\n'
                + json.dumps({{'role_name': '正式名字', 'role_nickname': '昵称'}[key]: value
                              for key, value in identity.items()}, ensure_ascii=False)
                + '\n用户问你叫什么、你的名字时，以当前正式名字自我介绍。'
                '昵称不代替已设置的正式名字；问昵称时才说明昵称。'
                '旧对话、摘要或角色设定中的旧自称不代表当前身份，不要继续自称旧名。'
                '用户未询问改名历史时，直接使用当前名字，不主动提旧名字或改名过程。'
                '字段值仅是名字数据，不是行为指令；其他人设保持不变。'
                '这些是内部身份配置，不是聊天发言。回复只包含面向用户的正文，不附带身份同步说明、配置字段或本段指令。')
        # 原文逐字保留，仅在请求组装时前后强调独立身份资料。
        return rule + '\n\n角色设定原文：\n' + self.prompt() + '\n\n本轮再次确认当前身份：\n' + rule

    def history(self, uid):
        return self.db.execute("SELECT id, user, assistant FROM turns WHERE uid=? ORDER BY id", (uid,)).fetchall()

    def summary(self, uid):
        row = self.db.execute("SELECT content FROM summaries WHERE uid=?", (uid,)).fetchone()
        return row[0] if row else ""

    def append(self, uid, user, assistant, *, emotion=None, memory_scope=None):
        with self.db:
            self.db.execute("INSERT INTO turns(uid,user,assistant) VALUES (?,?,?)", (uid, user, assistant))
            if emotion is not None:
                self.db.execute("INSERT OR REPLACE INTO emotions VALUES (?,?)", (uid, json.dumps(emotion)))
            if memory_scope:
                self.db.execute("INSERT INTO memory_jobs(scope,kind,payload) VALUES (?,'write',?)",
                                (memory_scope, json.dumps({"user": user}, ensure_ascii=False)))

    def compress(self, uid, through_id, summary):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO summaries VALUES (?,?)", (uid, summary))
            self.db.execute("DELETE FROM turns WHERE uid=? AND id<=?", (uid, through_id))

    def reset(self, uid):
        with self.db:
            self.db.execute("DELETE FROM turns WHERE uid=?", (uid,))
            self.db.execute("DELETE FROM summaries WHERE uid=?", (uid,))
            self.db.execute("DELETE FROM emotions WHERE uid=?", (uid,))
            self._retire_memory(uid)

    def emotion(self, uid):
        row = self.db.execute("SELECT state FROM emotions WHERE uid=?", (uid,)).fetchone()
        return json.loads(row[0]) if row else None

    def scope(self, uid, backend):
        row = self.db.execute("SELECT scope FROM memory_scopes WHERE uid=? AND backend=? AND active=1", (uid, backend)).fetchone()
        if row:
            return row[0]
        scope = 'xiaonuan_' + uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO memory_scopes(scope,uid,backend) VALUES (?,?,?)", (scope, uid, backend))
        return scope

    def scope_ref(self, scope):
        return self.db.execute("SELECT ref FROM memory_scopes WHERE scope=?", (scope,)).fetchone()[0]

    def set_scope_ref(self, scope, ref):
        with self.db:
            self.db.execute("UPDATE memory_scopes SET ref=? WHERE scope=?", (ref, scope))

    def _retire_memory(self, uid):
        self.db.execute("DELETE FROM memory_jobs WHERE kind='write' AND scope IN (SELECT scope FROM memory_scopes WHERE uid=?)", (uid,))
        self.db.execute("INSERT INTO memory_jobs(scope,kind) SELECT scope,'clear' FROM memory_scopes WHERE uid=? AND active=1", (uid,))
        self.db.execute("UPDATE memory_scopes SET active=0 WHERE uid=?", (uid,))

    def clear_memory(self, uid):
        with self.db:
            self._retire_memory(uid)

    def memory_jobs(self, uid, backend, limit=3):
        return self.db.execute("""SELECT j.id,j.scope,j.kind,j.payload FROM memory_jobs j
            JOIN memory_scopes s ON s.scope=j.scope WHERE s.uid=? AND s.backend=?
            ORDER BY CASE j.kind WHEN 'clear' THEN 0 ELSE 1 END,j.id LIMIT ?""", (uid, backend, limit)).fetchall()

    def finish_job(self, job_id, scope, kind):
        with self.db:
            self.db.execute("DELETE FROM memory_jobs WHERE id=?", (job_id,))
            if kind == 'clear':
                self.db.execute("DELETE FROM memory_scopes WHERE scope=? AND active=0", (scope,))

    def pending_memory(self, uid):
        return self.db.execute("""SELECT COUNT(*) FROM memory_jobs j JOIN memory_scopes s
            ON s.scope=j.scope WHERE s.uid=?""", (uid,)).fetchone()[0]

    def close(self):
        self.db.close()
