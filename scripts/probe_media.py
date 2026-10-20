"""只输出模型ID/测试状态，不输出聊天、图像数据或密钥。"""
import asyncio
import sys
from qqbot.config import Settings
from openai import AsyncOpenAI


async def main():
    c = Settings.load()
    print('Checking local model service...', flush=True)
    async with AsyncOpenAI(api_key=c.api_key, base_url=c.base_url, timeout=15, max_retries=0) as client:
        async with asyncio.timeout(25):
            result = await client.models.list()
            print('\n'.join(m.id for m in result.data), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
