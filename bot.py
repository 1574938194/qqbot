import logging
import os

import nonebot
from dotenv import dotenv_values
from nonebot.adapters.onebot.v11 import Adapter


def main():
    env = dotenv_values(".env")
    token = os.getenv("ONEBOT_ACCESS_TOKEN") or env.get("ONEBOT_ACCESS_TOKEN")
    if not token or token == "replace-with-random-token":
        raise SystemExit("请先运行 install.ps1，或在 .env 配置随机 ONEBOT_ACCESS_TOKEN。")
    # WARNING 避免框架默认的事件 INFO 日志记录完整私聊正文。
    nonebot.init(driver="~fastapi", host=os.getenv("HOST", env.get("HOST") or "127.0.0.1"),
                 port=int(os.getenv("PORT", env.get("PORT") or "8080")),
                 log_level="WARNING", onebot_access_token=token)
    for name in ("openai", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    nonebot.get_driver().register_adapter(Adapter)
    nonebot.load_plugin("qqbot.plugin")
    nonebot.run()


if __name__ == "__main__":
    main()
