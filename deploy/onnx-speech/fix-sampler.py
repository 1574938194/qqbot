"""离线修正 Genie 模板采样：probs / Exp(1)，不使用可为负的正态噪声。"""
from pathlib import Path
import argparse
import hashlib
import json
import onnx
from onnx import helper


def fix(path):
    model = onnx.load(str(path), load_external_data=False)
    nodes, changed = [], 0
    for node in model.graph.node:
        if node.op_type != 'RandomNormalLike':
            nodes.append(node)
            continue
        base = node.output[0] + '_exponential'
        nodes.extend([
            helper.make_node('RandomUniformLike', list(node.input), [base + '_uniform'],
                             dtype=1, low=0.000001, high=0.999999),
            helper.make_node('Log', [base + '_uniform'], [base + '_log']),
            helper.make_node('Neg', [base + '_log'], list(node.output)),
        ])
        changed += 1
    if changed:
        del model.graph.node[:]
        model.graph.node.extend(nodes)
        onnx.save(model, str(path))
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', type=Path, required=True)
    args = parser.parse_args()
    root = args.assets.resolve()
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    for voice in ('aoi', 'noto', 'hayami'):
        for stem in ('t2s_first_stage_decoder', 't2s_stage_decoder'):
            path = root / voice / (stem + '.q8.onnx')
            if not path.exists():
                continue
            print('SAMPLER_FIX', voice, stem, fix(path), flush=True)
            if manifest:
                with path.open('rb') as stream:
                    manifest['sha256'][path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    if manifest:
        manifest['sampler'] = 'exponential-v1'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
