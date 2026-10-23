"""固定 QwenPaw 版本的最小兼容修补：允许 240K/260K 压缩阈值。"""
from pathlib import Path
import importlib.util

spec = importlib.util.find_spec('qwenpaw')
path = Path(spec.origin).parent / 'config/config.py'
source = path.read_text(encoding='utf-8')
old = 'compact_threshold_ratio: float = Field(\n        default=0.8,\n        ge=0.1,\n        le=0.9,'
new = old.replace('le=0.9,', 'le=0.99,')
if old in source:
    path.write_text(source.replace(old, new, 1), encoding='utf-8')
elif new not in source:
    raise RuntimeError('QwenPaw context schema changed; review compatibility patch')
