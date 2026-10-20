"""固定 UTC+8 的持久调度，不依赖 Windows tzdata。"""
import re
import time
from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8), 'Asia/Shanghai')


def duration(value):
    match = re.fullmatch(r'(\d+)(s|m|h|d|秒|分钟|小时|天)', str(value).strip())
    if not match:
        raise ValueError('时长格式：30s、10m、2h、1d。')
    amount = int(match[1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, '秒': 1, '分钟': 60, '小时': 3600, '天': 86400}[match[2]]
    if not 1 <= amount <= 366 * 86400:
        raise ValueError('时长应在 1 秒到 366 天之间。')
    return amount


def schedule(mode='now', when='', *, now=None):
    now = time.time() if now is None else now
    interval, daily = None, None
    if mode == 'now':
        due = now
    elif mode == 'in':
        due = now + duration(when)
    elif mode == 'at':
        try:
            date = datetime.fromisoformat(when)
            due = (date if date.tzinfo else date.replace(tzinfo=SHANGHAI)).timestamp()
        except (ValueError, TypeError):
            raise ValueError('时间格式：2026-10-21T08:00（无时区时按北京时间）。') from None
        if due <= now:
            raise ValueError('指定时间必须在未来。')
    elif mode == 'every':
        interval = duration(when)
        if interval < 60:
            raise ValueError('周期任务间隔至少 60 秒。')
        due = now + interval
    elif mode == 'daily':
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', when):
            raise ValueError('每日时间格式：08:30（北京时间）。')
        daily = when
        date = datetime.fromtimestamp(now, SHANGHAI).replace(hour=int(when[:2]), minute=int(when[3:]), second=0, microsecond=0)
        due = date.timestamp() if date.timestamp() > now else (date + timedelta(days=1)).timestamp()
    else:
        raise ValueError('调度模式必须为 now、in、at、every 或 daily。')
    return due, interval, daily


def next_due(task, *, now=None):
    now = time.time() if now is None else now
    if task['daily_time']:
        return schedule('daily', task['daily_time'], now=now)[0]
    if task['interval_seconds']:
        previous = task['next_run'] or now
        return previous + (max(0, int((now - previous) // task['interval_seconds'])) + 1) * task['interval_seconds']
    return None


def display_time(value):
    return datetime.fromtimestamp(value, SHANGHAI).strftime('%Y-%m-%d %H:%M:%S') + ' 北京时间' if value else '无'
