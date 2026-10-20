"""仅回环监听的串行ONNX语音API，不记录输入正文与参考转写。"""
import asyncio
import io
import logging
import os
import sys
import wave
from contextlib import asynccontextmanager

for thread_variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(thread_variable, '1')
import numpy as np
from fastapi import FastAPI
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
import uvicorn

from engine import Engine

diagnostics = sys.stderr
engine = None
gate = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    global engine
    engine = Engine(os.getenv('VOICE_ASSETS', '/voices'), os.getenv('GENIE_SOURCE', '/app/genie_tts'))
    # 只预加载默认声音，避免三套模型同时驻留；加载失败时服务不报告ready。
    await run_in_threadpool(engine.select, 'aoi')
    sys.stdout = sys.stderr = open(os.devnull, 'w')
    logging.disable(logging.CRITICAL)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


class Speech(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    speaker: str = Field(default='aoi', pattern='^(aoi|noto|hayami)$')


@app.get('/health')
async def health():
    return {'status': 'ready' if engine else 'starting', 'engine': 'onnx',
            'active_speaker': engine.active if engine else None,
            'torch_loaded': any(name == 'torch' or name.startswith('torch.') for name in sys.modules)}


@app.post('/tts')
async def tts(request: Speech):
    try:
        async with gate:
            audio = await run_in_threadpool(engine.synthesize, request.text, request.speaker)
        output = io.BytesIO()
        with wave.open(output, 'wb') as stream:
            stream.setparams((1, 2, 32000, 0, 'NONE', 'not compressed'))
            stream.writeframes((audio * 32767).astype('<i2').tobytes())
        return Response(output.getvalue(), media_type='audio/wav')
    except Exception as exc:
        diagnostics.write(f'ONNX speech failed: {type(exc).__name__}\n')
        diagnostics.flush()
        return JSONResponse({'message': 'speech generation failed'}, status_code=503)


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('VOICE_PORT', '9880')),
                access_log=False, log_level='critical')
