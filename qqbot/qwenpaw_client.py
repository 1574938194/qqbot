"""现有 QQ 入口复用 QwenPaw 原生会话；不自行实现 Agent 工具循环。"""
import asyncio
import hashlib
import json
import logging
import uuid

import httpx

from .config import ADMIN
from .identity import clean_identity_echo
from .llm import ModelError


class QwenReply(str):
    def __new__(cls, text, parts=()):
        value = super().__new__(cls, text)
        value.parts = list(parts)
        return value


def sent_files(output):
    """只提取成功 send_file_to_user 的 DataBlock，绝不发送工具正文。"""
    calls, results = set(), []
    for message in output:
        if not isinstance(message, dict) or message.get('status') != 'completed':
            continue
        chunks = message.get('content', [])
        if not isinstance(chunks, list):
            continue
        for part in chunks:
            data = part.get('data') if isinstance(part, dict) else None
            if not isinstance(data, dict) or data.get('name') != 'send_file_to_user':
                continue
            if message.get('type') == 'plugin_call' and message.get('role') == 'assistant':
                calls.add(data.get('call_id'))
            elif message.get('type') == 'plugin_call_output' and message.get('role') == 'tool':
                results.append(data)
    files = []
    for data in results:
        if not data.get('call_id') or data['call_id'] not in calls or data.get('state') != 'success':
            continue
        try:
            blocks = json.loads(data.get('output', ''))
        except (ValueError, TypeError):
            continue
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict) or block.get('type') != 'data':
                continue
            source = block.get('source')
            if not isinstance(source, dict) or source.get('type') != 'url' or not isinstance(source.get('url'), str):
                continue
            mime = str(source.get('media_type', ''))
            kind = 'image' if mime.startswith('image/') else 'audio' if mime.startswith('audio/') else 'file'
            key = {'image': 'image_url', 'audio': 'data', 'file': 'file_url'}[kind]
            files.append({'type': kind, key: source['url']})
    return files


def final_content(response):
    """只收最终助手正文与附件，排除思考和工具输入/输出。"""
    if response.get('status') != 'completed' or response.get('error'):
        raise ModelError('QwenPaw 未正常完成，执行记录已保留，请检查任务状态后再重试。')
    output = response.get('output', [])
    if not isinstance(output, list):
        raise ModelError('QwenPaw 返回正文格式无效。')
    messages = [m for m in output if isinstance(m, dict) and m.get('type') == 'message'
                and m.get('role') == 'assistant' and m.get('status') == 'completed']
    if not messages:
        raise ModelError('QwenPaw 没有返回最终正文。')
    text, parts = '', sent_files(output)
    for message in messages:
        chunks = message.get('content', [])
        if not isinstance(chunks, list):
            continue
        chunks = [p for p in chunks if isinstance(p, dict)]
        visible = '\n'.join(str(p.get('text', p.get('refusal', ''))) for p in chunks
                            if p.get('type') in ('text', 'refusal'))
        if visible.strip():
            text = visible.strip()
        parts.extend(p for p in chunks if p.get('type') in ('file', 'image', 'audio'))
    text = clean_identity_echo(text)
    if not text and not parts:
        raise ModelError('QwenPaw 没有返回可发送内容。')
    return QwenReply(text or '任务已完成，附件如下。', parts)


class QwenPaw:
    def __init__(self, store, config, tasks=None):
        self.store, self.config, self.tasks = store, config, tasks
        self.synced = {}

    def session(self, uid):
        key = 'qwen-session-' + str(uid)
        row = self.store.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        if row:
            return row[0]
        value = 'qqbot-' + str(uid) + '-' + uuid.uuid4().hex[:12]
        with self.store.db:
            self.store.db.execute('INSERT INTO settings VALUES (?,?)', (key, value))
        return value

    def client(self, *, timeout=30):
        return httpx.AsyncClient(base_url=self.config.qwenpaw_base_url.rstrip('/'), trust_env=False,
            timeout=timeout, headers={'X-QQBot-Token': self.config.qwenpaw_token})

    async def sync(self, uid, *, reset=False):
        if not self.config.qwenpaw_token:
            raise ModelError('QwenPaw 网关未配置，请管理员检查服务。')
        execute = bool(uid == ADMIN and self.tasks and self.tasks.tools.shell_enabled())
        prompt, identity = self.store.prompt(), self.store.identity()
        fingerprint = hashlib.sha256(json.dumps([prompt, identity, execute], ensure_ascii=False).encode()).hexdigest()
        if not reset and self.synced.get(uid) == fingerprint:
            return
        history = [] if reset else [{'用户': u, '助手': clean_identity_echo(a)} for _, u, a in self.store.history(uid)]
        payload = {'uid': uid, 'prompt': prompt, 'identity': identity, 'execute': execute,
                   'reset': reset, 'summary': '' if reset else self.store.summary(uid), 'history': history}
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 3 * 1024 * 1024:
            raise ModelError('待迁移历史过大，原始数据已保留，请先压缩后重试。')
        async with self.client(timeout=120) as client:
            response = await client.post('/api/qqbot/sync', json=payload)
            response.raise_for_status()
        self.synced[uid] = fingerprint
        if reset:
            with self.store.db:
                self.store.db.execute('DELETE FROM settings WHERE key=?', ('qwen-session-' + str(uid),))

    async def stop(self, uid):
        try:
            async with self.client(timeout=15) as client:
                response = await client.post(f'/api/agents/qq-{uid}/console/chat/stop',
                    params={'chat_id': self.session(uid)})
                response.raise_for_status()
                stopped = response.json().get('stopped')
            return '已停止当前任务；已经产生的文件和外部操作会保留。' if stopped else '当前没有正在执行的任务。'
        except (httpx.HTTPError, ValueError):
            return '暂时无法确认停止结果，请在 QwenPaw 网页检查任务状态。'

    async def reset(self, uid):
        try:
            await self.sync(uid, reset=True)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ModelError('QwenPaw 清空未确认，原有 QQ 历史已保留，请稍后重试。') from None

    async def chat(self, uid, text, *, progress=None):
        try:
            await self.sync(uid)
            data = {'session_id': self.session(uid), 'user_id': str(uid), 'channel': 'console',
                    'input': [{'role': 'user', 'content': [{'type': 'text', 'text': text}]}]}
            final = None
            async with asyncio.timeout(self.config.qwenpaw_timeout):
                async with self.client(timeout=self.config.qwenpaw_timeout) as client:
                    async with client.stream('POST', f'/api/agents/qq-{uid}/console/chat', json=data) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith('data:'):
                                continue
                            raw = line[5:].strip()
                            if raw == '[DONE]':
                                continue
                            try:
                                event = json.loads(raw)
                            except ValueError:
                                raise ModelError('QwenPaw 响应中断，请检查任务状态后再重试。') from None
                            if not isinstance(event, dict):
                                raise ModelError('QwenPaw 响应无效，请检查任务状态。')
                            if event.get('object') == 'response' and event.get('status') in ('completed', 'failed', 'cancelled'):
                                final = event
            if not isinstance(final, dict):
                raise ModelError('QwenPaw 连接结束，尚未确认任务完成，请先检查网页状态。')
            return final_content(final)
        except asyncio.CancelledError:
            await self.stop(uid)
            raise
        except (TimeoutError, httpx.TimeoutException):
            await self.stop(uid)
            raise ModelError('这次执行等待超时，已请求停止；请检查已产生的结果后再重试。') from None
        except ModelError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logging.getLogger(__name__).warning('QwenPaw gateway failure: %s', type(exc).__name__)
            raise ModelError('QwenPaw 暂时不可用，原对话已保留。') from None
