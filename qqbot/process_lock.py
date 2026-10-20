"""按数据库持有操作系统锁，避免第二实例恢复正在执行的任务。"""
import os
from pathlib import Path


class ProcessLock:
    def __init__(self, db_path):
        path = Path(str(Path(db_path).resolve()) + '.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+b')
        if path.stat().st_size == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('已有机器人实例使用此数据库，请先关闭旧实例。') from None

    def close(self):
        if not self.file.closed:
            self.file.close()
