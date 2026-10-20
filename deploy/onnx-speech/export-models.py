"""离线导出 v2ProPlus；此工具需要 Torch，线上服务不需要。"""
from pathlib import Path
import argparse
import gc
import importlib
import importlib.util
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--checkout', type=Path, required=True, help='固定版本 Genie-TTS 完整源码')
parser.add_argument('--gpt', type=Path, required=True)
parser.add_argument('--sovits', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
source = (args.checkout / 'src/genie_tts').resolve()
output = args.output.resolve()
if output.exists() and any(output.iterdir()):
    raise SystemExit('Output must be empty')
output.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('genie_tts', source / '__init__.py',
                                             submodule_search_locations=[str(source)])
sys.modules['genie_tts'] = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(source / 'Converter'))
import numpy as np
import onnx
import onnxruntime as ort
from onnxruntime.quantization import quantize_dynamic, QuantType
sampler_spec = importlib.util.spec_from_file_location('sampler_fix', Path(__file__).with_name('fix-sampler.py'))
sampler_fix = importlib.util.module_from_spec(sampler_spec)
sampler_spec.loader.exec_module(sampler_fix)
half_spec = importlib.util.spec_from_file_location('half_storage', Path(__file__).with_name('fp16-storage.py'))
half_storage = importlib.util.module_from_spec(half_spec)
half_spec.loader.exec_module(half_storage)

converter = importlib.import_module('genie_tts.Converter.v2ProPlus.Converter')
# 保留失败产物和缓存供检查，不调用上游递归删除。
converter.remove_folder = lambda folder: None
converter.CACHE_DIR = str(output / 'export-cache')
converter.convert(str(args.gpt.resolve()), str(args.sovits.resolve()), str(output))
for stem in ('t2s_shared', 'vits', 'prompt_encoder'):
    values = np.fromfile(output / (stem + '_fp16.bin'), dtype=np.float16)
    values.astype(np.float32).tofile(output / (stem + '_fp32.bin'))
    del values
for stem in ('t2s_first_stage_decoder', 't2s_stage_decoder'):
    original = output / (stem + '_fp32.onnx')
    optimized = output / (stem + '.optimized.onnx')
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    options.optimized_model_filepath = str(optimized)
    session = ort.InferenceSession(str(original), sess_options=options,
                                   providers=['CPUExecutionProvider'])
    del session
    gc.collect()
    quantize_dynamic(str(optimized), str(output / (stem + '.q8.onnx')),
                     weight_type=QuantType.QUInt8, per_channel=True,
                     op_types_to_quantize=['MatMul', 'Gemm', 'Attention'])
    sampler_fix.fix(output / (stem + '.q8.onnx'))
    half_storage.convert(original, output / (stem + '.fp16-storage.onnx'))
print('Export complete; prepare each voice reference before deployment.')
