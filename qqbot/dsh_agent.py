"""DSH 是唯一 agent 执行后端；机器人只负责准入、调度和结果投递。"""
import httpx

from .config import ADMIN
from .llm import ModelError


class DshAgent:
    def __init__(self, config):
        self.config = config

    async def run(self, task, run_id):
        if task['uid'] != ADMIN:
            raise ModelError('DSH 执行当前仅向超级管理员开放。')
        if not self.config.dsh_token:
            raise ModelError('DSH 服务未配置，请管理员检查 DSH_BASE_URL 和 DSH_TOKEN。')
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=self.config.task_run_timeout) as client:
                response = await client.post(self.config.dsh_base_url.rstrip('/') + '/run',
                    headers={'Authorization': 'Bearer ' + self.config.dsh_token},
                    json={'uid': task['uid'], 'task_id': task['id'], 'run_id': run_id,
                          'instruction': task['instruction']})
            if not response.is_success:
                raise ModelError('DSH 执行失败，请查看任务状态；已产生的文件和外部操作不会自动撤销。')
            result = response.json()
            if result.get('finish_reason') != 'completed' or not isinstance(result.get('text'), str) or not result['text'].strip():
                raise ModelError('DSH 未正常完成，执行记录已保留；请检查任务后决定是否恢复。')
            return result['text']
        except ModelError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ModelError('DSH 服务连接失败或超时。请先检查任务执行状态，避免重复产生副作用。') from None
