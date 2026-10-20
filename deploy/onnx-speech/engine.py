"""固定 Genie 提交的无 PyTorch 推理适配；模型与参考数据独立挂载。"""
from __future__ import annotations
from dataclasses import dataclass

import gc
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import sys
import threading
import time
import types

for thread_variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(thread_variable, '1')
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer


def session_options():
    options = ort.SessionOptions()
    options.intra_op_num_threads = int(os.getenv('ORT_THREADS', '1'))
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return options


def load_session(path):
    return ort.InferenceSession(str(path), sess_options=session_options(),
                                providers=['CPUExecutionProvider'])


def trim_memory():
    gc.collect()
    if os.name == 'posix':
        import ctypes
        try:
            ctypes.CDLL(None).malloc_trim(0)
        except (OSError, AttributeError):
            pass


@dataclass(frozen=True)
class TextToken:
    text: str


@dataclass(frozen=True)
class PauseToken:
    seconds: float


def speech_tokens(text):
    """标点成为内部停顿token，不把未训练的占位字符串交给GPT。"""
    result, pending = [], ''
    cursor = 0
    pattern = r'[，,、；;：:。！？!?\n…]+|(?<!\d)\.(?!\d)'
    for match in re.finditer(pattern, text):
        mark = match.group()
        if mark in (':', '：') and match.start() and match.end() < len(text) and text[match.start()-1].isdigit() and text[match.end()].isdigit():
            continue  # 时间中的冒号交给数字读法归一化，不作为句间停顿。
        pending += text[cursor:match.start()]
        cursor = match.end()
        strong = any(c in mark for c in '。！？!?\n….')
        duration = .30 if strong else .20 if any(c in mark for c in '；;：:') else .12
        units = len(re.findall(r'[\u3400-\u9fff0-9]|[A-Za-z]+', pending))
        if units >= (4 if strong else 6):
            result.extend([TextToken(pending.strip()), PauseToken(duration)])
            pending = ''
        elif pending and pending[-1].isascii() and pending[-1].isalnum():
            pending += ' '  # 合并短英文片段时保留单词边界。
    pending += text[cursor:]
    pending = pending.strip()
    if re.search(r'\w', pending):
        if result and len(re.findall(r'[\u3400-\u9fff0-9]|[A-Za-z]+', pending)) < 4:
            result.pop()  # 将过短尾句并入上一段，避免只生成碎音。
            previous = result.pop()
            pending = previous.text + (' ' if previous.text[-1:].isascii() else '') + pending
        result.extend([TextToken(pending), PauseToken(.30)])
    return result


class TextModels:
    def __init__(self, root):
        self.root = root
        self.roberta_model = self.roberta_tokenizer = None

    def load_roberta_model(self):
        if self.roberta_model is None:
            self.roberta_model = load_session(self.root / 'roberta/bert.int8.onnx')
            self.roberta_tokenizer = Tokenizer.from_file(str(self.root / 'roberta/tokenizer.json'))
        return True

    def release(self):
        self.roberta_model = None
        trim_memory()


def load_frontend(source, assets):
    # SDK顶层会导入播放器、自动下载器和Torch转换器。此进程只加载已审查的
    # 文本前端与T2S循环，注入资源路径及共享BERT，参考编码在离线准备时完成。
    spec = importlib.util.spec_from_file_location('genie_tts', source / '__init__.py',
                                                 submodule_search_locations=[str(source)])
    package = importlib.util.module_from_spec(spec)
    sys.modules['genie_tts'] = package
    resources = types.ModuleType('genie_tts.Core.Resources')
    resources.Chinese_G2P_DIR = str(assets / 'resources/G2P/ChineseG2P')
    resources.English_G2P_DIR = str(assets / 'resources/G2P/EnglishG2P')
    sys.modules[resources.__name__] = resources
    manager = types.ModuleType('genie_tts.ModelManager')
    manager.model_manager = TextModels(assets)
    sys.modules[manager.__name__] = manager
    reference = types.ModuleType('genie_tts.Audio.ReferenceAudio')
    reference.ReferenceAudio = object  # 仅作上游T2S函数的类型注解，不创建在线编码器。
    sys.modules[reference.__name__] = reference
    from genie_tts.GetPhonesAndBert import get_phones_and_bert
    from genie_tts.Core.Inference import GENIE
    return get_phones_and_bert, GENIE()


class Engine:
    def __init__(self, assets, source, verify=True):
        self.assets = Path(assets).resolve()
        self.manifest = json.loads((self.assets / 'manifest.json').read_text(encoding='utf-8'))
        if set(self.manifest['voices']) != {'aoi', 'noto', 'hayami'}:
            raise ValueError('voice catalog incomplete')
        if verify:
            for name, expected in self.manifest['sha256'].items():
                path = (self.assets / name).resolve()
                if not path.is_relative_to(self.assets) or not path.is_file():
                    raise ValueError('voice asset missing')
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                        raise ValueError('voice asset checksum mismatch')
            if self.manifest.get('sampler') != 'exponential-v1':
                raise ValueError('semantic sampler upgrade required')
        self.get_phones, self.generator = load_frontend(Path(source).resolve(), self.assets)
        self.lock = threading.RLock()
        self.active = None
        self.sessions = {}
        self.references = {}
        self.switches = 0

    def reference(self, speaker):
        if speaker not in self.references:
            root = self.assets / speaker
            info = self.manifest['voices'][speaker]
            phones, bert = self.get_phones(info['prompt_text'], language='Japanese')
            with np.load(root / 'reference.npz', allow_pickle=False) as data:
                features = {name: data[name].copy() for name in data.files}
            if 'ge' not in features or 'ge_advanced' not in features:
                encoder = load_session(root / 'prompt_encoder_fp32.onnx')
                ge, advanced = encoder.run(None, {'ref_audio': features['audio_32k'],
                                                   'sv_emb': features['sv_emb']})
                features.update(ge=ge, ge_advanced=advanced)
                del encoder
                trim_memory()
            features.update(phones=phones, bert=bert)
            self.references[speaker] = features
        return self.references[speaker]

    def select(self, speaker):
        if speaker not in self.manifest['voices']:
            raise ValueError('unknown speaker')
        if self.active == speaker:
            return
        self.sessions.clear()
        self.active = None
        trim_memory()
        self.reference(speaker)
        root = self.assets / speaker
        variant = self.manifest['voices'][speaker].get('decoder_format', 'q8')
        if variant not in ('q8', 'fp32', 'fp16-storage'):
            raise ValueError('invalid decoder format')
        suffix = {'q8': '.q8.onnx', 'fp32': '_fp32.onnx', 'fp16-storage': '.fp16-storage.onnx'}[variant]
        files = {'encoder': 't2s_encoder_fp32.onnx', 'first': 't2s_first_stage_decoder' + suffix,
                 'step': 't2s_stage_decoder' + suffix}
        self.decoder_paths = {key: root / files[key] for key in ('first', 'step')}
        if variant != 'q8':
            files = {'encoder': files['encoder']}  # 完整精度两阶段分别加载，避免复制两套大权重常驻。
        loaded = {key: load_session(root / name) for key, name in files.items()}
        self.sessions = loaded
        self.active = speaker
        self.switches += 1
        trim_memory()

    def synthesize(self, text, speaker):
        if not text.strip() or len(text) > int(os.getenv('MAX_TEXT_CHARS', '200')):
            raise ValueError('invalid text length')
        plan = speech_tokens(text)
        if not plan:
            raise ValueError('no pronounceable text')
        with self.lock:
            audio = []
            try:
                for token in plan:
                    if isinstance(token, PauseToken):
                        audio.append(np.zeros(round(32000 * token.seconds), dtype=np.float32))
                    else:
                        audio.append(self.synthesize_segment(token.text, speaker))
            except ValueError as exc:
                parts = [token.text for token in plan if isinstance(token, TextToken)]
                if str(exc) not in ('semantic output too short', 'invalid audio output') or len(parts) < 2:
                    raise
                # 某些克隆模型不能稳定朗读独立短片段。丢弃本次所有局部音频，
                # 合并完整正文用同一音色重试，避免重复前句或漏掉后句。
                merged = ' '.join(parts)
                audio = [self.synthesize_segment(merged, speaker), np.zeros(9600, dtype=np.float32)]
            return np.concatenate(audio)

    def synthesize_segment(self, text, speaker):
        if not text.strip() or len(text) > int(os.getenv('MAX_TEXT_CHARS', '200')):
            raise ValueError('invalid text length')
        # 除HTTP队列外，工作线程也持锁；客户端超时不会让旧推理与换模型重叠。
        with self.lock:
            started = time.monotonic()
            self.select(speaker)
            loaded = time.monotonic()
            reference = self.references[speaker]
            try:
                text_seq, text_bert = self.get_phones('。' + text + '。', language='Chinese')
            finally:
                # 2GB主机避免BERT与声学工作区同时驻留，权重仍可由系统文件缓存复用。
                sys.modules['genie_tts.ModelManager'].model_manager.release()
            if text_seq.shape[1] == 0:
                raise ValueError('no pronounceable text')
            prepared = time.monotonic()
            # 自回归采样偶尔提前结束。只对过短语义重试，最多三次；不返回参考音频。
            units = len(re.findall(r'[\u3400-\u9fff0-9]|[A-Za-z]+', text))
            minimum_tokens = max(6, min(50, units * 2))  # 仅拦截退化输出；时长不能代替正文完整性校验。
            for attempt in range(3):
                tokens = self.semantic(reference, text_seq, text_bert)
                if tokens.shape[-1] >= minimum_tokens:
                    break
            else:
                raise ValueError('semantic output too short')
            generated = time.monotonic()
            vocoder = load_session(self.assets / speaker / 'vits_fp32.onnx')
            try:
                audio = vocoder.run(None, {'text_seq': text_seq, 'pred_semantic': tokens,
                        'ge': reference['ge'], 'ge_advanced': reference['ge_advanced']})[0]
            finally:
                del vocoder
                trim_memory()
            audio = np.asarray(audio, dtype=np.float32).reshape(-1)
            if audio.size < 6400 or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 0.005:
                raise ValueError('invalid audio output')
            self.last_metrics = {'load': loaded - started, 'text': prepared - loaded,
                                 'semantic': generated - prepared, 'vocoder': time.monotonic() - generated}
            return np.clip(audio, -1, 1)

    def semantic(self, reference, text_seq, text_bert):
        # 上游 idx=0 时 y[:,-idx:] 会切出完整参考序列；显式按参考长度切割。
        x, prompts = self.sessions['encoder'].run(None, {
            'ref_seq': reference['phones'], 'ref_bert': reference['bert'],
            'text_seq': text_seq, 'text_bert': text_bert, 'ssl_content': reference['ssl_content']})
        first = self.sessions.get('first') or load_session(self.decoder_paths['first'])
        try:
            y, embedding, *cache = first.run(None, {'x': x, 'prompts': prompts})
        finally:
            del first
            if 'first' not in self.sessions: trim_memory()
        step = self.sessions.get('step') or load_session(self.decoder_paths['step'])
        try:
            names = [item.name for item in step.get_inputs()]
            for _ in range(500):
                y, embedding, stop, *cache = step.run(None, dict(zip(names, [y, embedding, *cache])))
                if stop:
                    break
            else:
                raise ValueError('semantic generation limit exceeded')
        finally:
            del step
            if 'step' not in self.sessions: trim_memory()
        tokens = y[:, prompts.shape[-1]:].copy()
        # 最后一个采样位置为停止标记；不把EOS传入声学模型。
        tokens = tokens[:, :-1]
        eos = np.where(tokens >= 1024)
        if len(eos[0]):
            tokens = tokens[:, :eos[-1][0]]
        return np.expand_dims(tokens, axis=0)
