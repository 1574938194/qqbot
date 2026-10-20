"""离线生成固定参考的 SSL、说话人和声学条件，保留原参考音频。"""
from pathlib import Path
import argparse
import os
import shutil
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--gsv-source', type=Path, required=True)
parser.add_argument('--reference', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True, help='export-models.py 的声音输出目录')
args = parser.parse_args()
root, reference, output = args.gsv_source.resolve(), args.reference.resolve(), args.output.resolve()
sys.path[:0] = [str(root), str(root / 'GPT_SoVITS')]
os.chdir(root)
import numpy as np
import soundfile as sf
import soxr
import torch
import onnxruntime as ort
from feature_extractor.cnhubert import CNHubert
from sv import SV

torch.set_num_threads(2)
audio, rate = sf.read(reference, dtype='float32')
if audio.ndim > 1:
    audio = audio.mean(axis=1)
if rate != 32000:
    audio = soxr.resample(audio, rate, 32000, quality='hq')
if not 3 <= len(audio) / 32000 <= 10:
    raise SystemExit('Reference should be 3–10 seconds')
audio = np.concatenate([audio, np.zeros(9600, dtype=np.float32)])[None, :]
wave16 = soxr.resample(audio[0], 32000, 16000, quality='hq').astype(np.float32)[None, :]
hubert = CNHubert(str(root / 'GPT_SoVITS/pretrained_models/chinese-hubert-base')).eval()
speaker = SV(torch.device('cpu'), False)
with torch.inference_mode():
    ssl = hubert.model(torch.from_numpy(wave16))['last_hidden_state'].transpose(1, 2).numpy()
    sv = speaker.compute_embedding3(torch.from_numpy(wave16)).numpy()
options = ort.SessionOptions()
options.intra_op_num_threads = 1
encoder = ort.InferenceSession(str(output / 'prompt_encoder_fp32.onnx'), sess_options=options,
                               providers=['CPUExecutionProvider'])
ge, advanced = encoder.run(None, {'ref_audio': audio, 'sv_emb': sv})
np.savez_compressed(output / 'reference.npz', audio_32k=audio, ssl_content=ssl,
                    sv_emb=sv, ge=ge, ge_advanced=advanced)
shutil.copy2(reference, output / 'reference.wav')
print('Reference features ready; original audio retained.')
