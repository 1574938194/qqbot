"""只将明确的执行请求送入后台；闲聊、咨询和命令仍走原入口。"""
import re


def task_request(text):
    # 上传资料中的指令不能变成用户的执行请求。
    text = text.split('\n以下JSON是用户上传的文本文件资料', 1)[0]
    text = text.strip()
    if not text or text.startswith('/'):
        return False
    if re.search(r'不要(?:执行|调用|写代码)|只(?:需|要).{0,15}(?:解释|聊聊|方案)|需要(?:多久|什么)|^(?:如何|怎么|为什么)', text):
        return False
    action = re.search(r'^(?:(?:请|帮我|给我|麻烦|直接|现在|你来)[，,\s]*)?(?:用.{0,20})?(?:开发|编写|实现|修复|重构|搭建|创建|制作|写一个|写个|做一个|做个|搜索|查一下|查询|检索|查找|浏览|打开|下载|整理|分析|处理)|(?:请|帮我|给我|麻烦).{0,35}(?:开发|编写|实现|修复|重构|创建|搜索|检索|下载)|^(?:(?:please|can you|could you)\s+)?(?:build|develop|implement|fix|refactor|create|search|browse|download)\b', text, re.I)
    subject = re.search(r'代码|程序|项目|脚本|计算器|网页|网站|应用|软件|文件|资料|新闻|信息|仓库|文档|报告|目录|论文|https?://|\b(?:cli|app|api|code|script|calculator|program|website|file|github)\b', text, re.I)
    research = re.match(r'^(?:(?:请|帮我|给我|麻烦|直接|现在)[，,\s]*)?(?:搜索|查一下|查询|检索|查找|浏览|下载).+', text)
    recall = re.search(r'之前|上次|刚才|聊天记录|记忆', text)
    return bool(action and subject) or bool(research and not recall)
