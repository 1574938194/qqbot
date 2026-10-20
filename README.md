# 小爱 QQ Bot

基于 **Python 3.12、NoneBot2、OneBot v11 和 NapCat** 的私聊 AI 陪伴机器人。通过 buddyproxy 调用 DeepSeek，支持按用户隔离的记忆、图片理解、按需语音、定时提醒和可恢复的后台任务。

默认只处理白名单私聊、只发送文字，不主动发送问候。

## 功能

- **陪伴与记忆**：管理员统一人设、角色名和昵称；SQLite 保存对话、摘要及情感状态。
- **上下文管理**：最大 260K tokens，估算输入超过 240K 时自动摘要，保留最近 6 轮完整对话；默认不按轮数提前压缩，支持手动压缩。失败不丢数据，清空与聊天按用户串行。
- **多模态**：DeepSeek V4.1 Flash 图片理解，支持配文和多图；头像设置等待期间优先修改头像。
- **语音**：单次朗读或按用户开启语音回复；支持 Edge 在线合成和 Windows SAPI 回退。
- **长期记忆**：可选 Mem0 OSS REST / Letta blocks，默认不依赖外部记忆服务。
- **任务代理**：定时提醒、公开网页检索、计算、文件、笔记、多步工具执行、状态查询和检查点恢复。
- **任务清理**：`/task list` 仅显示待处理任务，`/task list all` 查看保留历史；结束任务满 7 天自动清理执行记录，未投递通知保留。
- **权限**：管理员、白名单、显式启用的本机命令；群消息、自身及未授权消息不触发模型。

## 环境

Linux 服务器 Docker 部署见 [部署说明](docs/DEPLOYMENT.md)；Windows 安装如下。

Windows + Python **3.12**（含 Python Launcher `py`），可用的 buddyproxy，以及已登录机器人 QQ 的 NapCat。

当前固定超级管理员为 `1574938194`，定义在 [`qqbot/config.py`](qqbot/config.py)。部署到其他账号前请修改该常量。机器人 QQ 应与管理员 QQ 不同。

## 安装与启动

在项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

也可双击 `install.bat`。脚本安装依赖，首次从 `.env.example` 生成 `.env` 和随机 OneBot Token；已有配置不会覆盖。

启动 buddyproxy，默认接口为 `http://127.0.0.1:32126/v1`。密钥优先读取进程环境变量 `LLM_API_KEY`、`OPENAI_API_KEY`、`CODEBUDDY_PROXY_API_KEY`，其次读取项目 `.env` 的 `LLM_API_KEY`，再读取 `~/.codebuddy/proxy.env` 的代理密钥。不要把密钥写入源码。

```powershell
.\start.ps1
# 或双击 start.bat
# 可选后台启动：.\start-background.ps1
```

同一数据库只运行一个机器人实例。默认监听 `127.0.0.1:8080`。

## NapCat 接入

按 [NapCat 配置指南](https://napneko.github.io/config/basic) 登录机器人 QQ，在网络配置中添加并启用 **WebSocket 客户端**：

| 设置 | 值 |
| --- | --- |
| URL | `ws://127.0.0.1:8080/onebot/v11/` |
| Token | 与 `.env` 的 `ONEBOT_ACCESS_TOKEN` 完全一致 |
| 消息格式 | `array` |
| 上报自身消息 / debug | 关闭 |
| 重连 / 心跳间隔 | `5000` / `30000` 毫秒 |

WebUI Token、OneBot Token、模型密钥相互独立。访问 `http://127.0.0.1:8080/health`，`connected_bots` 应包含机器人 QQ；再用管理员私聊发送 `/help`。

项目提供官方 NapCat 下载准备与便携启动脚本，见 [运行说明](docs/OPERATIONS.md#napcat-接入)。仓库不分发 QQ、NapCat 二进制或登录资料。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `/help`、`/status` | 帮助、模型、历史与上下文估算状态 |
| `/compress`、`/reset` | 压缩或清空自己的陪伴记忆与摘要 |
| `/emotion`、`/memory status` | 情感估算、外部记忆同步状态 |
| `/say 你好，我是小爱` | 单次发语音，不调用聊天模型 |
| `/voice on` / `off` / `both` | 语音 / 默认文字 / 文字加语音 |
| `/remind in 10m 喝水` | 10分钟后提醒，也支持 at/every/daily |
| `/task run 计算17乘以3，将结果保存为result.txt` | 创建后台多步任务 |
| `/task list`、`/task show ID`、`/task steps ID` | 查询任务与执行进度 |
| `/task pause ID`、`resume ID`、`cancel ID`、`retry ID` | 暂停、检查点恢复、取消或新一轮重试 |

仅超级管理员可用：

```text
/whitelist list
/whitelist add QQ号
/whitelist remove QQ号
/prompt show
/prompt set 统一人设正文（支持多行）
/prompt reset
/setname 爱
/setnickname 小爱
/avatar
/avatar cancel
/tools shell on
/tools shell off
```

`/avatar` 后5分钟内收到的管理员第一张私聊图片用于设置头像；超时/取消后恢复普通识图。`/setname` 设置正式角色名，`/setnickname` 同步 QQ 昵称及角色昵称，身份独立保存，不改写原始人设文件。`/name`、`/nickname` 是昵称命令的兼容别名。

未知 `/命令` 不进入模型；输入语音转文字尚未实现。

## 配置与数据

完整变量见 [`.env.example`](.env.example)，命令、任务恢复语义、Mem0/Letta 和排错见 [详细运行说明](docs/OPERATIONS.md)。

- 聊天默认 `deepseek-v4.1-flash`，识图默认跟随聊天模型，可用 `VISION_MODEL` 单独覆盖。
- 默认超过20轮或预计输入超过12,000 tokens时压缩，保留最近6轮；token均为估算值。
- 图片默认每条最多3张、每张5 MiB；不持久保存原图，识图描述作为标注来源的聊天资料保存。
- 语音默认关闭；`TTS_BACKEND=auto` 优先 Edge 在线语音，失败回退 Windows SAPI。设置 `sapi` 可仅本地合成。
- `MEMORY_BACKEND=none` 为默认值；接入 Mem0/Letta 需自行部署服务并配置独立密钥。
- SQLite与成果文件位于 `data/`，重启恢复。`/reset` 保留独立任务、任务笔记及成果；停止定时工作用 `/task cancel ID`。

## 权限与隐私

默认只监听本机，日志不输出完整聊天或凭据，只发送模型最终正文。`.env`、`data/`、虚拟环境及个人角色文件均不应上传版本库。

图片会发送到配置的视觉模型服务。Edge 合成会把待朗读文本发送到微软语音服务；本地 SAPI 可避免这部分云端传输。外部记忆仅在显式启用后同步。

**本机命令工具默认关闭。** 管理员开启后，PowerShell/Python 具有机器人账户的本机权限，不是沙箱；任务文件工具的目录限制不能约束管理员脚本。只在信任任务内容时开启；取消不能撤销已经产生的副作用。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

64项自动测试已通过，覆盖权限、上下文、记忆契约、情感状态、任务恢复、图片、语音和模拟 OneBot 收发。真实 buddyproxy 聊天、摘要、多步工具、DeepSeek 识图及真实 QQ 图片回复、语音播放也已验证。Mem0/Letta 使用接口契约测试，尚未宣称真实记忆服务验收。

以下脚本显式调用真实服务，使用测试输入和临时数据库，不向 QQ 发送消息：

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_chat
.\.venv\Scripts\python.exe -m scripts.verify_proxy
.\.venv\Scripts\python.exe -m scripts.verify_tasks
.\.venv\Scripts\python.exe -m scripts.verify_multimedia
.\.venv\Scripts\python.exe -m scripts.verify_multimedia voice
```

## 项目结构

```text
bot.py                  NoneBot入口
qqbot/                  聊天、模型、权限、存储、任务、资料与媒体模块
scripts/                NapCat准备及真实服务验收脚本
tests/                  自动测试和OneBot集成测试
docs/OPERATIONS.md      详细配置、运行语义与排错
.env.example            不含真实密钥的配置模板
```

管理员私聊发送 **签到**，调用 buddyproxy 当前站点账号池签到并返回脱敏汇总。`BUDDY_SITE` 默认为 `global`，国内站设为 `cn`；`BUDDY_ADMIN_PASSWORD` 对应代理管理密码。国际站通常没有签到活动，返回不支持属于正常结果。
