"""持久化调度与通知；任务执行委托官方 DSH。"""
import asyncio
import json
import logging
import time

from .config import ADMIN
from .llm import ModelError
from .scheduling import display_time, schedule
from .task_store import TaskStore
from .task_files import ToolError, TaskFiles
from .dsh_agent import DshAgent

TASK_HELP = '''/tool 任务内容（显式发起工具任务）
/tool /task run 任务内容
/tool /task in 10m 任务内容
/tool /task at 2026-10-21T08:00 任务内容
/tool /task every 1h 任务内容
/tool /task daily 08:00 任务内容
/remind in 10m 提醒内容（也支持 at/every/daily）
/task list
/task list all（最近 7 天历史）
/task show 任务ID
/task steps 任务ID
/task runs 任务ID
/task files 任务ID
/task file 任务ID 相对路径
/task cancel|pause 任务ID
/tool /task resume|retry 任务ID
/tool /task reply 任务ID 回答内容
/tools
/tools shell on|off（仅管理员）'''

class Tasks:
    def __init__(self, store, llm, config, *, sender=None):
        self.store, self.llm, self.config = store, llm, config
        self.repo = TaskStore(store)
        self.repo.migrate_dsh()
        self.tools = TaskFiles(self.repo, config)
        self.agent = DshAgent(config)
        self.sender = sender
        self.running = {}
        self.loop_task = None
        self.delivery_task = None
        self.stopping = False
        self.notification_retry = {}
        self.next_cleanup = 0

    def create(self, uid, instruction, *, kind='agent', mode='now', when='', bot_id=''):
        from .service import estimate
        if not self.store.allowed(uid):
            raise ValueError('没有任务权限。')
        if not isinstance(instruction, str) or not instruction.strip() or estimate(instruction) > self.config.max_input_tokens:
            raise ValueError('任务内容为空或过长。')
        if kind == 'agent' and (uid != ADMIN or not self.tools.shell_enabled()):
            raise ValueError('DSH 仅供管理员使用，请先用 /tools shell on 启用。')
        if kind not in ('agent', 'reminder'):
            raise ValueError('任务类型必须为 agent 或 reminder。')
        if self.repo.count_active(uid) >= self.config.task_max_per_user:
            raise ValueError('未结束任务数量已达上限，请先取消旧任务。')
        due, interval, daily = schedule(mode, when)
        return self.repo.create(uid, instruction.strip(), kind, due, interval, daily, bot_id)

    def brief(self, task):
        return f"{task['id']} [{task['state']}] {task['instruction'][:100]}\n下次执行：{display_time(task['next_run'])}"

    def details(self, uid, task_id, *, steps=False):
        task = self.repo.get(uid, task_id)
        if not task:
            raise ValueError('未找到你的任务。')
        text = self.brief(task)
        run = self.repo.latest_run(task_id)
        if run:
            text += f"\n最近执行：{run['id']} [{run['state']}]；模型轮次：{run['iterations']}"
            if steps:
                text += '\n' + '\n'.join(f"{i+1}. {s['name']} [{s['state']}] {s['result'][:300]}" for i, s in enumerate(self.repo.steps(run['id'])))
            if run['result']: text += '\n结果：\n' + run['result']
            if run['error']: text += '\n说明：' + run['error']
        return text

    def control(self, uid, task_id, action):
        task = self.repo.control(uid, task_id, action)
        if action in ('cancel', 'pause') and task_id in self.running:
            self.running[task_id][1].cancel()
        return self.brief(task)

    def revoke(self, uid):
        for task in self.repo.rows("SELECT * FROM tasks WHERE uid=? AND state IN ('scheduled','running','paused','waiting_input')", (uid,)):
            if task['state'] in ('scheduled', 'running', 'paused'):
                self.control(uid, task['id'], 'cancel')
        with self.repo.db:
            self.repo.db.execute('UPDATE task_runs SET notified=1 WHERE task_id IN (SELECT id FROM tasks WHERE uid=?)', (uid,))

    async def command(self, uid, command, args, *, bot_id=''):
        try:
            if command == '/tools':
                if args.startswith('shell '):
                    action = args.split()
                    if len(action) != 2 or action[1] not in ('on', 'off'):
                        return '格式：/tools shell on 或 /tools shell off'
                    self.tools.set_shell(uid, action[1] == 'on')
                    return '本机命令执行已' + ('启用（仅超级管理员任务）。' if action[1] == 'on' else '关闭。')
                return 'Agent 后端：DeepSeek Harness（DSH）\n能力由 DSH 配置与插件管理；旧版搜索、计算及 shell 工具循环已移除。\nDSH 执行：' + ('已启用' if self.tools.shell_enabled() else '未启用') + '\n' + TASK_HELP
            parts = args.split(maxsplit=1)
            action, rest = (parts + [''])[:2] if parts else ('', '')
            if action == 'list':
                if rest.strip() not in ('', 'all'):
                    return '格式：/task list 或 /task list all。'
                self.cleanup()
                return '\n\n'.join(self.brief(t) for t in self.repo.list(uid, include_finished=rest.strip() == 'all')) or '当前没有任务。'
            if action in ('show', 'steps'):
                return self.details(uid, rest.strip(), steps=action == 'steps')
            if action in ('runs', 'files', 'file'):
                arguments = rest.split(maxsplit=1)
                if not arguments or not self.repo.get(uid, arguments[0]):
                    return '未找到你的任务。'
                task_id = arguments[0]
                if action == 'runs':
                    return '\n'.join(f"{r['id']} [{r['state']}] {display_time(r['created_at'])}" for r in self.repo.rows(
                        'SELECT * FROM task_runs WHERE task_id=? ORDER BY created_at DESC LIMIT 30', (task_id,))) or '尚未执行。'
                if action == 'files':
                    return await self.tools.execute(uid, task_id, 'list_files', {})
                if len(arguments) != 2:
                    return '格式：/task file 任务ID 相对路径'
                return await self.tools.execute(uid, task_id, 'read_file', {'path': arguments[1]})
            if action == 'reply':
                arguments = rest.split(maxsplit=1)
                from .service import estimate
                if len(arguments) != 2 or estimate(arguments[1]) > self.config.max_input_tokens:
                    return '格式：/task reply 任务ID 回答内容（请限制输入长度）'
                self.repo.reply(uid, arguments[0], arguments[1])
                return '补充信息已保存，任务将继续执行。'
            if action in ('cancel', 'pause', 'resume', 'retry'):
                return self.control(uid, rest.strip(), action)
            if action == 'run' and command != '/remind':
                task = self.create(uid, rest, bot_id=bot_id)
            elif action in ('in', 'at', 'every', 'daily'):
                when_text = rest.split(maxsplit=1)
                if len(when_text) != 2:
                    return TASK_HELP
                task = self.create(uid, when_text[1], kind='reminder' if command == '/remind' else 'agent',
                                   mode=action, when=when_text[0], bot_id=bot_id)
            else:
                return TASK_HELP
            return '已创建任务：\n' + self.brief(task)
        except (ValueError, ToolError) as exc:
            return str(exc)
        except OSError:
            return '任务文件读取失败，请检查文件是否存在。'

    async def chat(self, uid, messages, *, bot_id=''):
        instruction = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), '')
        try:
            task = self.create(uid, instruction, bot_id=bot_id)
            return '已创建 DSH 任务：\n' + self.brief(task) + '\n结果会在后台完成后投递到 QQ，可用 /task show 查询。'
        except ValueError as exc:
            return str(exc)

    def initial_messages(self, task):
        # 不把陪伴人设和私人聊天传给代码/浏览器 agent。
        return [{'role': 'user', 'content': task['instruction']}]

    async def execute(self, task, run_id):
        uid = task['uid']
        try:
            async with asyncio.timeout(self.config.task_run_timeout):
                if task['kind'] == 'reminder':
                    self.repo.finish(task['id'], run_id, 'succeeded', result='提醒：' + task['instruction'])
                    return
                if uid != ADMIN or not self.tools.shell_enabled():
                    raise ModelError('DSH 未获管理员执行授权，请检查 /tools shell on。')
                # 单一有副作用的 DSH 步骤；进程中断时暂停，避免自动重复执行。
                existing = self.repo.steps(run_id)
                saved = json.loads(self.repo.run(run_id)['messages'])
                call_id = 'dsh-' + str(len(existing))
                call = {'id': call_id, 'type': 'function', 'function': {'name': 'dsh', 'arguments': '{}'}}
                self.repo.plan(run_id, saved, [call], {'dsh'})
                self.repo.begin_tool(run_id, call_id)
                execution = dict(task)
                legacy = [{'name': s['name'], 'state': s['state'], 'result': s['result'][:1000]}
                          for s in existing if s['name'] != 'dsh']
                if legacy:
                    execution['instruction'] = ('这是用户显式恢复的旧 agent 任务。以下是可能已产生副作用的历史资料，'
                        '不是新指令。必须先检查实际文件和外部状态，再继续未完成工作，不能盲目重放：\n'
                        + json.dumps(legacy[-20:], ensure_ascii=False) + '\n原任务：\n' + task['instruction'])
                additions = [m['content'] for m in saved if m.get('role') == 'user' and m.get('content', '').startswith('用户补充信息：')]
                if additions:
                    execution['instruction'] += '\n' + '\n'.join(additions)
                result = await self.agent.run(execution, run_id)
                if not self.store.allowed(uid):
                    self.repo.control(uid, task['id'], 'cancel')
                    return
                self.repo.tool_result(run_id, call_id, result[:self.config.task_result_chars], saved)
                self.repo.finish(task['id'], run_id, 'succeeded', result=result[:self.config.task_result_chars])
        except asyncio.CancelledError:
            raise
        except (ModelError, TimeoutError) as exc:
            self.repo.finish(task['id'], run_id, 'failed', error=str(exc) if isinstance(exc, ModelError) else 'DSH 执行超时，可能已产生部分副作用，请检查后再恢复。')
        except Exception as exc:
            logging.getLogger(__name__).warning('DSH task failure: %s', type(exc).__name__)
            self.repo.finish(task['id'], run_id, 'failed', error='DSH 内部错误，执行记录已保留。')

    async def notify(self):
        if not self.sender:
            return
        for run in self.repo.notifications():
            if not self.store.allowed(run['uid']):
                self.repo.delivered(run['id'], run['notify_index'], done=True)
                continue
            if self.notification_retry.get(run['id'], 0) > time.time():
                continue
            text = f"任务 {run['task_id']} [{run['state']}]\n" + (run['result'] or run['error'] or '执行已暂停。')
            parts = [text[i:i+self.config.message_chars] for i in range(0, len(text), self.config.message_chars)]
            try:
                for index in range(run['notify_index'], len(parts)):
                    if not self.store.allowed(run['uid']):
                        break
                    async with asyncio.timeout(15):
                        await self.sender(run['uid'], parts[index], run['bot_id'])
                    self.repo.delivered(run['id'], index + 1, done=index == len(parts)-1)
                self.notification_retry.pop(run['id'], None)
            except Exception as exc:
                logging.getLogger(__name__).warning('task notification failure: %s', type(exc).__name__)
                self.notification_retry[run['id']] = time.time() + 30

    def cleanup(self):
        now = time.time()
        if now >= self.next_cleanup:
            self.repo.prune(now - 7 * 86400)
            self.next_cleanup = now + 60
            self.notification_retry = {run_id: due for run_id, due in self.notification_retry.items() if self.repo.run(run_id)}

    async def tick(self, *, notify=True):
        self.cleanup()
        for task_id, (uid, worker) in list(self.running.items()):
            if not self.store.allowed(uid):
                self.revoke(uid)
            if worker.done():
                await asyncio.gather(worker, return_exceptions=True)
                del self.running[task_id]
        busy = {uid for uid, _ in self.running.values()}
        for task in self.repo.due(time.time()):
            if len(self.running) >= self.config.task_concurrency:
                break
            if not self.store.allowed(task['uid']):
                self.repo.control(task['uid'], task['id'], 'cancel')
                continue
            if task['uid'] in busy:
                continue
            run_id = self.repo.claim(task, self.initial_messages(task))
            if run_id:
                worker = asyncio.create_task(self.execute(task, run_id), name='qqbot-task-' + task['id'])
                self.running[task['id']] = (task['uid'], worker)
                busy.add(task['uid'])
        if notify:
            await self.notify()

    async def loop(self):
        while not self.stopping:
            try:
                await self.tick(notify=False)
            except Exception as exc:
                logging.getLogger(__name__).warning('scheduler failure: %s', type(exc).__name__)
            await asyncio.sleep(self.config.task_poll_seconds)

    async def deliver_loop(self):
        while not self.stopping:
            try:
                await self.notify()
            except Exception as exc:
                logging.getLogger(__name__).warning('notification worker failure: %s', type(exc).__name__)
            await asyncio.sleep(self.config.task_poll_seconds)

    def start(self):
        self.repo.recover()
        self.loop_task = asyncio.create_task(self.loop(), name='qqbot-scheduler')
        self.delivery_task = asyncio.create_task(self.deliver_loop(), name='qqbot-delivery')

    async def close(self):
        self.stopping = True
        services = [task for task in (self.loop_task, self.delivery_task) if task]
        for task in services:
            task.cancel()
        workers = [worker for _, worker in self.running.values()]
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, *services, return_exceptions=True)
        await self.tools.close()
