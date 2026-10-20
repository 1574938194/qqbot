"""显式运行：真实 buddyproxy 聊天、摘要调用；仅使用临时数据库，不输出正文或密钥。"""
import asyncio
import tempfile
from pathlib import Path

from qqbot.config import ADMIN, Settings
from qqbot.llm import LLM
from qqbot.service import Service
from qqbot.store import Store


async def main():
    config = Settings.load()
    llm = LLM(config)
    try:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / 'verify.db'))
            try:
                service = Service(store, llm, config)
                await service.handle(ADMIN, '你好小暖，我叫小明，喜欢猫，今天有点紧张。请简短回复。')
                if len(store.history(ADMIN)) != 1:
                    raise RuntimeError('真实聊天验证未成功，请检查代理状态。')
                # 构造明确标注的验收样本，额外发起真实摘要调用。
                for i in range(config.keep_rounds + 1):
                    store.append(ADMIN, f'验收样本{i}：我还在等待考试结果。', '慢慢来，我陪你等。')
                if not await service.compress(ADMIN) or not store.summary(ADMIN):
                    raise RuntimeError('真实摘要验证未成功。')
                print(f'PASS：{config.model} 真实聊天与摘要调用成功；正文与凭据未输出。')
            finally:
                store.close()
    finally:
        await llm.close()


if __name__ == '__main__':
    asyncio.run(main())
