"""为已上传的权重与参考音频生成启动校验清单，不更换任何模型。"""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('assets', type=Path)
args = parser.parse_args()
root = args.assets.resolve()
hashes = {}
names = ['custom/gpt.ckpt', 'custom/sovits.pth', 'reference/aoi.wav']
if (root / 'custom/bert.int8.onnx').exists():
    names.append('custom/bert.int8.onnx')
if (root / 'g2pw/g2pW.onnx').exists():
    names.append('g2pw/g2pW.onnx')
for name in names:
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise SystemExit('Missing voice asset: ' + name)
    with path.open('rb') as stream:
        hashes[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
manifest = root / 'manifest.json'
manifest.write_text(json.dumps({'sha256': hashes}, indent=2) + '\n', encoding='utf-8')
manifest.chmod(0o600)
print('Voice asset checksums prepared.')
