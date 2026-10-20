"""启动真实 NoneBot ASGI 服务，模拟 NapCat 双向 WS 与模型 HTTP 接口。"""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import re
import io
import wave
from PIL import Image
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from qqbot.config import ADMIN


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def test_reverse_websocket(tmp_path):
    calls = []
    speech_calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path == '/tts':
                speech_calls.append(body)
                output = io.BytesIO()
                with wave.open(output, 'wb') as audio:
                    audio.setparams((1, 2, 32000, 0, 'NONE', 'not compressed'))
                    audio.writeframes(b'\x01\x00' * 32000)
                payload = output.getvalue()
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            calls.append(body)
            final = '[CQ:at,qq=123]最终正文' * 3
            if any(isinstance(m['content'], list) for m in calls[-1]['messages']):
                final = '图片里有一个蓝色方块。'
            # 即使请求使用工具协议，普通聊天正文也应直接正常投递。
            payload = json.dumps({'id': 'mock', 'object': 'chat.completion', 'created': 0,
                                  'model': 'mock', 'choices': [{'index': 0, 'finish_reason': 'stop',
                                  'message': {'role': 'assistant', 'content': final,
                                              'reasoning_content': '绝不发送的思考'}}]}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = free_port()
    env = {**os.environ, 'HOST': '127.0.0.1', 'PORT': str(port),
           'ONEBOT_ACCESS_TOKEN': 'test-access', 'LLM_API_KEY': 'test-only',
           'LLM_BASE_URL': f'http://127.0.0.1:{server.server_port}/v1',
           'DB_PATH': str(tmp_path / 'ws.db'), 'MESSAGE_CHARS': '12',
           # 等待提示由 test_reply_wait 覆盖，此处只检查最终正文分段收发。
           'CHAT_NOTICE_SECONDS': '60', 'CHAT_TIMEOUT': '90',
           'VISION_MODEL': 'vision-test', 'TTS_BACKEND': 'genie', 'TTS_TIMEOUT': '30',
           'TTS_BASE_URL': f'http://127.0.0.1:{server.server_port}'}
    logfile = tmp_path / 'bot.log'
    with logfile.open('w', encoding='utf-8') as output:
        process = subprocess.Popen([sys.executable, 'bot.py'], cwd=Path(__file__).resolve().parents[1],
                                   env=env, stdout=output, stderr=output)
        try:
            url = f'ws://127.0.0.1:{port}/onebot/v11/'
            headers = {'X-Self-ID': '99999', 'X-Client-Role': 'Universal', 'Authorization': 'Bearer test-access'}
            ws = None
            for _ in range(100):
                if process.poll() is not None:
                    pytest.fail('NoneBot 启动失败：' + logfile.read_text(encoding='utf-8'))
                try:
                    ws = await connect(url, additional_headers=headers, proxy=None)
                    break
                except OSError:
                    await asyncio.sleep(.1)
            assert ws is not None, 'NoneBot 未就绪'
            async with ws:
                with pytest.raises(InvalidStatus):
                    async with connect(url, additional_headers={**headers, 'Authorization': 'Bearer wrong'}, proxy=None):
                        pass

                def event(uid, text, group=False, image=False):
                    result = {'time': 1, 'self_id': 99999, 'post_type': 'message',
                              'message_type': 'group' if group else 'private',
                              'sub_type': 'normal' if group else 'friend', 'message_id': 1,
                              'user_id': uid, 'message': [{'type': 'text', 'data': {'text': text}}],
                              'raw_message': text, 'font': 0, 'sender': {'user_id': uid, 'nickname': '测试'}}
                    if group:
                        result['group_id'] = 100
                    if image:
                        result['message'].append({'type': 'image', 'data': {'file': 'test.png'}})
                    return json.dumps(result)

                for payload in (event(123, '非白名单秘密'), event(ADMIN, '群秘密', group=True),
                                    event(99999, '自身消息'), event(123, '图片消息', image=True)):
                    await ws.send(payload)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(ws.recv(), .3)
                assert not calls
                await ws.send(event(ADMIN, '链路测试秘密'))
                text = ''
                while len(text) < len('[CQ:at,qq=123]最终正文' * 3):
                    action = json.loads(await asyncio.wait_for(ws.recv(), 45))
                    assert action['action'] == 'send_private_msg'
                    assert action['params']['user_id'] == ADMIN
                    segments = action['params']['message']
                    assert all(segment['type'] == 'text' for segment in segments)
                    part = ''.join(segment['data']['text'] for segment in segments)
                    assert len(part) <= 12
                    text += part
                    await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {'message_id': 2}, 'echo': action['echo']}))
                assert text == '[CQ:at,qq=123]最终正文' * 3
                assert '绝不发送的思考' not in text
                assert len(calls) == 1
                await ws.send(event(ADMIN, '/remind in 1s 主动提醒验收'))
                async def receive_segment():
                    action = json.loads(await asyncio.wait_for(ws.recv(), 45))
                    assert action['action'] == 'send_private_msg'
                    assert action['params']['user_id'] == ADMIN
                    assert all(segment['type'] == 'text' for segment in action['params']['message'])
                    part = ''.join(segment['data']['text'] for segment in action['params']['message'])
                    assert len(part) <= 12
                    await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {'message_id': 3}, 'echo': action['echo']}))
                    return part
                acknowledgment = ''
                while not acknowledgment.endswith('北京时间'):
                    acknowledgment += await receive_segment()
                match = re.search(r'([a-f0-9]{12}) \[scheduled\]', acknowledgment)
                assert match, acknowledgment
                expected = f'任务 {match[1]} [succeeded]\n提醒：主动提醒验收'
                notification = ''
                while len(notification) < len(expected):
                    notification += await receive_segment()
                assert notification == expected
                assert len(calls) == 1  # 提醒不调用模型
                await ws.send(event(ADMIN, '/name 小暖'))
                action = json.loads(await asyncio.wait_for(ws.recv(), 45))
                assert action['action'] == 'set_qq_profile'
                assert action['params'] == {'nickname': '小暖'}
                await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {}, 'echo': action['echo']}))
                assert await receive_segment() == '机器人昵称已更新。'
                await ws.send(event(ADMIN, '/avatar'))
                prompt = ''
                while not prompt.endswith('/avatar cancel。'):
                    prompt += await receive_segment()
                assert '5分钟' in prompt
                await ws.send(event(ADMIN, '图片说明', image=True))
                action = json.loads(await asyncio.wait_for(ws.recv(), 45))
                assert action['action'] == 'get_image' and action['params']['file'] == 'test.png'
                await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {'file': 'C:/cache/test.png'}, 'echo': action['echo']}))
                action = json.loads(await asyncio.wait_for(ws.recv(), 45))
                assert action['action'] == 'set_qq_avatar'
                assert action['params'] == {'file': 'C:/cache/test.png'}
                await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {}, 'echo': action['echo']}))
                assert await receive_segment() == '机器人头像已更新。'
                assert len(calls) == 1  # 资料更新不调用模型
                image_path = tmp_path / 'blue.png'
                Image.new('RGB', (50, 50), 'blue').save(image_path)
                await ws.send(event(ADMIN, '看看这张图', image=True))
                action = json.loads(await asyncio.wait_for(ws.recv(), 45))
                assert action['action'] == 'get_image'
                await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {'file': str(image_path)}, 'echo': action['echo']}))
                image_reply = ''
                while len(image_reply) < len('[CQ:at,qq=123]最终正文' * 3):
                    image_reply += await receive_segment()
                assert image_reply == '[CQ:at,qq=123]最终正文' * 3
                assert len(calls) == 3
                assert calls[1]['model'] == 'vision-test'
                assert calls[1]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
                assert '图片里有一个蓝色方块' in str(calls[2]['messages'])
                await ws.send(event(ADMIN, '/voice on'))
                assert await receive_segment() == '已开启语音回复。'
                await ws.send(event(ADMIN, '/voice off'))
                assert await receive_segment() == '已切换为文字回复。'
                for speaker in ('noto', 'hayami', 'aoi'):
                    await ws.send(event(ADMIN, '/speaker ' + speaker))
                    acknowledgment = ''
                    while not acknowledgment.endswith('试听。'):
                        acknowledgment += await receive_segment()
                    await ws.send(event(ADMIN, '/say 你好小爱'))
                    action = json.loads(await asyncio.wait_for(ws.recv(), 35))
                    assert action['action'] == 'send_private_msg'
                    assert action['params']['message'][0]['type'] == 'record'
                    assert action['params']['message'][0]['data']['file'].startswith('base64://')
                    await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {'message_id': 4}, 'echo': action['echo']}))
                    assert len(calls) == 3  # /say 不调用模型
                    assert speech_calls[-1] == {'text': '你好小爱', 'speaker': speaker}
                await ws.send(event(ADMIN, '/speaker noto'))
                acknowledgment = ''
                while not acknowledgment.endswith('试听。'):
                    acknowledgment += await receive_segment()
                await ws.send(event(ADMIN, '/voice on'))
                assert await receive_segment() == '已开启语音回复。'
                await ws.send(event(ADMIN, '语音回复测试'))
                action = json.loads(await asyncio.wait_for(ws.recv(), 35))
                assert action['action'] == 'send_private_msg'
                assert action['params']['message'][0]['type'] == 'record'
                await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {'message_id': 5}, 'echo': action['echo']}))
                assert len(calls) == 4
                assert speech_calls[-1] == {'text': '[CQ:at,qq=123]最终正文' * 3, 'speaker': 'noto'}
        finally:
            process.terminate()
            process.wait(timeout=10)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    log = logfile.read_text(encoding='utf-8')
    assert '链路测试秘密' not in log and 'test-access' not in log and 'test-only' not in log
