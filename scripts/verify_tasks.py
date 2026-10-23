"""真实 DSH 验收：临时数据库，不投递 QQ。服务会保留专用测试目录。"""
import asyncio
import tempfile
from dataclasses import replace
from pathlib import Path
from qqbot.config import ADMIN, Settings
from qqbot.store import Store
from qqbot.tasks import Tasks

async def main():
    config = Settings.load()
    with tempfile.TemporaryDirectory() as directory:
        config = replace(config, db_path=str(Path(directory) / 'tasks.db'))
        store = Store(config.db_path)
        tasks = Tasks(store, None, config)
        try:
            tasks.tools.set_shell(ADMIN, True)
            task = tasks.create(ADMIN, '实际计算(17+25)*3，将纯数字结果写入result.txt，读取核验后给出结果。')
            await tasks.tick(notify=False)
            await asyncio.gather(*(worker for _, worker in tasks.running.values()))
            run = tasks.repo.latest_run(task['id'])
            assert run['state'] == 'succeeded', run['error']
            assert tasks.repo.steps(run['id'])[0]['name'] == 'dsh'
            result = await tasks.tools.execute(ADMIN, task['id'], 'read_file', {'path': 'result.txt'})
            assert result.strip() == '126', '共享任务目录中的实际文件结果错误'
            assert not store.history(ADMIN)
            print('PASS: real DSH, shared artifact=126, task state and history isolation; task=' + task['id'])
        finally:
            await tasks.close()
            store.close()

if __name__ == '__main__':
    asyncio.run(main())
