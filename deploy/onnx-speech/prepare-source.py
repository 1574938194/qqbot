"""取得固定 Genie 源码；导出用完整源码，镜像只复制推理前端。"""
from pathlib import Path
import argparse
import shutil
import subprocess

REVISION = 'd347fd0f8683e9a362b69f59fa0a4799ddb5e828'
parser = argparse.ArgumentParser()
parser.add_argument('--checkout', type=Path, required=True)
args = parser.parse_args()
if args.checkout.exists():
    raise SystemExit('checkout must be a new directory')
subprocess.run(['git', 'clone', 'https://github.com/High-Logic/Genie-TTS.git', str(args.checkout)], check=True)
subprocess.run(['git', '-C', str(args.checkout), 'checkout', '--detach', REVISION], check=True)
destination = Path(__file__).resolve().parent / 'source'
if destination.exists():
    raise SystemExit('source/ already exists; use a new release directory')
source = args.checkout / 'src/genie_tts'
for name in ('Core', 'G2P', 'Utils'):
    shutil.copytree(source / name, destination / 'genie_tts' / name,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for name in ('__init__.py', 'GetPhonesAndBert.py'):
    shutil.copy2(source / name, destination / 'genie_tts' / name)
shutil.copy2(args.checkout / 'LICENSE', destination / 'LICENSE')
print('Prepared Genie ' + REVISION)
