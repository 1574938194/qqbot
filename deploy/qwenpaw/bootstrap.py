"""初始化独立 QwenPaw；不读取或打印用户人设和聊天。"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil


async def configure():
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.config.config import ACPConfig, ModelSlotConfig, load_agent_config, save_agent_config
    from qwenpaw.providers.provider import ProviderInfo, ModelInfo
    from qwenpaw.providers.provider_manager import ProviderManager

    model = os.environ.get('LLM_MODEL', 'deepseek-v4.1-flash')
    manager = ProviderManager()
    provider = ProviderInfo(id='buddyproxy', name='buddyproxy',
        base_url=os.environ['DSH_MODEL_BASE_URL'], api_key=os.environ['DSH_MODEL_API_KEY'],
        discovery_strategy='unsupported', models=[ModelInfo(id=model, name=model,
            supports_image=True, supports_tool_calling=True, max_input_length=260000,
            max_output_length=6000, generate_kwargs={'max_tokens': 6000})])
    await manager.add_custom_provider(provider)
    cfg = load_config()
    cfg.user_timezone = 'Asia/Shanghai'
    cfg.show_tool_details = False
    cfg.channels.console.show_thinking = False
    cfg.channels.console.show_tool_calls = False
    cfg.channels.console.show_tool_results = False
    cfg.channels.qqbot = {'enabled': True, 'show_thinking': False, 'show_tool_calls': False, 'show_tool_results': False}
    cfg.plugins['qqbot-gateway'] = {'enabled': True}
    plugin_root = Path(os.environ.get('QWENPAW_WORKING_DIR', '/state/qwenpaw')) / 'plugins/qqbot-gateway'
    source = Path(__file__).with_name('qqbot-plugin')
    if source.is_dir():
        shutil.copytree(source, plugin_root, dirs_exist_ok=True)
    cfg.acp = ACPConfig.model_validate(json.loads(Path(__file__).with_name('acp.example.json').read_text()))
    cfg.acp.node_path = '/usr/local/bin/node'
    save_config(cfg)
    agent = load_agent_config('default')
    agent.acp = cfg.acp
    agent.active_model = ModelSlotConfig(provider_id='buddyproxy', model=model)
    agent.running.llm_retry_enabled = False
    agent.running.max_iters = 20
    agent.running.max_input_length = 260000
    agent.running.auto_title_config.enabled = False
    context = agent.running.light_context_config
    context.strategy = 'native'
    context.context_compact_config.compact_threshold_ratio = 240000 / 260000
    memory = agent.running.reme_light_memory_config
    memory.auto_memory_search_config.enabled = True
    for name in ('auto_memory_inbox_push_enabled', 'auto_dream_inbox_push_enabled',
                 'daily_paper_inbox_push_enabled', 'auto_fin_inbox_push_enabled',
                 'dream_cron_enabled', 'daily_paper_cron_enabled', 'auto_fin_cron_enabled'):
        setattr(memory, name, False)
    # 明确禁用其他外部 runner，仅保留用户指定的 DSH。
    save_agent_config('default', agent)
    print('QWENPAW_BUDDYPROXY_DSH_CONFIGURED', flush=True)


if __name__ == '__main__':
    try:
        root = Path(os.environ.get('QWENPAW_WORKING_DIR', '/state/qwenpaw'))
        if not (root / 'config.json').is_file():
            subprocess.run(['qwenpaw', 'init', '--defaults', '--accept-security'], check=True)
        asyncio.run(configure())
    except Exception as exc:
        print('QwenPaw bootstrap failed: ' + type(exc).__name__, file=sys.stderr)
        if hasattr(exc, 'errors'):
            print('Invalid fields: ' + str([e['loc'] for e in exc.errors()]), file=sys.stderr)
        raise SystemExit(1) from None
