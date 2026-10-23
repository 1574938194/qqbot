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
import base64
import httpx
import sqlite3
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
            if self.path == '/v1/images/generations':
                payload=json.dumps({'data':[{'url':'https://example.com/generated.png'}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                return
            calls.append(body)
            assert '结构化JSON协议' not in str(body['messages'])
            assert 'tools' not in body and 'tool_choice' not in body
            final = '[CQ:at,qq=123]最终正文' * 3
            if any(isinstance(m['content'], list) for m in calls[-1]['messages']):
                final = '图片里有一个蓝色方块。'
            # 普通聊天始终只取正文，不进入工具协议。
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
           'QQBOT_GATEWAY_TOKEN': 'test-gateway-token',
           'LLM_BASE_URL': f'http://127.0.0.1:{server.server_port}/v1',
           'DB_PATH': str(tmp_path / 'ws.db'), 'MESSAGE_CHARS': '12',
           # 等待提示由 test_reply_wait 覆盖，此处只检查最终正文分段收发。
           'CHAT_NOTICE_SECONDS': '60', 'CHAT_TIMEOUT': '90',
           'VISION_MODEL': 'vision-test', 'TTS_BACKEND': 'genie', 'TTS_TIMEOUT': '30',
           'TTS_BASE_URL': f'http://127.0.0.1:{server.server_port}'}
    logfile = tmp_path / 'bot.log'
    with logfile.open('w', encoding='utf-8') as output:
        bootstrap = "import io,runpy; from PIL import Image; import qqbot.image_generation as m; b=io.BytesIO(); Image.new('RGB',(10,10),'blue').save(b,format='PNG'); exec('async def download(*a,**k): return b.getvalue()'); m.download_file=download; runpy.run_path('bot.py',run_name='__main__')"
        process = subprocess.Popen([sys.executable, '-c', bootstrap], cwd=Path(__file__).resolve().parents[1],
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
                await ws.send(event(ADMIN, '/draw a blue square'))
                image_action=json.loads(await asyncio.wait_for(ws.recv(),45))
                assert image_action['action']=='send_private_msg'
                assert image_action['params']['message'][0]['type']=='image'
                assert image_action['params']['message'][0]['data']['file'].startswith('base64://')
                await ws.send(json.dumps({'status':'ok','retcode':0,'data':{'message_id':22},'echo':image_action['echo']}))
                assert len(calls)==1  # 图片独立接口，命令不进入对话上下文。
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
                # QwenPaw 原生频道回调：鉴权、白名单与最终内容投递。
                async with httpx.AsyncClient(trust_env=False) as client:
                    target = f'http://127.0.0.1:{port}/internal/qwenpaw/deliver'
                    denied = await client.post(target, json={'uid': ADMIN, 'parts': []})
                    assert denied.status_code == 403
                    denied = await client.post(target, headers={'X-QQBot-Token': 'test-gateway-token'},
                        json={'uid': 123, 'parts': []})
                    assert denied.status_code == 403
                    pending = asyncio.create_task(client.post(target,
                        headers={'X-QQBot-Token': 'test-gateway-token'},
                        json={'uid': ADMIN, 'parts': [
                            {'type': 'reasoning', 'text': '隐藏推理'},
                            {'type': 'text', 'text': '任务完成'},
                            {'type': 'file', 'filename': 'report.txt',
                             'file_url': 'data:text/plain;base64,MTUz'}]}))
                    assert await receive_segment() == '任务完成'
                    action = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    assert action['action'] == 'upload_private_file'
                    assert action['params']['file'] == 'base64://MTUz'
                    assert action['params']['name'] == 'report.txt'
                    await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {}, 'echo': action['echo']}))
                    assert (await pending).status_code == 200
                assert len(calls) == 1
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
                await ws.send(event(ADMIN, '/tool 显式工具测试'))
                tool_reply = ''
                while not tool_reply.endswith('启用。'):
                    tool_reply += await receive_segment()
                assert 'DSH' in tool_reply
                assert len(calls) == 4
                database = sqlite3.connect(tmp_path / 'ws.db')
                history_count = database.execute('SELECT count(*) FROM turns').fetchone()[0]
                async def prompt_command():
                    await ws.send(event(ADMIN, '/setprompt'))
                    acknowledgment = ''
                    while not acknowledgment.endswith('/setprompt cancel。'):
                        acknowledgment += await receive_segment()
                async def prompt_done():
                    acknowledgment = ''
                    while not acknowledgment.endswith('本次等待已结束。'):
                        acknowledgment += await receive_segment()
                    assert '已更新' in acknowledgment
                await prompt_command()
                exact_prompt = '  测试统一人设\r\n第二行  '
                await ws.send(event(ADMIN, exact_prompt))
                await prompt_done()
                assert database.execute("SELECT value FROM settings WHERE key='prompt'").fetchone()[0] == exact_prompt
                await prompt_command()
                await ws.send(json.dumps({'time': 1, 'self_id': 99999, 'post_type': 'notice',
                    'notice_type': 'offline_file', 'user_id': ADMIN,
                    'file': {'id': 'prompt-file-id', 'name': '人物.md', 'size': 20}}))
                action = json.loads(await asyncio.wait_for(ws.recv(), 15))
                assert action['action'] == 'get_private_file_url'
                await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {}, 'echo': action['echo']}))
                action = json.loads(await asyncio.wait_for(ws.recv(), 15))
                assert action['action'] == 'get_file'
                exact_file = '文件原文\r\n第二行\r\n'
                await ws.send(json.dumps({'status': 'ok', 'retcode': 0,
                    'data': {'base64': base64.b64encode(exact_file.encode()).decode()}, 'echo': action['echo']}))
                await prompt_done()
                assert database.execute("SELECT value FROM settings WHERE key='prompt'").fetchone()[0] == exact_file
                assert database.execute('SELECT count(*) FROM turns').fetchone()[0] == history_count
                assert len(calls) == 4 and len(speech_calls) == 4
                database.close()
            # 真实 HTTP 网页入口不依赖 OneBot 在线，复用刚才 QQ 的上下文。
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', trust_env=False) as client:
                page = await client.get('/debug')
                assert page.status_code == 200
                token = re.search(r"const token='([^']+)'", page.text).group(1)
                client.headers['X-Debug-Token'] = token
                state = (await client.get('/debug/state')).json()
                assert len(state['history']) == history_count
                response = await client.post('/debug/chat', json={'text': '网页链路测试秘密'})
                assert response.status_code == 200
                assert response.json()['reply'] == '[CQ:at,qq=123]最终正文' * 3
                assert len(calls) == 5
                state = (await client.get('/debug/state')).json()
                assert state['history'][-1][0] == '网页链路测试秘密'
                assert len(state['history']) == history_count + 1
                await client.post('/debug/chat', json={'text': '/status'})
                assert len(calls) == 5
                assert len((await client.get('/debug/state')).json()['history']) == history_count + 1
                picture = io.BytesIO()
                Image.new('RGB', (20, 20), 'blue').save(picture, format='PNG')
                result = await client.post('/debug/chat', json={'text': '网页图片测试', 'files': [
                    {'name': 'blue.png', 'data': base64.b64encode(picture.getvalue()).decode()}]})
                assert result.status_code == 200 and result.json()['reply'] == '[CQ:at,qq=123]最终正文' * 3
                assert len(calls) == 7  # 一次识图、一次陪伴正文。
                assert calls[-2]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
                await client.post('/debug/chat', json={'text': '/setprompt'})
                web_prompt = '网页文件人设测试\r\n保留换行\r\n'
                result = await client.post('/debug/chat', json={'files': [
                    {'name': 'role.md', 'data': base64.b64encode(web_prompt.encode()).decode()}]})
                assert '已更新' in result.json()['reply'] and not result.json()['prompt_pending']
                database = sqlite3.connect(tmp_path / 'ws.db')
                assert database.execute("SELECT value FROM settings WHERE key='prompt'").fetchone()[0] == web_prompt
                assert database.execute('SELECT count(*) FROM turns').fetchone()[0] == history_count + 2
                database.close()
                assert len(calls) == 7
                # 在真实 NoneBot WS 上验证群事件只接受指定群、管理员、真实 @。
                async with connect(url, additional_headers=headers, proxy=None) as group_ws:
                    def group_event(uid=ADMIN, gid=707318959, mention='99999'):
                        payload=json.loads(event(uid,'群聊隔离测试',group=True))
                        payload['group_id']=gid
                        if mention:
                            payload['message'].append({'type':'at','data':{'qq':mention}})
                        return json.dumps(payload)
                    for payload in (group_event(123),group_event(gid=100),group_event(mention=None),group_event(mention='all')):
                        await group_ws.send(payload)
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(group_ws.recv(),.3)
                    assert len(calls)==7
                    await group_ws.send(group_event())
                    received=''
                    while len(received)<len('[CQ:at,qq=123]最终正文'*3):
                        action=json.loads(await asyncio.wait_for(group_ws.recv(),30))
                        assert action['action']=='send_group_msg'
                        assert action['params']['group_id']==707318959
                        received+=''.join(p['data']['text'] for p in action['params']['message'])
                        await group_ws.send(json.dumps({'status':'ok','retcode':0,'data':{'message_id':44},'echo':action['echo']}))
                    assert received=='[CQ:at,qq=123]最终正文'*3
                    assert len(calls)==8 and web_prompt not in str(calls[-1]['messages'])
                    for gid in (100,707318959):
                        await group_ws.send(json.dumps({'time':1,'self_id':99999,'post_type':'request',
                            'request_type':'group','sub_type':'invite','group_id':gid,'user_id':ADMIN,
                            'comment':'邀请测试','flag':'invite-fixture'}))
                        if gid==100:
                            with pytest.raises(TimeoutError):
                                await asyncio.wait_for(group_ws.recv(),.2)
                        else:
                            action=json.loads(await asyncio.wait_for(group_ws.recv(),10))
                            assert action['action']=='set_group_add_request'
                            assert action['params']['flag']=='invite-fixture' and action['params']['approve'] is True
                            await group_ws.send(json.dumps({'status':'ok','retcode':0,'data':{},'echo':action['echo']}))
        finally:
            process.terminate()
            process.wait(timeout=10)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    log = logfile.read_text(encoding='utf-8')
    assert '链路测试秘密' not in log and 'test-access' not in log and 'test-only' not in log
    assert '网页链路测试秘密' not in log and token not in log
    assert '网页文件人设测试' not in log and '网页图片测试' not in log
