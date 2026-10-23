import logging
import asyncio
import time

from openai import AsyncOpenAI, AuthenticationError, APITimeoutError
from .config import Settings

class ModelError(Exception):
    pass


class LLM:
    def __init__(self, config: Settings):
        if not config.api_key:
            raise ValueError("未配置模型密钥，请设置 LLM_API_KEY 或 ~/.codebuddy/proxy.env")
        self.config = config
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url,
                                  timeout=config.timeout, max_retries=0)
        self._gate = asyncio.Lock()
        self._next_request = 0.0
        self._cooldown = 0.0

    async def create(self, **kwargs):
        for attempt in range(self.config.llm_rate_retries + 1):
            async with self._gate:
                delay = max(self._next_request, self._cooldown) - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                self._next_request = time.monotonic() + self.config.llm_min_interval
            try:
                return await self.client.chat.completions.create(**kwargs)
            except Exception as exc:
                limited = getattr(exc, 'status_code', None) == 429
                try:
                    body = exc.response.json()
                    error = body.get('error', {}) if isinstance(body, dict) else {}
                    limited = limited or (isinstance(error, dict) and (error.get('cause') == 'rate_limited' or error.get('code') == 14003))
                except (AttributeError, ValueError, TypeError):
                    pass
                if not limited:
                    raise
                if attempt == self.config.llm_rate_retries:
                    raise ModelError('模型代理请求限流，请稍后重试。') from None
                backoff = min(120, self.config.llm_rate_backoff * (2 ** attempt))
                self._cooldown = max(self._cooldown, time.monotonic() + backoff)
                logging.getLogger(__name__).warning('model rate limited; retry scheduled')

    async def complete(self, messages, *, summary=False):
        try:
            response = await self.create(model=self.config.model, messages=messages,
                max_tokens=self.config.summary_tokens if summary else self.config.max_reply_tokens)
            choice = response.choices[0] if response.choices else None
            content = choice.message.content if choice else None
            if not isinstance(content, str) or not content.strip():
                raise ModelError('模型没有返回正文，请稍后重试。')
            if choice.finish_reason == 'length':
                raise ModelError('模型输出达到长度限制，请缩短输入后重试。')
            return content.strip()
        except ModelError:
            raise
        except Exception as exc:
            # 不输出异常正文：SDK 错误可能包含请求、响应或鉴权信息。
            logging.getLogger(__name__).warning("model failure: %s", type(exc).__name__)
            if isinstance(exc, AuthenticationError):
                raise ModelError("模型认证失败，请联系管理员检查代理密钥。") from None
            if isinstance(exc, APITimeoutError):
                raise ModelError("模型响应超时，请稍后重试。") from None
            raise ModelError("模型暂时不可用，请稍后重试。") from None

    async def close(self):
        await self.client.close()
