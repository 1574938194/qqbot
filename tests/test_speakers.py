import asyncio
import io
import json
import wave

import httpx
import pytest

from qqbot.config import ADMIN, Settings
from qqbot.llm import ModelError
from qqbot.media import EDGE_VOICE, Media
from qqbot.store import Store


def wav():
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setparams((1, 2, 32000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x01\x00' * 320)
    return output.getvalue()


async def test_speaker_permissions_isolation_and_restart(tmp_path):
    path = str(tmp_path / 'voice.db')
    store = Store(path)
    store.db.execute('INSERT INTO whitelist(uid) VALUES (?)', (123,))
    store.db.commit()
    media = Media(store, None, Settings(tts_backend='genie'))
    try:
        assert await media.command(456, '/voice speaker noto') is None
        assert media.voice_mode(ADMIN) == 'off'
        assert '早见沙织' in await media.command(ADMIN, '/voice speaker list')
        assert '能登麻美子' in await media.command(ADMIN, '/voice speaker noto')
        assert '早见沙织' in await media.command(123, '/voice speaker 早见沙织')
        assert media.speaker(ADMIN) == 'noto' and media.speaker(123) == 'hayami'
        assert '不存在' in await media.command(ADMIN, '/voice speaker ../../secret')
        assert media.speaker(ADMIN) == 'noto'
        store.close()
        media.store = store = Store(path)
        assert media.speaker(ADMIN) == 'noto' and media.speaker(123) == 'hayami'
        assert '悠木碧' in await media.command(ADMIN, '/voice speaker reset')
        assert media.speaker(ADMIN) == 'aoi' and media.voice_mode(ADMIN) == 'off'
    finally:
        await media.close()
        store.close()


async def test_selected_speaker_payload_and_explicit_edge(tmp_path):
    store = Store(str(tmp_path / 'db'))
    media = Media(store, None, Settings(tts_backend='genie', tts_voice='悠木碧克隆'))
    await media.client.aclose()
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=wav())
    media.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async def edge(text, voice):
        assert voice == EDGE_VOICE and text == '原来的声音'
        return b'edge-audio'
    media.edge_audio = edge
    try:
        await media.command(ADMIN, '/voice speaker hayami')
        assert await media.command(ADMIN, '/voice say 你好') == wav()
        assert calls == [{'text': '你好', 'speaker': 'hayami'}]
        await media.command(ADMIN, '/voice speaker edge')
        assert await media.command(ADMIN, '/voice say 原来的声音') == b'edge-audio'
        assert len(calls) == 1
    finally:
        await media.close()
        store.close()


async def test_failed_clone_keeps_selection_and_does_not_fallback(tmp_path):
    store = Store(str(tmp_path / 'db'))
    media = Media(store, None, Settings(tts_backend='genie'))
    await media.client.aclose()
    media.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    async def forbidden(*args):
        raise AssertionError('must not change voice on failure')
    media.edge_audio = media.sapi_audio = forbidden
    try:
        await media.command(ADMIN, '/voice speaker noto')
        with pytest.raises(ModelError, match='语音生成失败'):
            await media.command(ADMIN, '/voice say 你好')
        assert media.speaker(ADMIN) == 'noto'
    finally:
        await media.close()
        store.close()


async def test_queued_request_keeps_its_selected_voice(tmp_path):
    store = Store(str(tmp_path / 'db'))
    media = Media(store, None, Settings(tts_backend='genie'))
    calls = []
    async def synthesize(text, speaker=None):
        calls.append(speaker)
        return wav()
    media.sovits_audio = synthesize
    try:
        await media.command(ADMIN, '/voice speaker noto')
        await media.tts_gate.acquire()
        task = asyncio.create_task(media.synthesize('你好', uid=ADMIN))
        await asyncio.sleep(0)
        await media.command(ADMIN, '/voice speaker hayami')
        media.tts_gate.release()
        await task
        assert calls == ['noto']
        await media.synthesize('现在', uid=ADMIN)
        assert calls == ['noto', 'hayami']
    finally:
        await media.close()
        store.close()
