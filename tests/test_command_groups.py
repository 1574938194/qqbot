import pytest

from qqbot.commands import help_text
from qqbot.config import ADMIN
from test_web_chat import setup, client_for
from test_service import service


async def test_grouped_commands_keep_permissions_and_history(service):
    service.store.grant(123, True)
    service.store.append(ADMIN, '保留我的聊天', '好的')
    for command in ('/chat status', '/chat emotion', '/chat memory status', '/chat memory sync', '/chat memory clear'):
        assert await service.handle(ADMIN, command)
    assert len(service.store.history(ADMIN)) == 1
    assert not service.llm.calls
    assert '只有超级管理员' in await service.handle(123, '/prompt set 不应更新')
    assert '没有这个帮助分类' in await service.handle(123, '/help profile')
    assert '未知命令' in await service.handle(ADMIN, '/voicebox')
    assert '对话' in await service.handle(ADMIN, '/chat missing')
    await service.handle(ADMIN, '/chat reset 多余参数')
    assert len(service.store.history(ADMIN)) == 1
    await service.handle(ADMIN, '/chat reset')
    assert not service.store.history(ADMIN)


async def test_grouped_prompt_profile_and_voice_through_web(setup):
    app, web, service, upload, media, bots = setup
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        async def send(text):
            result = await client.post('/debug/chat', json={'text': text})
            assert result.status_code == 200
            return result.json()
        assert '5分钟' in (await send('/prompt upload'))['reply']
        # 命令不会被正在等待的人设接收器误收。
        await send('/profile name 测试名字')
        assert service.store.identity()['role_name'] == '测试名字'
        assert (await send('/help prompt'))['prompt_pending']
        exact = '  测试人设\r\n原始换行  '
        await send(exact)
        assert service.store.prompt() == exact
        await send('/prompt upload')
        assert not (await send('/prompt cancel'))['prompt_pending']
        await send('/voice speaker noto')
        media.command.assert_awaited_with(ADMIN, '/voice speaker noto')
        await send('/voice say 测试朗读')
        media.command.assert_awaited_with(ADMIN, '/voice say 测试朗读')
        assert '网页暂不支持' in (await send('/profile avatar'))['reply']
    assert not service.store.history(ADMIN)
    service.llm.complete.assert_not_called()


def test_help_only_advertises_grouped_commands():
    help = help_text(admin=True, tasks=True, agent=True)
    assert '/voice' in help and '/profile' in help and '/task' in help
    for old in ('/setprompt', '/setname', '/speaker', '/say', '/tools', '/remind', '/tool '):
        assert old not in help
    assert '/prompt' not in help_text()
    assert '/task' not in help_text()

@pytest.mark.parametrize('command', [
    '/status', '/compress', '/reset', '/emotion', '/memory clear',
    '/setprompt', '/setprompt cancel', '/setname bad', '/setnickname bad',
    '/name bad', '/nickname bad', '/avatar', '/avatar cancel', '/speaker noto',
    '/say 你好', '/tool 写文件', '/tool /task run 写文件', '/tools shell on',
    '/remind in 5m 喝水', '/stop', '/帮助', '/状态', '/压缩', '/清空', '/情绪',
    '/任务 run 写文件', '/提醒 in 5m 喝水', '/工具',
])
async def test_removed_commands_have_no_effect_in_web_or_shared_service(setup, command):
    app, web, service, upload, media, bots = setup
    service.store.append(ADMIN, '保留的对话', '保留的回复')
    original = (service.store.prompt(), service.store.identity(), service.store.history(ADMIN))
    async with client_for(app) as client:
        client.headers['X-Debug-Token'] = web.token
        result = (await client.post('/debug/chat', json={'text': command})).json()
        assert '未知命令' in result['reply']
        assert not result['prompt_pending']
    assert (service.store.prompt(), service.store.identity(), service.store.history(ADMIN)) == original
    assert upload.deadline('99990008') is None
    assert not service.store.db.execute("SELECT 1 FROM settings WHERE key LIKE 'avatar_pending:%'").fetchone()
    media.command.assert_not_called()
    service.llm.complete.assert_not_called()
