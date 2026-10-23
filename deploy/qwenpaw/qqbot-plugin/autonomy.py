"""QQBot 的软件任务交付检查；继续执行由 QwenPaw 原生循环驱动。"""
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import re
import time
import uuid


def value(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def message_text(messages):
    texts = []
    for msg in messages or []:
        if value(msg, 'role') != 'user':
            continue
        content = value(msg, 'content', [])
        if isinstance(content, str):
            texts.append(content)
        else:
            texts.extend(str(value(p, 'text', '')) for p in content if value(p, 'type') == 'text')
    text = '\n'.join(texts)
    return text.rsplit('当前用户消息：\n', 1)[-1]


def coding_request(text):
    if text.lstrip().startswith('/') or re.search(r'只(?:需|要).{0,12}(?:解释|示例|方案)|不要(?:执行|写代码)|需要(?:多久|什么)|(?:如何|怎么|为什么).{0,12}(?:开发|编写)', text):
        return False
    action = re.search(r'^(?:(?:请|帮我|给我|麻烦|直接|现在|继续|你来)[，,\s]*)?(?:开发|编写|实现|修复|重构|改进|搭建|创建|制作|写(?:一个|个|一段)|做(?:一个|个))|(?:请|帮我|给我|麻烦).{0,40}(?:开发|编写|实现|修复|重构|改进|创建|制作)|^(?:(?:please|can you|could you)\s+)?(?:build|implement|develop|fix|refactor|create)\b', text.strip(), re.I)
    subject = re.search(r'代码|程序|项目|脚本|计算器|网页|网站|应用|软件|\b(?:cli|app|api|code|script|calculator|program|website)\b', text, re.I)
    return bool(action and subject)


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + path.name + '.new')
    if path.is_symlink() or temp.is_symlink():
        raise ValueError('任务记录路径不能是符号链接')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(path)


@dataclass
class Workflow:
    workspace: Path
    request_text: str
    enabled: bool = False
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    continuations: int = 0
    max_continuations: int = 3
    calls: list = field(default_factory=list)
    status: str = 'implementing'
    issue: str = ''

    def __post_init__(self):
        self.workspace = self.workspace.resolve()
        self.enabled = coding_request(self.request_text)

    @property
    def directory(self):
        directory = self.workspace / 'files' / '.qqbot-workflows' / self.task_id
        if not directory.resolve().is_relative_to(self.workspace):
            raise ValueError('任务记录越过工作区边界')
        return directory

    @property
    def receipt(self):
        return self.directory / 'review.json'

    @property
    def review_tag(self):
        return 'QQBOT_REVIEW:' + self.task_id

    def persist(self):
        if self.enabled:
            atomic_json(self.directory / 'state.json', {
                'task_id': self.task_id, 'status': self.status,
                'continuations': self.continuations, 'updated_at': time.time(),
                'request_sha256': hashlib.sha256(self.request_text.encode()).hexdigest(),
                'calls': self.calls,
            })

    def before_delegate(self, call_id, arguments):
        if arguments.get('runner') != 'deepseek_harness':
            return
        action = arguments.get('action')
        message = arguments.get('message', '')
        if action in ('start', 'message'):
            self.enabled = self.enabled or coding_request(message)
        if not self.enabled:
            return
        review = action == 'start' and self.review_tag in message
        closed = any(c['action'] == 'close' and c['ok'] for c in self.calls)
        self.calls.append({'id': call_id, 'action': action, 'review': review and closed, 'ok': False})
        if review:
            self.status = 'reviewing'
        self.persist()

    def after_delegate(self, call_id, ok):
        for call in self.calls:
            if call['id'] == call_id:
                call['ok'] = bool(ok)
        self.persist()

    def check(self, requested_file=None):
        """验收凭证必须来自本次独立会话，并与实际交付文件一致。"""
        if not self.enabled:
            return True, ''
        if not any(c['review'] and c['ok'] for c in self.calls):
            return False, '尚未完成独立 DSH 验收会话'
        work = [c for c in self.calls if c['action'] in ('start', 'message')]
        if not work or not work[-1]['ok']:
            return False, '最近的 DSH 执行尚未确认成功'
        try:
            receipt = self.receipt
            if receipt.is_symlink() or receipt.stat().st_size > 128 * 1024:
                raise ValueError('验收记录无效')
            data = json.loads(receipt.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('验收记录必须是 JSON 对象')
            if data.get('task_id') != self.task_id:
                raise ValueError('验收记录不是本次任务')
            if data.get('status') != 'passed':
                raise ValueError('自主验收未通过，请自行根据验收记录继续修复')
            checks = data.get('checks', [])
            kinds = set()
            for check in checks:
                if (not isinstance(check, dict) or not check.get('command') or not check.get('observed')
                        or check.get('passed') is not True
                        or type(check.get('exit_code')) is not int
                        or check['exit_code'] != check.get('expected_exit_code', 0)):
                    raise ValueError('验收用例缺少命令、实际输出或成功结果')
                kinds.add(check.get('kind'))
            if not {'baseline', 'boundary', 'package'}.issubset(kinds):
                raise ValueError('需要分别完成基线、独立边界和交付包验收')
            artifacts = data.get('artifacts', [])
            if not artifacts:
                raise ValueError('缺少交付文件及校验值')
            paths = []
            for item in artifacts:
                path = Path(item['path'])
                if not path.is_absolute():
                    path = self.workspace / 'files' / path
                path = path.resolve()
                if (not path.is_relative_to(self.workspace)
                        or not path.is_relative_to((self.workspace / 'files').resolve()) or not path.is_file()):
                    raise ValueError('交付文件不存在或越过工作区边界')
                if path.stat().st_size > 15 * 1024 * 1024:
                    raise ValueError('交付文件超过 QQ 附件大小限制')
                if hashlib.sha256(path.read_bytes()).hexdigest() != item.get('sha256'):
                    raise ValueError('交付文件已变化，需重新验收和更新校验值')
                paths.append(path)
            if requested_file:
                requested = Path(requested_file.removeprefix('file://'))
                if not requested.is_absolute():
                    requested = self.workspace / 'files' / requested
                if requested.resolve() not in paths:
                    raise ValueError('此附件不在已验收的交付文件中')
            self.status = 'passed'
            self.persist()
            return True, ''
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            return False, str(exc) if isinstance(exc, ValueError) else '验收记录尚未有效生成'

    def guide(self, issue=''):
        return f'''这是 QQBot 内部自主交付流程，不需要用户或 Codex 再发消息推动。
任务编号：{self.task_id}。验收记录：{self.receipt}。
你负责把用户需求推进到可交付结果：先自行制定验收清单并委托 deepseek_harness 实现。
实现完成后，close 当前 DSH 会话，再 start 一个独立验收会话；验收 message 必须包含 {self.review_tag}。
独立验收方自行读取需求和实际文件，重新设计并运行正常、非法、边界及资源限制测试，检查交付包解压后可运行，不能只转述实现者自测。
把用户原始需求和项目路径传给独立审查者，不能拿实现者的自测结论代替审查。
让验收方写入上述 JSON：task_id、status（passed/failed/blocked）、checks、artifacts。
checks 是数组，每项包含 name、kind（baseline/boundary/package）、command、exit_code、expected_exit_code、passed、observed（实际输出摘要）。三类检查都要有实际证据。
artifacts 是数组，每项包含 path（实际交付文件绝对路径）、sha256（文件当前 SHA256）。
发现失败，你自行使用 message 继续修复、补回归并重新验收，更新记录和交付包；不把这种反馈工作交还给用户。
记录通过后才 send_file_to_user 交付，并简洁报告结果。遇到授权缺失、上游故障或无法解决的阻塞，应如实说明，不能声称完成。
当前待解决：{issue or '完成实现后执行独立验收'}。'''


def register_autonomy(api):
    """通过 QwenPaw 官方 middleware、runtime hook 与 stop handler 接口接入。"""
    from agentscope.message import Msg, TextBlock, ToolResultState
    from agentscope.middleware import MiddlewareBase
    from agentscope.tool import ToolResponse
    from qwenpaw.config.config import load_agent_config
    from qwenpaw.loop.gates import StopAction, StopHandlerResult
    from qwenpaw.runtime.hooks import HookBase, HookResult
    from qwenpaw.runtime.phases import Phase

    class Prepare(HookBase):
        phase, name, priority = Phase.PRE_AGENT_BUILD, 'qqbot_autonomy_prepare', 85

        async def run(self, ctx):
            if (ctx.agent_id != 'qq-1574938194' and not re.fullmatch(r'qq-1574938194-task-[a-f0-9]{12}', ctx.agent_id)) or str(value(ctx.request, 'user_id', '')) != '1574938194':
                return HookResult()
            config = ctx.agent_config or load_agent_config(ctx.agent_id)
            runner = config.acp.agents.get('deepseek_harness')
            if not runner or not runner.enabled:
                return HookResult()
            text = message_text(value(ctx.request, 'input', []) or ctx.input_msgs)
            state = Workflow(Path(ctx.workspace_dir), text)
            ctx.extras['qqbot_autonomy'] = state
            if state.enabled:
                state.persist()
                ctx.inject_context(state.guide(), source=self.name)
            return HookResult()

    class Middleware(MiddlewareBase):
        def __init__(self, state):
            self.workflow = state

        async def on_acting(self, agent, input_kwargs, next_handler):
            state = self.workflow
            agent._qqbot_autonomy = state
            call = input_kwargs['tool_call']
            name, call_id = value(call, 'name', ''), value(call, 'id', '')
            args = value(call, 'input', {})
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                args = {}
            if name == 'send_file_to_user' and state.enabled:
                ok, issue = state.check(args.get('file_path') or args.get('path'))
                if not ok:
                    yield ToolResponse(id=call_id, state=ToolResultState.ERROR, content=[TextBlock(
                        type='text', text=state.guide(issue) + '\n附件尚未发送。')])
                    return
            delegated = name == 'delegate_external_agent'
            if delegated:
                state.before_delegate(call_id, args)
            succeeded = False
            failed = False
            try:
                async for item in next_handler():
                    response = value(item, 'response', item)
                    response_state = value(response, 'state')
                    if value(response_state, 'value', response_state) in ('error', 'cancelled', 'interrupted'):
                        failed = True
                    yield item
                succeeded = not failed
            finally:
                if delegated:
                    state.after_delegate(call_id, succeeded)

    def factory(ctx, config):
        state = ctx.extras.get('qqbot_autonomy')
        return Middleware(state) if state else None

    class Attach(HookBase):
        phase, name, priority = Phase.PRE_EXECUTE, 'qqbot_autonomy_attach', 90

        async def run(self, ctx):
            if ctx.agent is not None:
                ctx.agent._qqbot_autonomy = ctx.extras.get('qqbot_autonomy')
            return HookResult()

    async def check_stop(ctx):
        state = getattr(ctx['agent'], '_qqbot_autonomy', None)
        if not state or not state.enabled or ctx.get('has_tool_calls'):
            return StopHandlerResult(action=StopAction.BYPASS)
        ok, issue = state.check()
        if ok:
            return StopHandlerResult(action=StopAction.BYPASS)
        state.issue = issue
        if state.continuations >= state.max_continuations:
            state.status = 'blocked'
            state.persist()
            return StopHandlerResult(action=StopAction.TERMINATE, reason='qqbot autonomous review incomplete',
                final_message=Msg(name='assistant', role='assistant', content=[TextBlock(type='text',
                    text='任务尚未通过自主验收，执行记录和已生成文件已保留。当前问题：' + issue + '。')]))
        state.continuations += 1
        state.status = 'reviewing'
        state.persist()
        return StopHandlerResult(action=StopAction.INTERRUPT_AND_CONTINUE,
            reason='qqbot requires independent acceptance', continuation_message=state.guide(issue))

    async def stop(ctx):
        try:
            return await check_stop(ctx)
        except Exception:
            # 原生 runner 会跳过抛出异常的 handler；此处必须明确阻止误报成功。
            return StopHandlerResult(action=StopAction.TERMINATE,
                reason='qqbot acceptance unavailable',
                final_message=Msg(name='assistant', role='assistant', content=[TextBlock(
                    type='text', text='自主验收暂时无法完成，任务尚未交付。请稍后检查服务状态。')]))

    api.register_runtime_hook(Prepare())
    api.register_runtime_hook(Attach())
    api.register_middleware(factory, priority=75)
    api.register_agent_stop_handler(stop, priority=25, name='qqbot_autonomous_acceptance')
