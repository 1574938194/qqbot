import asyncio
import io
import json
import wave

import httpx
import pytest

from qqbot.config import Settings, ADMIN
from qqbot.llm import ModelError
from qqbot.media import Media
from qqbot.store import Store


def config(**changes):
    return Settings(tts_backend='gptsovits', tts_ref_audio='/voices/ref.wav',
                    tts_prompt_text='これはテストです。', tts_voice='测试克隆音色', **changes)


def audio():
    out = io.BytesIO()
    with wave.open(out, 'wb') as stream:
        stream.setparams((1, 2, 32000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x01\x00' * 3200)
    return out.getvalue()


async def test_sovits_request_and_voice_mode(tmp_path):
    store = Store(str(tmp_path / 'db'))
    media = Media(store, None, config())
    await media.client.aclose()
    def respond(request):
        assert request.url == 'http://127.0.0.1:9880/tts'
        payload = json.loads(request.content)
        assert payload['text'] == '你好'
        assert payload['ref_audio_path'] == '/voices/ref.wav'
        assert payload['prompt_lang'] == 'all_ja'
        assert payload['text_lang'] == 'zh'
        assert payload['media_type'] == 'wav' and not payload['streaming_mode']
        return httpx.Response(200, content=audio(), headers={'content-type': 'audio/wav'})
    media.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        assert await media.command(ADMIN, '/voice say 你好') == audio()
        assert media.voice_mode(ADMIN) == 'off'
        assert '测试克隆音色' in await media.command(ADMIN, '/voice')
    finally:
        await media.close()
        store.close()


@pytest.mark.parametrize('kind', ['http', 'timeout', 'empty', 'json', 'oversize'])
async def test_sovits_failure_never_falls_back(tmp_path, kind, caplog):
    store = Store(str(tmp_path / 'db'))
    media = Media(store, None, config())
    await media.client.aclose()
    def respond(request):
        if kind == 'timeout':
            raise httpx.ReadTimeout('private-upstream-detail', request=request)
        return httpx.Response(500 if kind == 'http' else 200,
                              content=b'x' * (10 * 1024 * 1024 + 1) if kind == 'oversize'
                              else b'' if kind == 'empty' else b'{"secret":"private-upstream-detail"}')
    media.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async def forbidden(text):
        raise AssertionError('must not silently change voice')
    media.edge_audio = media.sapi_audio = forbidden
    try:
        with pytest.raises(ModelError, match='语音生成失败'):
            await media.synthesize('你好')
        assert 'private-upstream-detail' not in caplog.text
    finally:
        await media.close()
        store.close()


async def test_sovits_serializes_inference(tmp_path):
    store = Store(str(tmp_path / 'db'))
    media = Media(store, None, config())
    active = maximum = 0
    async def synthesize(text):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        await asyncio.sleep(.01)
        active -= 1
        return audio()
    media.sovits_audio = synthesize
    try:
        await asyncio.gather(media.synthesize('甲'), media.synthesize('乙'))
        assert maximum == 1
    finally:
        await media.close()
        store.close()


def test_sovits_config_validation():
    with pytest.raises(ValueError):
        Settings(tts_backend='gptsovits')
    with pytest.raises(ValueError):
        config(tts_base_url='http://user:secret@example.com')
