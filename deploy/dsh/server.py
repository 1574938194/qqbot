"""仅本机且需独立令牌的 DSH 服务；每轮拥有独立进程组。"""
import asyncio
import json
import os
import re
import secrets
import signal
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
gate = asyncio.Semaphore(1)


@app.get('/health')
async def health():
    from importlib.metadata import version
    installed = Path('/opt/dsh-plugins/node_modules/.bin/dsh').is_file()
    return {'status': 'ready' if installed else 'unavailable', 'engine': 'deepseek-harness',
            'runtime': 'node', 'sdk_version': version('deepseek-harness-sdk')}


@app.post('/run')
async def run(request: Request):
    token = os.environ.get('DSH_TOKEN', '')
    supplied = request.headers.get('authorization', '')
    if not token or not supplied.isascii() or not secrets.compare_digest(supplied, 'Bearer ' + token):
        raise HTTPException(403, '拒绝访问。')
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 128 * 1024:
            raise HTTPException(413, '任务过长。')
    try:
        data = json.loads(raw)
        assert data['uid'] == 1574938194
        assert all(isinstance(data[k], str) and re.fullmatch('[a-f0-9]{12}', data[k]) for k in ('task_id', 'run_id'))
        assert isinstance(data['instruction'], str) and 0 < len(data['instruction']) <= 50000
    except (ValueError, KeyError, TypeError, AssertionError):
        raise HTTPException(400, '任务参数错误。') from None
    async with gate:
        proc = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).with_name('worker.py')),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True)
        communicate = asyncio.create_task(proc.communicate(json.dumps(data).encode()))

        async def disconnected():
            while not await request.is_disconnected():
                await asyncio.sleep(.3)

        monitor = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait({communicate, monitor}, timeout=float(os.getenv('DSH_RUN_TIMEOUT', '900')),
                                         return_when=asyncio.FIRST_COMPLETED)
            if communicate not in done:
                raise HTTPException(504, '执行中断或超时，请检查任务状态。')
            output, _ = communicate.result()
            if proc.returncode or len(output) > 1024 * 1024:
                raise HTTPException(502, 'DSH 执行失败，请检查隔离服务和会话记录。')
            return JSONResponse(json.loads(output), headers={'Cache-Control': 'no-store'})
        finally:
            monitor.cancel()
            if proc.returncode is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), 4)
                except TimeoutError:
                    os.killpg(proc.pid, signal.SIGKILL)
            await asyncio.gather(communicate, monitor, return_exceptions=True)


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=32128, access_log=False, log_level='warning')
