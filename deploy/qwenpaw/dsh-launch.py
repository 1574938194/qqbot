"""QwenPaw 原生 ACP runner 入口；stdout 仅留给 DSH 协议。"""
import hashlib
import os
from pathlib import Path
import sys


def launch():
    workspace = Path.cwd().resolve()
    allowed = Path(os.environ.get('QWENPAW_WORKDIR', '/state/qwenpaw')).resolve()
    if not workspace.is_relative_to(allowed):
        raise ValueError('DSH 工作目录必须位于 QwenPaw 工作区内')
    if not os.environ.get('DSH_MODEL_API_KEY'):
        raise ValueError('未配置 DSH 模型凭据')
    tag = hashlib.sha256(str(workspace).encode()).hexdigest()[:24]
    home = Path(os.environ.get('DSH_HOME_ROOT', '/state/dsh')) / tag
    modules = home / 'profiles/acp/node_modules'
    modules.parent.mkdir(parents=True, exist_ok=True)
    if not modules.exists():
        modules.symlink_to('/opt/dsh-plugins/node_modules', target_is_directory=True)
    os.environ['DSH_HOME'] = str(home)
    binary = os.environ.get('DSH_BIN', '/opt/dsh-plugins/node_modules/.bin/dsh')
    patch = str(Path(__file__).with_name('dsh-acp.patch.yml'))
    os.execv(binary, [binary, '--profile', 'acp', '--patch', patch])


if __name__ == '__main__':
    try:
        launch()
    except (ValueError, OSError) as exc:
        # 只输出错误类型，避免把路径、命令参数或模型密钥写入日志。
        print('DSH ACP launcher unavailable: ' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
