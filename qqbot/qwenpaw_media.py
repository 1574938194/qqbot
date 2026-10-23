"""QwenPaw 成果只允许读取当前 QQ 工作区，或下载经过公网检查的 URL。"""
import base64
import io
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from PIL import Image

from .llm import ModelError
from .prompt_upload import download_file

MAX_BYTES = 15 * 1024 * 1024


def local_path(uid, source, config):
    url = urlsplit(source)
    if url.scheme and (url.scheme != 'file' or url.netloc not in ('', 'localhost')):
        raise ValueError('file URI')
    path = unquote(url.path if url.scheme else source)
    root = Path(config.qwenpaw_files).resolve()
    allowed = root / 'qwenpaw/workspaces' / ('qq-' + str(uid))
    if not allowed.resolve().is_relative_to(root):
        raise ValueError('workspace link')
    raw = PurePosixPath(path)
    if raw.is_absolute():
        relative = raw.relative_to('/state')
        target = root.joinpath(*relative.parts).resolve()
    else:
        target = allowed.joinpath(*raw.parts).resolve()
    if not target.is_relative_to(allowed.resolve()) or not target.is_file():
        raise ValueError('file outside user workspace')
    return target


async def collect(uid, parts, config):
    result, seen = [], set()
    for part in parts:
        kind = part.get('type')
        if kind not in ('image', 'file', 'audio'):
            continue
        source = part.get('image_url') if kind == 'image' else part.get('file_url') if kind == 'file' else part.get('data')
        if not isinstance(source, str) or (kind, source) in seen:
            continue
        seen.add((kind, source))
        if len(seen) > 5:
            raise ModelError('任务附件超过5个，请分批发送。')
        try:
            if source.startswith(('https://', 'http://')):
                raw = await download_file(source, max_bytes=MAX_BYTES)
            elif source.startswith('data:'):
                header, encoded = source.split(',', 1)
                if ';base64' not in header or len(encoded) > (MAX_BYTES + 2) // 3 * 4:
                    raise ValueError('data URI')
                raw = base64.b64decode(encoded, validate=True)
            else:
                target = local_path(uid, source, config)
                with target.open('rb') as stream:
                    raw = stream.read(MAX_BYTES + 1)
            if not raw or len(raw) > MAX_BYTES:
                raise ValueError('file size')
            name = part.get('filename') or PurePosixPath(urlsplit(source).path).name or ('image.jpg' if kind == 'image' else 'attachment')
            name = str(name).replace('\\', '/').rsplit('/', 1)[-1].replace('\x00', '')[:150]
            if kind == 'image':
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > 25000000:
                        raise ValueError('image dimensions')
                    image.load()
                    image = image.convert('RGB')
                    image.thumbnail((2048, 2048))
                    out = io.BytesIO()
                    image.save(out, format='JPEG', quality=92)
                    raw = out.getvalue()
            result.append({'type': kind, 'name': name, 'data': raw})
        except Exception:
            raise ModelError('任务已产生结果，但附件无法读取或超出限制；请在 QwenPaw 网页查看原文件。') from None
    return result


async def send_files(bot, uid, files):
    from nonebot.adapters.onebot.v11 import Message, MessageSegment
    for file in files:
        if file['type'] in ('image', 'audio'):
            segment = MessageSegment.image(file['data']) if file['type'] == 'image' else MessageSegment.record(file['data'])
            await bot.send_private_msg(user_id=uid, message=Message(segment))
        else:
            await bot.call_api('upload_private_file', user_id=uid, name=file['name'],
                file='base64://' + base64.b64encode(file['data']).decode('ascii'))
