"""单实例推理入口：隐藏原版推理器的逐句输出日志。"""
import asyncio
import logging
import os
import sys
import warnings
import hashlib
import json
from pathlib import Path

import torch
import uvicorn

host = os.getenv('GSV_HOST', '127.0.0.1')
port = int(os.getenv('GSV_PORT', '9880'))
torch.set_num_threads(int(os.getenv('GSV_TORCH_THREADS', '1')))
torch.set_num_interop_threads(1)
manifest = json.loads(Path('/voices/manifest.json').read_text(encoding='utf-8'))
required = {'custom/gpt.ckpt', 'custom/sovits.pth', 'reference/aoi.wav'}
for name in ('GSV_BERT_ONNX', 'GSV_FIXED_REF'):
    if os.getenv(name):
        required.add(Path(os.environ[name]).resolve().relative_to('/voices').as_posix())
if not required.issubset(manifest['sha256']):
    raise RuntimeError('voice asset manifest incomplete')
for relative, expected in manifest['sha256'].items():
    target = (Path('/voices') / relative).resolve()
    if not target.is_relative_to(Path('/voices')) or not target.is_file():
        raise RuntimeError('voice asset missing')
    with target.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
            raise RuntimeError('voice asset checksum mismatch')
sys.argv = ['api_v2.py', '-a', host, '-p', str(port), '-c', '/etc/gsv/tts.yaml']
if os.getenv('GSV_ORT_LOW_MEMORY') == '1':
    from bert_onnx import low_memory_sessions
    low_memory_sessions()
if os.getenv('GSV_BERT_ONNX'):
    from bert_onnx import install
    install(os.environ['GSV_BERT_ONNX'])
import api_v2  # noqa: E402; 原版在导入时加载模型，加载失败保留启动错误栈。
if os.getenv('GSV_FIXED_REF'):
    from fixed_voice import install
    install(api_v2, os.environ['GSV_FIXED_REF'])


@api_v2.APP.get('/health')
async def health():
    return {'status': 'ready', 'model_version': api_v2.tts_config.version}


diagnostics = sys.stderr
quiet = open(os.devnull, 'w')
sys.stdout = sys.stderr = quiet
logging.disable(logging.CRITICAL)
warnings.simplefilter('ignore')


class QuietInference:
    def __init__(self, app):
        self.app = app
        self.gate = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        async def safe_send(message):
            if message['type'] == 'http.response.start' and message['status'] >= 400:
                diagnostics.write(f'GPT-SoVITS request failed: HTTP {message["status"]}\n')
                diagnostics.flush()
            await send(message)
        try:
            if scope['type'] == 'http' and scope.get('path') == '/tts':
                async with self.gate:
                    await self.app(scope, receive, safe_send)
            else:
                await self.app(scope, receive, safe_send)
        except Exception as exc:
            diagnostics.write(f'GPT-SoVITS request failed: {type(exc).__name__}\n')
            diagnostics.flush()
            raise RuntimeError('speech request failed') from None


uvicorn.run(QuietInference(api_v2.APP), host=host, port=port, access_log=False, log_level='critical')
