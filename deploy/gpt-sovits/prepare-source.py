"""下载固定官方源码提交，保留原整合包与训练资产。"""
from io import BytesIO
from pathlib import Path
import urllib.request
import zipfile

root = Path(__file__).resolve().parent
revision = (root / 'UPSTREAM_REVISION').read_text().strip()
if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
    raise SystemExit('Invalid upstream revision')
destination = root / 'source'
if destination.exists() and any(destination.iterdir()):
    raise SystemExit('source/ already exists; use a new release directory')
with urllib.request.urlopen('https://codeload.github.com/RVC-Boss/GPT-SoVITS/zip/' + revision, timeout=90) as response:
    raw = response.read(100 * 1024 * 1024 + 1)
if len(raw) > 100 * 1024 * 1024:
    raise SystemExit('Source archive too large')
with zipfile.ZipFile(BytesIO(raw)) as archive:
    prefix = archive.namelist()[0].split('/')[0] + '/'
    if sum(item.file_size for item in archive.infolist()) > 200 * 1024 * 1024:
        raise SystemExit('Expanded source too large')
    destination.mkdir(exist_ok=True)
    for item in archive.infolist():
        relative = item.filename.removeprefix(prefix)
        if not relative or item.is_dir():
            continue
        target = (destination / relative).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise SystemExit('Unsafe archive path')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(item))
(destination / 'UPSTREAM_REVISION').write_text(revision + '\n')
print('Official source ready: ' + revision)
