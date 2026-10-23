import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from qqbot.config import ADMIN, Settings
from qqbot.image_generation import ImageGenerator, ImageReply, image_request
from qqbot.llm import ModelError
from qqbot.service import Service
from qqbot.store import Store


@pytest.mark.parametrize('text', ['帮我画一张蓝色的小猫图片', '生成一张图片：海边日落', '/draw a cat', 'Please generate an image of a cat'])
def test_explicit_drawing_intent(text):
    assert image_request(text)


@pytest.mark.parametrize('text', ['不要生成图片', '为什么不能生成图片？', '图片里是什么', '/tool 生成图片', '我今天画了一张画', '这个故事里的画一张图片是台词'])
def test_normal_discussion_not_drawing(text):
    assert image_request(text) is None


async def test_generator_calls_images_api_and_validates_download(monkeypatch):
    from qqbot import image_generation as module
    png = io.BytesIO()
    Image.new('RGB', (10, 10), 'blue').save(png, format='PNG')
    fetch = AsyncMock(return_value=png.getvalue())
    monkeypatch.setattr(module, 'download_file', fetch)
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        import json
        payload = json.loads(request.content)
        assert request.url.path == '/v1/images/generations'
        assert payload == {'model': 'hunyuan-image-alpha', 'prompt': 'a cat', 'n': 1}
        assert request.headers['authorization'] == 'Bearer test-key'
        calls.append(payload)
        return httpx.Response(200, json={'data': [{'url': 'https://public.example/image'}]})

    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    reply = await ImageGenerator(Settings(api_key='test-key')).generate('a cat')
    assert isinstance(reply, ImageReply) and reply.images[0].startswith(b'\xff\xd8')
    assert len(calls) == 1
    fetch.assert_awaited_once_with('https://public.example/image', max_bytes=15 * 1024 * 1024)


async def test_service_permissions_no_tools_failed_draw_not_saved(tmp_path):
    store = Store(str(tmp_path / 'db'))
    llm = SimpleNamespace(complete=AsyncMock(return_value='普通回复'))
    generator = SimpleNamespace(generate=AsyncMock(return_value=ImageReply('图片已生成。', [b'jpeg'])))
    service = Service(store, llm, Settings(), image_generator=generator)
    try:
        assert await service.handle(123, '画一张猫') is None
        reply = await service.handle(ADMIN, '画一张猫')
        assert reply.images == [b'jpeg'] and not llm.complete.called
        assert store.history(ADMIN)[0][1:] == ('画一张猫', '图片已生成。')
        generator.generate.side_effect = ModelError('图片生成失败')
        assert await service.handle(ADMIN, '画一张狗') == '图片生成失败'
        assert len(store.history(ADMIN)) == 1
        assert await service.handle(ADMIN, '为什么不能生成图片？') == '普通回复'
    finally:
        store.close()
