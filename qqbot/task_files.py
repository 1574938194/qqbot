"""保留旧任务成果查询与管理员执行开关，不再维护自制模型工具。"""
import re
from pathlib import Path

from .config import ADMIN


class ToolError(ValueError):
    pass


class TaskFiles:
    def __init__(self, repo, config):
        self.repo = repo
        self.root = Path(config.task_workspace).resolve()

    def shell_enabled(self):
        row = self.repo.db.execute("SELECT value FROM settings WHERE key='task_shell_enabled'").fetchone()
        return bool(row and row[0] == 'true')

    def set_shell(self, uid, enabled):
        if uid != ADMIN:
            raise ToolError('只有超级管理员可以修改 DSH 执行开关。')
        with self.repo.db:
            self.repo.db.execute("INSERT OR REPLACE INTO settings VALUES ('task_shell_enabled',?)", ('true' if enabled else 'false',))

    def directory(self, uid, task_id):
        if not re.fullmatch(r'[a-f0-9]{12}', task_id):
            raise ToolError('无效任务目录。')
        path = self.root / str(uid) / task_id
        if not path.resolve().is_relative_to(self.root):
            raise ToolError('任务目录越界。')
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    async def execute(self, uid, task_id, name, arguments):
        directory = self.directory(uid, task_id)
        if name == 'list_files':
            return '\n'.join(str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file())[:10000] or '暂无文件。'
        if name == 'read_file':
            path = (directory / arguments['path']).resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                raise ToolError('文件不存在或路径越界。')
            with path.open('r', encoding='utf-8') as stream:
                return stream.read(10000)
        raise ToolError('旧版 agent 工具已移除，请使用 /tool 提交 DSH 任务。')

    async def close(self):
        pass
