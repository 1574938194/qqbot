import asyncio
import json
import os
import socket

import httpx
import pytest

from qqbot.config import ADMIN, Settings
from qqbot.store import Store
from qqbot.task_store import TaskStore
from qqbot.task_tools import ToolError, Tools, calculate


@pytest.fixture
async def tools(tmp_path):
    store = Store(str(tmp_path / 'db.sqlite3'))
    store.grant(123, True)
    tools = Tools(TaskStore(store), Settings(task_workspace=str(tmp_path / 'tasks')))
    yield tools
    await tools.close()
    store.close()


def test_calculator_limits():
    assert calculate('(3+5)/2') == '4.0'
    for bad in ['__import__("os")', '9**99999', '1/0', '[1,2]', '2 << 30', '1e999']:
        with pytest.raises(ToolError):
            calculate(bad)


async def test_file_scope_and_paginated_reads(tools):
    task_id = '0123456789ab'
    for path in ('../secret.txt', '../../../../.env', 'C:\\secret.txt', '.'):
        with pytest.raises(ToolError):
            tools.path(ADMIN, task_id, path)
    await tools.execute(ADMIN, task_id, 'write_file', {'path': 'folder/report.txt', 'content': 'abcdef'})
    result = json.loads(await tools.execute(ADMIN, task_id, 'read_file', {'path': 'folder/report.txt', 'offset': 2, 'length': 3}))
    assert result['text'] == 'cde' and result['total_chars'] == 6
    with pytest.raises(ToolError):
        await tools.execute(123, task_id, 'read_file', {'path': 'folder/report.txt'})
    with pytest.raises(ToolError):
        await tools.execute(ADMIN, task_id, 'read_file', {'path': 'x', 'offset': -1})


async def test_shell_admin_optin_and_real_python_powershell(tools, monkeypatch):
    task_id = '0123456789ab'
    with pytest.raises(ToolError):
        await tools.execute(ADMIN, task_id, 'shell', {'language': 'python', 'code': 'print(1)'})
    with pytest.raises(ToolError):
        tools.set_shell(123, True)
    tools.set_shell(ADMIN, True)
    with pytest.raises(ToolError):
        await tools.execute(123, task_id, 'shell', {'language': 'python', 'code': 'print(1)'})
    monkeypatch.setenv('LLM_API_KEY', 'do-not-inherit')
    result = json.loads(await tools.execute(ADMIN, task_id, 'shell', {'language': 'python', 'code':
        "import os,pathlib; pathlib.Path('result.txt').write_text('42'); print(6*7); print(os.getenv('LLM_API_KEY'))"}))
    assert result['exit_code'] == 0 and '42' in result['output'] and 'None' in result['output']
    if os.name == 'nt':
        result = json.loads(await tools.execute(ADMIN, task_id, 'shell', {'language': 'powershell', 'code': 'Write-Output (6*7)'}))
        assert result['exit_code'] == 0 and '42' in result['output']
    tools.set_shell(ADMIN, False)
    assert not tools.shell_enabled()


async def test_shell_timeout_terminates_owned_process(tools):
    from dataclasses import replace
    tools.config = replace(tools.config, task_tool_timeout=.5)
    tools.set_shell(ADMIN, True)
    with pytest.raises(TimeoutError):
        await tools.execute(ADMIN, '0123456789ab', 'shell', {'language': 'python', 'code':
            "import time,os,pathlib; pathlib.Path('pid.txt').write_text(str(os.getpid())); time.sleep(30); pathlib.Path('should-not-exist.txt').write_text('bad')"})
    root = tools.directory(ADMIN, '0123456789ab')
    assert not (root / 'should-not-exist.txt').exists()
    if os.name == 'nt':
        import ctypes
        pid = int((root / 'pid.txt').read_text())
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            code = ctypes.c_ulong()
            kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            kernel.CloseHandle(handle)
            assert code.value != 259


async def test_web_fetch_blocks_private_dns_and_pins_public_ip(tools, monkeypatch):
    async def addresses(host, port, **kwargs):
        ip = '127.0.0.1' if host in ('localhost', 'private.test') else '93.184.216.34'
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (ip, port))]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', addresses)
    for url in ('http://localhost/', 'http://private.test/', 'file:///etc/passwd', 'http://user:pass@example.com', 'https://public.test:32126'):
        with pytest.raises(ToolError):
            await tools.fetch(url)
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(302, headers={'location': 'http://private.test/'})
        return httpx.Response(200, headers={'content-type': 'text/html'}, text='<h1>公开资料</h1>')
    await tools.client.aclose()
    tools.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with pytest.raises(ToolError):
        await tools.fetch('https://public.test/')
    assert len(calls) == 1
    text, url = await tools.fetch('https://public.test/')
    assert '公开资料' in text
    assert calls[-1].url.host == '93.184.216.34'
    assert calls[-1].headers['host'] == 'public.test'
    assert calls[-1].extensions['sni_hostname'] == 'public.test'


async def test_brave_search_and_rss_fallback(tools):
    from dataclasses import replace
    await tools.client.aclose()
    def respond(request):
        assert request.headers['X-Subscription-Token'] == 'test-brave-key'
        return httpx.Response(200, json={'web': {'results': [{'title': 'Python', 'url': 'https://python.org', 'description': '官方文档'}]}})
    tools.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    tools.config = replace(tools.config, web_search_key='test-brave-key')
    assert 'python.org' in await tools.search('Python')
    tools.config = replace(tools.config, web_search_key='')
    async def fetch(url):
        assert 'format=rss' in url
        return '<rss><channel><item><title>Python</title><link>https://python.org</link><description>docs</description></item></channel></rss>', url
    tools.fetch = fetch
    assert 'python.org' in await tools.search('Python')
