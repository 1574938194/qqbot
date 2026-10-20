"""用 ONNX 特征图替换上游 BERT；保留原来的倒数第三层输出接口。"""
from pathlib import Path

import onnxruntime as ort
import torch


def low_memory_sessions():
    original = ort.InferenceSession

    class LowMemorySession(original):
        def __init__(self, path_or_bytes, sess_options=None, **kwargs):
            options = sess_options or ort.SessionOptions()
            options.enable_cpu_mem_arena = False
            options.enable_mem_pattern = False
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.add_session_config_entry('session.disable_prepacking', '1')
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
            super().__init__(path_or_bytes, sess_options=options, **kwargs)

    ort.InferenceSession = LowMemorySession


class OnnxBert:
    def __init__(self, path):
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(path), sess_options=options,
                                           providers=['CPUExecutionProvider'])
        self.names = {item.name for item in self.session.get_inputs()}
        self.device = torch.device('cpu')

    def eval(self):
        return self

    def to(self, device):
        if torch.device(device).type != 'cpu':
            raise ValueError('ONNX BERT requires CPU')
        return self

    def float(self):
        return self

    def half(self):
        raise ValueError('ONNX BERT uses its exported precision')

    def __call__(self, output_hidden_states=True, **inputs):
        feed = {name: inputs[name].detach().cpu().numpy() for name in self.names}
        feature = torch.from_numpy(self.session.run(['features'], feed)[0])
        # 上游仅读取 hidden_states[-3]，该图只导出这一层。
        return {'hidden_states': (feature, feature, feature)}


def install(path):
    """在加载 API 前安装，只替换项目指定 BERT 的加载路径。"""
    from transformers import AutoModelForMaskedLM
    expected = (Path.cwd() / 'GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large').resolve()
    original = AutoModelForMaskedLM.from_pretrained

    def load(base_path, *args, **kwargs):
        if Path(base_path).resolve() == expected:
            return OnnxBert(path)
        return original(base_path, *args, **kwargs)

    AutoModelForMaskedLM.from_pretrained = load
