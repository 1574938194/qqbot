"""运行于 ONNX 镜像内的边界测试，无需加载模型。"""
import json
from pathlib import Path
import tempfile
import threading
import sys
from unittest.mock import patch, Mock
import unittest
import numpy as np

from engine import Engine, TextToken, PauseToken, speech_tokens


class Session:
    def __init__(self, function):
        self.function = function

    def run(self, outputs, feed):
        return self.function(feed)

    def get_inputs(self):
        return [type('Input', (), {'name': name}) for name in ('y', 'embedding')]


class SemanticBoundaries(unittest.TestCase):
    def test_chinese_comma_cannot_drop_the_name(self):
        self.assertEqual(speech_tokens('你好，我是梦梦。'), [TextToken('你好我是梦梦'), PauseToken(.30)])

    def test_punctuation_becomes_internal_pause_tokens(self):
        self.assertEqual(speech_tokens('今天辛苦了呀，我会陪着你的。'),
                         [TextToken('今天辛苦了呀'), PauseToken(.12), TextToken('我会陪着你的'), PauseToken(.30)])
        self.assertEqual(speech_tokens('12:30吃午饭。'), [TextToken('12:30吃午饭'), PauseToken(.30)])

    def test_all_sentences_are_synthesized_and_joined(self):
        engine = object.__new__(Engine)
        engine.lock = threading.RLock()
        engine.synthesize_segment = Mock(side_effect=[np.ones(32000), np.ones(64000) * .5])
        audio = engine.synthesize('今天辛苦了。早点休息！', 'aoi')
        self.assertEqual(engine.synthesize_segment.call_args_list[0].args, ('今天辛苦了', 'aoi'))
        self.assertEqual(engine.synthesize_segment.call_args_list[1].args, ('早点休息', 'aoi'))
        self.assertEqual(audio.size, 32000 + 9600 + 64000 + 9600)

    def test_english_words_are_not_merged(self):
        self.assertEqual(speech_tokens('Hi,Tom。'), [TextToken('Hi Tom'), PauseToken(.30)])

    def test_failed_fragment_retries_whole_text_without_repeating_partial_audio(self):
        engine = object.__new__(Engine)
        engine.lock = threading.RLock()
        engine.synthesize_segment = Mock(side_effect=[np.ones(32000), ValueError('semantic output too short'), np.ones(96000) * .5])
        audio = engine.synthesize('今天辛苦了呀，我会陪着你的。', 'noto')
        self.assertEqual(engine.synthesize_segment.call_args_list[-1].args,
                         ('今天辛苦了呀 我会陪着你的', 'noto'))
        self.assertEqual(audio.size, 96000 + 9600)
        self.assertTrue(np.all(audio[:96000] == .5))

    def engine(self, stop=True):
        engine = object.__new__(Engine)
        engine.sessions = {
            'encoder': Session(lambda feed: (np.zeros((1, 1)), np.array([[7, 8, 9]]))),
            'first': Session(lambda feed: (np.array([[7, 8, 9, 42]]), np.zeros((1, 1)))),
            'step': Session(lambda feed: (np.concatenate([feed['y'], [[1024]]], axis=1),
                                         feed['embedding'], stop)),
        }
        return engine

    def generate(self, engine):
        return engine.semantic({'phones': None, 'bert': None, 'ssl_content': None}, None, None)

    def test_immediate_stop_never_copies_reference(self):
        tokens = self.generate(self.engine())
        self.assertEqual(tokens.tolist(), [[[42]]])

    def test_eos_inside_output_is_removed(self):
        engine = self.engine()
        engine.sessions['first'] = Session(lambda feed: (np.array([[7, 8, 9, 42, 1024, 13]]), np.zeros((1, 1))))
        self.assertEqual(self.generate(engine).tolist(), [[[42]]])

    def test_full_precision_stages_load_separately_without_residency(self):
        engine = self.engine()
        first, step = engine.sessions.pop('first'), engine.sessions.pop('step')
        engine.decoder_paths = {'first': Path('first.onnx'), 'step': Path('step.onnx')}
        with patch('engine.load_session', side_effect=[first, step]) as load:
            self.assertEqual(self.generate(engine).tolist(), [[[42]]])
            self.assertEqual([call.args[0].name for call in load.call_args_list], ['first.onnx', 'step.onnx'])
        self.assertEqual(set(engine.sessions), {'encoder'})

    def test_unbounded_generation_fails(self):
        with self.assertRaisesRegex(ValueError, 'limit'):
            self.generate(self.engine(stop=False))

    def test_manifest_cannot_read_outside_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'manifest.json').write_text(json.dumps({
                'voices': {key: {} for key in ('aoi', 'noto', 'hayami')},
                'sha256': {'../outside': '0' * 64}}))
            with self.assertRaisesRegex(ValueError, 'missing'):
                Engine(path, path)

    def speaking_engine(self):
        engine = object.__new__(Engine)
        engine.assets = Path('/unused')
        engine.lock = threading.RLock()
        engine.select = lambda speaker: None
        engine.references = {'aoi': {'ge': None, 'ge_advanced': None}}
        engine.get_phones = lambda *args, **kwargs: (np.ones((1, 12)), None)
        return engine

    def test_short_semantics_are_retried_before_vocoder(self):
        engine = self.speaking_engine()
        engine.semantic = Mock(side_effect=[np.ones((1, 1, 3)), np.ones((1, 1, 30))])
        manager = type('Manager', (), {'model_manager': type('Models', (), {'release': lambda self: None})()})
        with patch.dict(sys.modules, {'genie_tts.ModelManager': manager}), patch('engine.load_session') as load:
            load.return_value = Session(lambda feed: [np.ones(32000, dtype=np.float32) * .1])
            self.assertEqual(engine.synthesize('你好，我是梦梦。', 'aoi').size, 41600)
            self.assertEqual(engine.semantic.call_count, 2)
            load.assert_called_once()

    def test_repeated_short_output_fails_without_vocoder(self):
        engine = self.speaking_engine()
        engine.semantic = Mock(return_value=np.ones((1, 1, 3)))
        manager = type('Manager', (), {'model_manager': type('Models', (), {'release': lambda self: None})()})
        with patch.dict(sys.modules, {'genie_tts.ModelManager': manager}), patch('engine.load_session') as load:
            with self.assertRaisesRegex(ValueError, 'too short'):
                engine.synthesize('你好，我是梦梦。', 'aoi')
            self.assertEqual(engine.semantic.call_count, 3)
            load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
