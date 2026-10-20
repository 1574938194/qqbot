import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ADMIN = 1574938194
DEFAULT_PROMPT = """你是小暖，一位温柔、自然、亲密的 AI 陪伴伙伴。用中文陪用户聊日常，认真关注情绪、生活细节和前面提到的事情。先理解和回应感受，适度追问，不说教、不机械重复、不动辄列清单或长篇回复。表达关心但不控制用户，尊重现实生活中的人际关系。不编造共同经历，不假装具有现实身体或真实人类身份。根据用户的语气自然交流，通常用几句简短的话回应。"""


@dataclass(frozen=True)
class Settings:
    buddy_admin_password: str = ""
    db_path: str = "data/buddy.sqlite3"
    base_url: str = "http://127.0.0.1:32126/v1"
    model: str = "deepseek-v4.1-flash"
    api_key: str = ""
    timeout: float = 90
    chat_timeout: float = 90
    chat_notice_seconds: float = 8
    compress_rounds: int = 0
    keep_rounds: int = 6
    context_tokens: int = 260000
    compress_tokens: int = 240000
    max_input_tokens: int = 6000
    max_reply_tokens: int = 1200
    summary_tokens: int = 1600
    message_chars: int = 1500
    memory_backend: str = "none"
    memory_base_url: str = ""
    memory_api_key: str = ""
    memory_timeout: float = 12
    memory_top_k: int = 5
    memory_chars: int = 2400
    emotion_enabled: bool = True
    tasks_enabled: bool = True
    task_workspace: str = "data/tasks"
    task_poll_seconds: float = 1
    task_concurrency: int = 2
    task_max_steps: int = 24
    task_max_per_user: int = 50
    task_tool_timeout: float = 60
    task_run_timeout: float = 900
    task_result_chars: int = 10000
    web_search_key: str = ""
    llm_tool_mode: str = "json"
    llm_min_interval: float = 1
    llm_rate_backoff: float = 30
    llm_rate_retries: int = 2
    vision_model: str = 'deepseek-v4.1-flash'
    vision_max_images: int = 3
    vision_max_bytes: int = 5242880
    vision_timeout: float = 40
    tts_backend: str = 'auto'
    tts_voice: str = 'zh-CN-XiaoxiaoNeural'
    tts_timeout: float = 30
    tts_max_chars: int = 500

    def __post_init__(self):
        for name in ("timeout", "keep_rounds", "context_tokens", "compress_tokens", "max_input_tokens", "max_reply_tokens", "summary_tokens", "message_chars", "memory_timeout", "memory_top_k", "memory_chars", "task_poll_seconds", "task_concurrency", "task_max_steps", "task_max_per_user", "task_tool_timeout", "task_run_timeout", "task_result_chars"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} 必须大于 0")
        if not 0 < self.chat_notice_seconds < self.chat_timeout:
            raise ValueError('CHAT_NOTICE_SECONDS 必须大于0且小于 CHAT_TIMEOUT')
        if min(self.vision_max_images, self.vision_max_bytes, self.vision_timeout, self.tts_timeout, self.tts_max_chars) <= 0:
            raise ValueError('图片及语音限制必须大于0')
        if self.tts_backend not in ('auto', 'edge', 'sapi', 'none'):
            raise ValueError('TTS_BACKEND 必须为 auto、edge、sapi 或 none')
        if not 0 < self.compress_tokens < self.context_tokens:
            raise ValueError('COMPRESS_TOKENS 必须大于 0 且小于 CONTEXT_TOKENS')
        if self.compress_rounds < 0:
            raise ValueError('COMPRESS_ROUNDS 必须大于或等于 0（0 表示关闭轮数触发）')
        if self.compress_rounds and self.keep_rounds >= self.compress_rounds:
            raise ValueError("KEEP_ROUNDS 必须小于 COMPRESS_ROUNDS")
        if self.memory_backend not in ("none", "mem0", "letta"):
            raise ValueError("MEMORY_BACKEND 必须为 none、mem0 或 letta")
        if self.llm_tool_mode not in ('json', 'single', 'native'):
            raise ValueError('LLM_TOOL_MODE 必须为 json、single 或 native')
        if self.llm_min_interval < 0 or self.llm_rate_backoff <= 0 or not 0 <= self.llm_rate_retries <= 5:
            raise ValueError('模型请求间隔/限流重试配置不正确')
        if self.memory_backend != "none":
            from urllib.parse import urlsplit
            url = urlsplit(self.memory_base_url)
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("MEMORY_BASE_URL 必须是无凭据、查询参数的 HTTP(S) 服务地址")

    @classmethod
    def load(cls):
        local = dotenv_values(".env")
        def value(name, default):
            return os.environ.get(name, local.get(name) or default)
        proxy = dotenv_values(Path.home() / ".codebuddy" / "proxy.env")
        key = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
               or os.getenv("CODEBUDDY_PROXY_API_KEY") or local.get("LLM_API_KEY")
               or proxy.get("CODEBUDDY_PROXY_API_KEY") or proxy.get("OPENAI_API_KEY") or "")
        return cls(
            buddy_admin_password=value('BUDDY_ADMIN_PASSWORD', os.getenv('CODEBUDDY_PROXY_ADMIN_PASSWORD') or proxy.get('CODEBUDDY_PROXY_ADMIN_PASSWORD') or ''),
            db_path=value("DB_PATH", "data/buddy.sqlite3"),
            base_url=value("LLM_BASE_URL", cls.base_url), model=value("LLM_MODEL", cls.model),
            api_key=key, timeout=float(value("LLM_TIMEOUT", "90")),
            chat_timeout=float(value('CHAT_TIMEOUT', '90')),
            chat_notice_seconds=float(value('CHAT_NOTICE_SECONDS', '8')),
            memory_backend=value("MEMORY_BACKEND", "none").lower(),
            memory_base_url=value("MEMORY_BASE_URL", "").rstrip("/"),
            memory_api_key=value("MEMORY_API_KEY", ""),
            memory_timeout=float(value("MEMORY_TIMEOUT", "12")),
            emotion_enabled=value("EMOTION_ENABLED", "true").lower() in ("true", "1", "yes"),
            tasks_enabled=value("TASKS_ENABLED", "true").lower() in ("true", "1", "yes"),
            task_workspace=value("TASK_WORKSPACE", "data/tasks"),
            task_poll_seconds=float(value("TASK_POLL_SECONDS", "1")),
            task_tool_timeout=float(value("TASK_TOOL_TIMEOUT", "60")),
            task_run_timeout=float(value("TASK_RUN_TIMEOUT", "900")),
            web_search_key=value("WEB_SEARCH_KEY", ""),
            llm_tool_mode=value('LLM_TOOL_MODE', 'json').lower(),
            llm_min_interval=float(value('LLM_MIN_INTERVAL', '1')),
            llm_rate_backoff=float(value('LLM_RATE_BACKOFF', '30')),
            llm_rate_retries=int(value('LLM_RATE_RETRIES', '2')),
            vision_model=value('VISION_MODEL', value('LLM_MODEL', cls.model)),
            vision_max_images=int(value('VISION_MAX_IMAGES', '3')),
            vision_max_bytes=int(value('VISION_MAX_BYTES', '5242880')),
            vision_timeout=float(value('VISION_TIMEOUT', '40')),
            tts_backend=value('TTS_BACKEND', 'auto').lower(),
            tts_voice=value('TTS_VOICE', 'zh-CN-XiaoxiaoNeural'),
            tts_timeout=float(value('TTS_TIMEOUT', '30')),
            tts_max_chars=int(value('TTS_MAX_CHARS', '500')),
            **{name: int(value(name.upper(), str(getattr(cls, name)))) for name in (
                "compress_rounds", "keep_rounds", "context_tokens", "compress_tokens", "max_input_tokens",
                "max_reply_tokens", "summary_tokens", "message_chars", "memory_top_k", "memory_chars",
                "task_concurrency", "task_max_steps", "task_max_per_user", "task_result_chars")},
        )
