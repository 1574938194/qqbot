"""明确的画图请求走 Images API；不开放其他工具，也不把图片 URL 写入聊天。"""
import asyncio
import io
import logging
import re

import httpx
from PIL import Image

from .llm import ModelError
from .prompt_upload import download_file


class ImageReply(str):
    def __new__(cls, text, images):
        result = super().__new__(cls, text)
        result.images = images
        return result


def image_request(text):
    text = text.strip()
    if text.startswith('/draw '):
        return text[6:].strip()
    # 仅明确的出图动词开头；否定、讨论识图和引用内容不会触发。
    if re.match(r'^(?:(?:请|麻烦|帮我|给我|请帮我|能不能|可以|你能|你可以|我要你|我想让你)[，,\s]*)*'
                r'(?:画(?:一张|一幅|一个|一只|张|幅|个|只)|生成(?:一张|一幅|张|幅|图片|图像|插画|照片|图)|绘制|作一幅画)', text):
        return text
    if re.match(r'^(?:please\s+)?(?:generate|draw|create)\s+(?:an?\s+)?(?:image|picture|illustration|photo)\b', text, re.I):
        return text
    return None


class ImageGenerator:
    def __init__(self, config):
        self.config = config
        self.gate = asyncio.Semaphore(1)

    async def generate(self, prompt):
        if not self.config.image_model:
            raise ModelError('尚未配置图片生成模型，请管理员设置 IMAGE_MODEL。')
        async with self.gate:
            try:
                async with asyncio.timeout(self.config.image_timeout):
                    async with httpx.AsyncClient(trust_env=False, timeout=self.config.image_timeout) as client:
                        response = await client.post(self.config.base_url.rstrip('/') + '/images/generations',
                            headers={'Authorization': 'Bearer ' + self.config.api_key},
                            json={'model': self.config.image_model, 'prompt': prompt, 'n': 1})
                    if response.status_code in (401, 403):
                        raise ModelError('图片生成认证或权限不足，请管理员检查图片模型后端。')
                    response.raise_for_status()
                    data = response.json().get('data')
                    if not isinstance(data, list) or not data or not isinstance(data[0].get('url'), str):
                        raise ValueError('image response missing')
                    raw = await download_file(data[0]['url'], max_bytes=15 * 1024 * 1024)
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.width * image.height > 25000000:
                            raise ValueError('image dimensions')
                        image.load()
                        image = image.convert('RGB')
                        image.thumbnail((2048, 2048))
                        output = io.BytesIO()
                        image.save(output, format='JPEG', quality=92)
                    return ImageReply('图片已生成。', [output.getvalue()])
            except ModelError:
                raise
            except (TimeoutError, httpx.TimeoutException):
                raise ModelError('图片生成超时，请稍后重试；未写入成功对话。') from None
            except Exception as exc:
                logging.getLogger(__name__).warning('image generation failed: %s', type(exc).__name__)
                raise ModelError('图片生成失败，请稍后重试；未写入成功对话。') from None
