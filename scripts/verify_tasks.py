"""真实 buddyproxy 工具调用与任务验收；无 QQ 投递，正式数据库不受影响。"""
import asyncio
import tempfile
from dataclasses import replace
from pathlib import Path

from qqbot.config import ADMIN, Settings
from qqbot.llm import LLM
from qqbot.service import Service
from qqbot.store import Store
from qqbot.tasks import Tasks


async def main():
    config = Settings.load()
    llm = LLM(config)
    try:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(config, db_path=str(Path(directory) / 'tasks.db'), task_workspace=str(Path(directory) / 'files'))
            store = Store(config.db_path)
            sent = []
            async def sender(uid, text, bot_id):
                sent.append((uid, text, bot_id))
            tasks = Tasks(store, llm, config, sender=sender)
            try:
                task = tasks.create(ADMIN,
                    '执行验收任务：必须调用calculate计算(17+25)*3，再调用write_file把结果以纯数字写入result.txt，'
                    '再用read_file读取确认，然后用note_set记录key=验收结果,value=126。最后简短说明结果。不可仅口头回答。')
                await tasks.tick()
                await asyncio.gather(*(worker for _, worker in tasks.running.values()))
                await tasks.tick()
                run = tasks.repo.latest_run(task['id'])
                if run['state'] != 'succeeded':
                    print('Saved iterations=' + str(run['iterations']) + ', steps=' + str([(s['name'], s['state']) for s in tasks.repo.steps(run['id'])]))
                    raise RuntimeError('真实多步任务失败：' + run['error'])
                names = {s['name'] for s in tasks.repo.steps(run['id']) if s['state'] == 'succeeded'}
                if not {'calculate', 'write_file', 'read_file', 'note_set'} <= names:
                    raise RuntimeError('模型没有完成全部指定工具调用。')
                result = (tasks.tools.directory(ADMIN, task['id']) / 'result.txt').read_text(encoding='utf-8').strip()
                if result != '126' or tasks.repo.note(ADMIN, '验收结果') != '126' or not sent:
                    raise RuntimeError('文件、笔记或结果通知验收失败。')
                service = Service(store, llm, config, tasks=tasks)
                await service.handle(ADMIN, '请实际调用task_create安排10分钟后提醒我喝水，kind=reminder，mode=in，when=10m。然后告诉我任务ID。', self_id=99999)
                reminders = [t for t in tasks.repo.list(ADMIN) if t['kind'] == 'reminder']
                if not reminders:
                    raise RuntimeError('真实自然语言任务创建失败。')
                print('PASS: real buddyproxy multi-step tools, artifact, note, state, notification and natural-language scheduling.')
            finally:
                await tasks.close()
                store.close()
    finally:
        await llm.close()


if __name__ == '__main__':
    asyncio.run(main())
