"""管理员显式开启的5分钟人设接收；内容不交给模型、不写聊天、不记录日志。"""
import asyncio
import base64
import ipaddress
import logging
from pathlib import Path
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .config import ADMIN

MAX_BYTES = 512 * 1024
PROMPT_UPLOAD_HELP = '\n/setprompt（5分钟内下一条文本或txt/md文件设为统一人设）\n/setprompt cancel'


async def download_file(url, *, max_bytes=MAX_BYTES):
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        for _ in range(4):
            parsed = urlsplit(url)
            port = 443 if parsed.scheme == 'https' else 80
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                    or parsed.username or parsed.password or parsed.port not in (None, port)):
                raise ValueError('invalid url')
            addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
            ips = sorted({entry[4][0] for entry in addresses}, key=lambda ip: ':' in ip)
            if not ips or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in ips):
                raise ValueError('private url')
            authority = '[' + ips[0] + ']' if ':' in ips[0] else ips[0]
            pinned = urlunsplit((parsed.scheme, authority, parsed.path or '/', parsed.query, ''))
            extensions = {'sni_hostname': parsed.hostname} if parsed.scheme == 'https' else {}
            async with client.stream('GET', pinned, headers={'Host': parsed.hostname}, extensions=extensions) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('location', ''))
                    continue
                response.raise_for_status()
                if int(response.headers.get('content-length', '0')) > max_bytes:
                    raise ValueError('file too large')
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ValueError('file too large')
                return bytes(data)
    raise ValueError('too many redirects')


def decode_text(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('file too large')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = raw.decode('utf-16')
    else:
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('gb18030')
    if '\0' in text:
        raise ValueError('binary file')
    return text


class PromptUpload:
    def __init__(self, store, context_tokens, *, clock=time.time, downloader=download_file):
        self.store, self.context_tokens = store, context_tokens
        self.clock, self.download = clock, downloader
        self.lock = asyncio.Lock()

    def key(self, bot_id):
        return 'prompt_pending:' + str(bot_id)

    def deadline(self, bot_id):
        row = self.store.db.execute('SELECT value FROM settings WHERE key=?', (self.key(bot_id),)).fetchone()
        return float(row[0]) if row else None

    def clear(self, bot_id):
        with self.store.db:
            self.store.db.execute('DELETE FROM settings WHERE key=?', (self.key(bot_id),))

    async def message(self, bot, event):
        if event.message_type != 'private' or event.user_id == int(bot.self_id):
            return None
        pure_text = all(segment.type == 'text' for segment in event.message)
        raw_text = event.get_plaintext() if pure_text else None
        parts = raw_text.strip().split(maxsplit=1) if raw_text is not None else []
        command = parts[0].lower() if parts else ''
        if command == '/setprompt':
            if event.user_id != ADMIN:
                return '只有超级管理员可以修改统一人设。'
            async with self.lock:
                if len(parts) == 2 and parts[1].strip() == 'cancel':
                    self.clear(bot.self_id)
                    return '已取消等待人设内容。'
                if len(parts) > 1:
                    return '用法：/setprompt 或 /setprompt cancel'
                with self.store.db:
                    self.store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (self.key(bot.self_id), str(self.clock() + 300)))
                return '请在5分钟内发送下一条非命令文本，或上传txt/md文件，将其原文设为统一system prompt。取消请用 /setprompt cancel。'
        if event.user_id != ADMIN or command.startswith('/'):
            return None
        files = [segment.data for segment in event.message if segment.type == 'file']
        if not files and (raw_text is None or not raw_text.strip()):
            return None
        return await self.accept(bot, text=raw_text if not files else None, file=files[0] if files else None)

    async def notice(self, bot, event):
        if (getattr(event, 'notice_type', None) != 'offline_file' or getattr(event, 'user_id', None) != ADMIN
                or getattr(event, 'group_id', None) is not None):
            return None
        file = getattr(event, 'file', None)
        if hasattr(file, 'model_dump'):
            file = file.model_dump()
        return await self.accept(bot, file=file) if isinstance(file, dict) else None

    async def file_text(self, bot, file):
        if Path(str(file.get('name', ''))).suffix.lower() not in ('.txt', '.md'):
            raise ValueError('unsupported file')
        if int(file.get('size', file.get('file_size', 0)) or 0) > MAX_BYTES:
            raise ValueError('file too large')
        url = file.get('url')
        file_id = file.get('file_id') or file.get('id')
        if not url and file_id:
            info = await bot.call_api('get_private_file_url', file_id=str(file_id))
            url = info.get('url')
            if not url:
                info = await bot.call_api('get_file', file_id=str(file_id))
                encoded = info.get('base64')
                if isinstance(encoded, str) and len(encoded) <= (MAX_BYTES + 2) // 3 * 4:
                    return decode_text(base64.b64decode(encoded, validate=True))
                url = info.get('url')
        if not isinstance(url, str) or not url:
            raise ValueError('file url unavailable')
        return decode_text(await self.download(url))

    async def accept(self, bot, *, text=None, file=None):
        async with self.lock:
            deadline = self.deadline(bot.self_id)
            if deadline is None:
                return None
            if self.clock() >= deadline:
                self.clear(bot.self_id)
                return None
            try:
                async with asyncio.timeout(30):
                    if file is not None:
                        text = await self.file_text(bot, file)
                    from .service import estimate
                    if not isinstance(text, str) or not text.strip('\ufeff \r\n\t') or '\0' in text:
                        raise ValueError('empty or binary text')
                    if len(text.encode('utf-8')) > MAX_BYTES or estimate(text) > self.context_tokens // 2:
                        raise ValueError('prompt too large')
                    with self.store.db:
                        self.store.db.execute("INSERT OR REPLACE INTO settings VALUES ('prompt',?)", (text,))
                        self.store.db.execute('DELETE FROM settings WHERE key=?', (self.key(bot.self_id),))
                return '统一system prompt已更新，下一轮对话生效。本次等待已结束。'
            except Exception as exc:
                logging.getLogger(__name__).warning('prompt upload failed: %s', type(exc).__name__)
                return '人设接收失败，原人设已保留。请在剩余等待时间内重发非空文本或512KB以内的txt/md文件（UTF-8、带BOM的UTF-16或GB18030），内容也需符合上下文长度限制。取消请用 /setprompt cancel。'
