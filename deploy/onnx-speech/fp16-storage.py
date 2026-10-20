"""FP16权重存储、FP32 CPU计算；避免INT8量化误差，不声称CPU原生FP16加速。"""
import argparse
from pathlib import Path
import importlib.util
import onnx
from onnx import helper, TensorProto


def convert(source, destination):
    model = onnx.load(str(source), load_external_data=False)
    casts = []
    for tensor in model.graph.initializer:
        metadata = {entry.key: entry.value for entry in tensor.external_data}
        if metadata.get('location') != 't2s_shared_fp32.bin':
            continue
        if tensor.data_type != TensorProto.FLOAT:
            raise ValueError('Unexpected shared tensor type')
        name = tensor.name
        tensor.name = name + '_fp16_storage'
        tensor.data_type = TensorProto.FLOAT16
        for entry in tensor.external_data:
            if entry.key == 'location': entry.value = 't2s_shared_fp16.bin'
            elif entry.key in ('offset', 'length'):
                if int(entry.value) % 2: raise ValueError('Unaligned tensor data')
                entry.value = str(int(entry.value) // 2)
        casts.append(helper.make_node('Cast', [tensor.name], [name], to=TensorProto.FLOAT))
    if not casts:
        raise ValueError('No shared weights converted')
    original = list(model.graph.node)
    del model.graph.node[:]
    model.graph.node.extend(casts + original)
    onnx.save(model, str(destination))
    spec = importlib.util.spec_from_file_location('sampler_fix', Path(__file__).with_name('fix-sampler.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.fix(destination)
    return len(casts)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    for stem in ('t2s_first_stage_decoder', 't2s_stage_decoder'):
        print('FP16_STORAGE', stem, convert(args.directory / (stem + '_fp32.onnx'),
                                           args.directory / (stem + '.fp16-storage.onnx')), flush=True)
