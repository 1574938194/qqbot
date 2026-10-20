"""离线图修复验收；仅导出/修复环境需要ONNX包。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import numpy as np
import onnx
from onnx import helper, numpy_helper, TensorProto
import onnxruntime as ort

spec = importlib.util.spec_from_file_location('sampler_fix', Path(__file__).with_name('fix-sampler.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SamplerTests(unittest.TestCase):
    def test_fp16_storage_retains_original_half_weights_on_cpu(self):
        spec = importlib.util.spec_from_file_location('half_storage', Path(__file__).with_name('fp16-storage.py'))
        half = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(half)
        values = np.array([[.125, .25, .5], [1, 2, 4]], dtype=np.float16)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values.tofile(root / 't2s_shared_fp16.bin')
            values.astype(np.float32).tofile(root / 't2s_shared_fp32.bin')
            tensor = numpy_helper.from_array(values.astype(np.float32), name='weight')
            onnx.external_data_helper.set_external_data(tensor, location='t2s_shared_fp32.bin', offset=0, length=values.size * 4)
            tensor.ClearField('raw_data')
            tensor.data_location = TensorProto.EXTERNAL
            graph = helper.make_graph([helper.make_node('MatMul', ['x', 'weight'], ['y'])], 'half-storage-test',
                [helper.make_tensor_value_info('x', TensorProto.FLOAT, [1, 2])],
                [helper.make_tensor_value_info('y', TensorProto.FLOAT, [1, 3])], [tensor])
            original = root / 'original.onnx'
            converted = root / 'half.onnx'
            onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)], ir_version=9), original)
            self.assertEqual(half.convert(original, converted), 1)
            expected = np.array([[1, 2]], dtype=np.float32) @ values.astype(np.float32)
            session = ort.InferenceSession(str(converted), providers=['CPUExecutionProvider'])
            np.testing.assert_array_equal(session.run(None, {'x': np.array([[1, 2]], dtype=np.float32)})[0], expected)

    def test_exponential_sampling_matches_categorical_probabilities(self):
        probabilities = np.tile(np.array([[.7, .2, .1]], dtype=np.float32), (10000, 1))
        graph = helper.make_graph([
            helper.make_node('RandomNormalLike', ['probabilities'], ['noise'], dtype=1),
            helper.make_node('Div', ['probabilities', 'noise'], ['scores']),
            helper.make_node('ArgMax', ['scores'], ['choice'], axis=1, keepdims=0),
        ], 'sampling-test', [], [helper.make_tensor_value_info('choice', TensorProto.INT64, [10000])],
            [numpy_helper.from_array(probabilities, name='probabilities')])
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)], ir_version=9)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.onnx'
            onnx.save(model, path)
            self.assertEqual(module.fix(path), 1)
            self.assertEqual(module.fix(path), 0)
            loaded = onnx.load(path)
            self.assertNotIn('RandomNormalLike', [node.op_type for node in loaded.graph.node])
            session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
            choices = session.run(None, {})[0]
            np.testing.assert_allclose(np.bincount(choices, minlength=3) / len(choices), [.7, .2, .1], atol=.02)


if __name__ == '__main__':
    unittest.main()
