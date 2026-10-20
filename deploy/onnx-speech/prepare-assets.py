"""校验部署所需模型/参考/资源，生成哈希清单；不打包导出中间文件。"""
from pathlib import Path
import argparse
import hashlib
import json
import tarfile
import onnx

parser = argparse.ArgumentParser()
parser.add_argument('--assets', type=Path, required=True)
parser.add_argument('--profiles', type=Path, required=True, help='三个声音的名称、准确参考转写 JSON')
parser.add_argument('--archive', type=Path)
args = parser.parse_args()
root = args.assets.resolve()
profiles = json.loads(args.profiles.read_text(encoding='utf-8'))
if set(profiles) != {'aoi', 'noto', 'hayami'}:
    raise SystemExit('Exactly aoi/noto/hayami profiles are required')
required = ['t2s_encoder_fp32.onnx', 't2s_encoder_fp32.bin',
            'vits_fp32.onnx', 'vits_fp32.bin', 'reference.npz', 'reference.wav']
files = [root / key / name for key in profiles for name in required]
formats = {}
for key, profile in profiles.items():
    variant = profile.get('decoder_format', 'q8')
    if variant not in ('q8', 'fp16-storage'):
        raise SystemExit('Unsupported decoder format')
    formats[key] = variant
    files.extend(root / key / (stem + '.' + variant + '.onnx') for stem in ('t2s_first_stage_decoder', 't2s_stage_decoder'))
    if variant == 'fp16-storage':
        files.append(root / key / 't2s_shared_fp16.bin')
files += [root / 'roberta/bert.int8.onnx', root / 'roberta/tokenizer.json']
files += [p for p in (root / 'resources').rglob('*') if p.is_file()]
for key in profiles:
    for stem in ('t2s_first_stage_decoder', 't2s_stage_decoder'):
        model = onnx.load(str(root / key / (stem + '.' + formats[key] + '.onnx')), load_external_data=False)
        operators = [node.op_type for node in model.graph.node]
        if 'RandomNormalLike' in operators or not all(name in operators for name in ('RandomUniformLike', 'Log', 'Neg')):
            raise SystemExit('Semantic sampler upgrade required: run fix-sampler.py first')
        del model
if not (root / 'resources/G2P/ChineseG2P/opencpop-strict.txt').is_file():
    raise SystemExit('G2P resources missing')
hashes = {}
for path in files:
    if not path.resolve().is_relative_to(root):
        raise SystemExit('Asset path escapes root')
    with path.open('rb') as stream:
        hashes[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
voices = {}
for key, profile in profiles.items():
    if not profile.get('prompt_text', '').strip():
        raise SystemExit('Reference transcript required')
    voices[key] = {'name': profile['name'], 'prompt_text': profile['prompt_text'], 'language': 'Japanese', 'decoder_format': formats[key]}
manifest = {'genie_revision': 'd347fd0f8683e9a362b69f59fa0a4799ddb5e828', 'sampler': 'exponential-v1', 'voices': voices, 'sha256': hashes}
(root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
if args.archive:
    with tarfile.open(args.archive, 'w:gz', compresslevel=1) as archive:
        for name in ['manifest.json', *hashes]:
            archive.add(root / name, arcname=name, recursive=False)
print('Verified runtime assets:', len(hashes))
