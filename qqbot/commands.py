"""QQ 与网页共用的命令分组；旧入口只作兼容，不出现在帮助里。"""

CHAT_HELP = '/chat status：模型、上下文、长期记忆与情感状态\n/chat compress：压缩旧对话\n/chat reset：清空自己的聊天和记忆\n/chat memory status|sync|clear：查看、同步或单独清除长期记忆'
VOICE_HELP = '/voice on|off|both：语音、文字或两者\n/voice speaker [list|aoi|noto|hayami|edge|reset]：查看或切换音色\n/voice say 内容：单次朗读'
PROFILE_HELP = '/profile：查看名字和昵称\n/profile name 名字：设置角色名\n/profile nickname 昵称：设置昵称并同步 QQ\n/profile avatar [cancel]：等待下一张私聊图片设为头像，5分钟有效'
PROMPT_HELP = '/prompt upload：5分钟内下一条文本或 txt/md 原文设为人设\n/prompt cancel：取消等待\n/prompt show：查看原文\n/prompt set 内容：直接设置，支持多行\n/prompt reset：恢复默认人设'
TASK_HELP = '''/task run 内容：创建独立后台任务
/task in 10m 内容：延后执行（也支持 at/every/daily）
/task remind in 10m 内容：定时提醒（也支持 at/every/daily）
/task list [all]：待处理任务 / 最近7天历史
/task show|steps|runs ID：结果、步骤或执行记录
/task files ID；/task file ID 路径：查看成果
/task cancel|pause|resume|retry ID：管理任务
/task reply ID 内容：补充信息
/task stop：停止当前 QwenPaw 执行
/task tools：查看执行能力
/task shell on|off：管理员启停本机命令执行'''
ADMIN_HELP = '/profile：名字、昵称和头像\n/prompt：统一人设与文件上传\n/whitelist list|add QQ号|remove QQ号：白名单\n/pool [cn|global]：查看或切换号池\n签到：当前号池签到'


def help_text(*, admin=False, tasks=False, agent=False, section=''):
    sections = {'chat': CHAT_HELP, 'voice': VOICE_HELP}
    if tasks:
        sections['task'] = TASK_HELP
    if admin:
        sections.update(profile=PROFILE_HELP, prompt=PROMPT_HELP, admin=ADMIN_HELP)
    if section:
        return sections.get(section.lower(), '没有这个帮助分类。可用分类：' + '、'.join(sections))
    lines = ['/chat status|compress|reset|memory：对话与记忆',
             '/voice：回复模式、音色和朗读', '/draw 描述：生成图片']
    if tasks:
        lines.append('/task：执行任务、提醒和查询进度')
    if agent:
        lines.append('明确任务也可直接用自然语言提出；/task stop 停止当前执行')
    if admin:
        lines.extend(['/profile：名字、昵称和头像', '/prompt：统一人设',
                      '/whitelist：白名单', '/pool [cn|global]：号池；签到：账号签到'])
    lines.append('/help 分类：详细用法（' + '、'.join(sections) + '）')
    return '\n'.join(lines)


def normalize(text):
    """只重写明确命令的路由，不改写普通文本、人设或任务正文。"""
    parts = text.strip().split(maxsplit=1)
    if not parts or not parts[0].startswith('/'):
        return text
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ''
    sub = args.split(maxsplit=1)
    action = sub[0].lower() if sub else ''
    rest = sub[1] if len(sub) > 1 else ''
    target = None
    if command == '/chat':
        if action in ('status', 'compress', 'reset', 'emotion') and rest:
            return text  # 参数错误时只给用法，不能误清空历史。
        target = {'': '/status', 'status': '/status', 'compress': '/compress',
                  'reset': '/reset', 'emotion': '/emotion', 'memory': '/memory'}.get(action)
    elif command == '/profile':
        target = {'': '/setname', 'name': '/setname', 'nickname': '/setnickname', 'avatar': '/avatar'}.get(action)
    elif command == '/voice' and action in ('speaker', 'say'):
        target = '/' + action
    elif command == '/prompt' and action in ('upload', 'cancel'):
        target = '/setprompt'
        if action == 'cancel':
            rest = 'cancel' + (' ' + rest if rest else '')
    elif command == '/task' and action == 'stop' and not rest:
        target = '/stop'
    elif command == '/task' and action in ('remind', 'tools', 'shell'):
        target = '/remind' if action == 'remind' else '/tools'
        if action == 'shell':
            rest = 'shell ' + rest
    if target:
        return target + (' ' + rest if rest else '')
    return text
