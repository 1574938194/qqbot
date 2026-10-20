"""使用真实模型验证启用任务后的普通聊天；临时数据，不向QQ投递。"""
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
    config = replace(Settings.load(), timeout=35, llm_rate_retries=0)
    llm = LLM(config)
    try:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(config, db_path=str(Path(directory) / 'chat.db'), task_workspace=str(Path(directory) / 'files'))
            store = Store(config.db_path)
            tasks = Tasks(store, llm, config)
            try:
                service = Service(store, llm, config, tasks=tasks)
                await service.handle(ADMIN, '你叫什么名字呀')
                if len(store.history(ADMIN)) != 1:
                    raise RuntimeError('真实普通聊天未成功；未输出正文，请检查代理状态。')
                print('PASS: real ordinary chat with task tools enabled; final body saved, no QQ delivery.')
            finally:
                await tasks.close()
                store.close()
    finally:
        await llm.close()


if __name__ == '__main__':
    asyncio.run(main())
