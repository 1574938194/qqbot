from pathlib import Path

import pytest

from qqbot.config import Settings


def test_key_precedence_and_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    for name in ('LLM_API_KEY', 'OPENAI_API_KEY', 'CODEBUDDY_PROXY_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    directory = tmp_path / '.codebuddy'
    directory.mkdir()
    (directory / 'proxy.env').write_text('CODEBUDDY_PROXY_API_KEY=file-key', encoding='utf-8')
    assert Settings.load().api_key == 'file-key'
    (tmp_path / '.env').write_text('LLM_API_KEY=local-key', encoding='utf-8')
    assert Settings.load().api_key == 'local-key'
    monkeypatch.setenv('OPENAI_API_KEY', 'environment-key')
    assert Settings.load().api_key == 'environment-key'
    monkeypatch.setenv('LLM_API_KEY', 'preferred-key')
    assert Settings.load().api_key == 'preferred-key'
    monkeypatch.setenv('KEEP_ROUNDS', '20')
    assert Settings.load().compress_rounds == 0
    monkeypatch.setenv('COMPRESS_ROUNDS', '20')
    with pytest.raises(ValueError, match='KEEP_ROUNDS'):
        Settings.load()
