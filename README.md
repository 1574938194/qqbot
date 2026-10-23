# 小爱 QQ Bot

基于 **Python 3.12、NoneBot2、OneBot v11 和 NapCat** 的私聊 AI 陪伴机器人。通过 buddyproxy 调用 DeepSeek，支持按用户隔离的记忆、图片理解、按需语音、定时提醒和可恢复的后台任务。

默认处理白名单私聊、只发送文字，不主动发送问候。群 `707318959` 仅在管理员 `1574938194` 明确 @ 机器人时回复；群会话与私聊隔离，不向群主动发送消息。详见[群聊规则](docs/GROUP.md)。

## 功能

- **陪伴与记忆**：管理员统一人设、角色名和昵称；SQLite 保存对话、摘要及情感状态。
- **上下文管理**：最大 260K tokens，估算输入超过 240K 时自动摘要，保留最近 6 轮完整对话；默认不按轮数提前压缩，支持手动压缩。失败不丢数据，清空与聊天按用户串行。
- **多模态**：DeepSeek V4.1 Flash 图片理解，支持配文和多图；头像设置等待期间优先修改头像。
- **语音**：单次朗读或按用户开启语音回复；支持 GPT-SoVITS 克隆音色、Edge 在线合成和 Windows SAPI。
- **长期记忆**：支持独立 Mem0 OSS 服务，QQ/QwenPaw 每轮自动检索、成功后后台提取用户事实，失败保留待办并重试；首次启用补建已有对话。见 [Mem0 部署](deploy/mem0/README.md)。
- **任务代理**：可选 QwenPaw 统一会话、网页控制台与记忆，通过原生 ACP 委托官方 DeepSeek Harness（DSH）执行 shell、文件和 Chromium 浏览器任务。接入与限制见 [QwenPaw 部署](deploy/qwenpaw/README.md)。
- **后台任务中心**：QwenPaw 模式下，明确的开发、检索和文件处理请求与 `/task run` 共用持久化队列；每个新任务独立工作区，执行期间可继续聊天。QQ 推送阶段和结果，网页任务中心提供查询、管理和成果下载。执行中断且副作用不确定时暂停，显式恢复后先检查已有状态。
- **任务清理**：`/task list` 仅显示待处理任务，`/task list all` 查看保留历史；结束任务满 7 天自动清理执行记录，未投递通知保留。
- **权限**：管理员、白名单、显式启用的本机命令；群聊仅处理指定群中的管理员直接 @，其他群消息、自身及未授权消息不触发模型。
- **网页调试**：通过 SSH 转发访问简单聊天页，复用管理员上下文，QQ 离线时也能聊天。

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

## 网页对话调试

启动机器人后，打开 `http://127.0.0.1:8080/debug` 即可直接聊天，不要求 NapCat 或 QQ 在线。无需额外安装网页依赖。

服务器部署时，在自己的电脑运行 SSH 转发（保持终端开启）：

```powershell
ssh -i E:\proj\agent_key.pem -N -L 127.0.0.1:18080:127.0.0.1:8080 root@110.40.226.103
```

然后打开 **http://127.0.0.1:18080/debug**。其他部署请替换密钥路径和服务器地址；本地端口被占用时可以改用 18081。

网页使用超级管理员 `1574938194` 的同一份上下文、人设、记忆和权限。普通聊天会保存，QQ 与网页聊天/清空共用同一用户锁；命令及命令回复不记入聊天上下文。页面显示最近 50 轮，刷新会重新读取历史，不会清空数据。支持多行消息、状态、压缩、文本命令以及 `/voice say` 语音试听；网页普通回复显示文字，`/voice` 设置仍影响 QQ。

点“添加图片”选择图片，可附带文字再发送，也可只发图片；默认一次最多3张、每张5 MiB，支持 JPEG、PNG、WebP、GIF，先解码压缩后识图。点“添加 txt/md”选择一个512 KiB以内的文本文件，不在人设等待状态时作为文件资料聊天，仍受单次输入和上下文长度限制。上传内容不保存到服务器文件目录，原图不写入聊天历史，只保存图片识别资料；普通文本附件内容会随成功聊天保存。

设置人设时，先发送 `/prompt upload`（或点“设置人设”），再在5分钟内单独上传一个 txt/md 文件并点发送。文件解码后的原文（含空格和换行）会替换统一 system prompt，支持 UTF-8、带BOM的UTF-16和GB18030，不调用模型、不记入聊天。网页会显示等待状态，可点“取消人设等待”或发 `/prompt cancel`。网页与 QQ 的等待分开；图片不消耗人设等待。命令与附件分开发送；头像设置继续使用 QQ。

QwenPaw 模式下，明确任务可用自然语言提出，`/task run` 可显式发起，`/task stop` 停止当前任务；legacy 模式使用 `/task run`。网页创建的后台任务、提醒向 QQ 投递，需要 QQ 资料 API 的命令要求 QQ 在线。左侧“任务中心”每5秒更新阶段与结果，支持暂停、取消、恢复、重试和下载模型明确交付的成果；QQ 离线不影响网页查看。自然语言接单立即返回任务编号，不再占用陪伴聊天等待任务完成。

入口只接受本机来源和本机 Host，并校验跨站来源与页面随机令牌，不使用独立密码。保持服务监听 `127.0.0.1`，只通过 SSH 转发访问，不要将网页反向代理或公开映射到公网。网页拥有管理员权限，与本机直接调试等效。

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

命令合并为英文分组：`/chat` 管对话和记忆，`/voice` 管语音，`/profile` 管资料，`/prompt` 管人设，`/task` 管任务和提醒。`/help` 查看精简目录，`/help chat|voice|task|profile|prompt|admin` 查看分类。旧命令及中文别名已移除，收到后返回帮助提示，不触发模型或操作；“签到”保留原入口。

| 命令 | 说明 |
| --- | --- |
| `/help`、`/chat status` | 帮助、模型、历史与上下文估算状态 |
| `/chat compress`、`/chat reset` | 压缩或清空自己的陪伴记忆与摘要 |
| `/chat emotion`、`/chat memory status` | 情感估算、外部记忆同步状态 |
| `/voice say 你好，我是小爱` | 单次发语音，不调用聊天模型 |
| `/voice on` / `off` / `both` | 语音 / 默认文字 / 文字加语音 |
| `/voice speaker aoi` / `noto` / `hayami` / `edge` | 悠木碧 / 能登麻美子 / 早见沙织 / 原 Edge 晓晓；list 查看，reset 恢复默认，按用户保存 |
| `/task remind in 10m 喝水` | 10分钟后提醒，也支持 at/every/daily |
| `/task run 计算17乘以3，将结果保存为result.txt` | 创建后台多步任务 |
| `/task list`、`/task show ID`、`/task steps ID` | 查询任务与执行进度 |
| `/task pause ID`、`/task cancel ID`；`/task resume ID`、`/task retry ID` | 暂停、取消、显式恢复或重试工具任务 |

仅超级管理员可用：

```text
/whitelist list
/whitelist add QQ号
/whitelist remove QQ号
/prompt upload
/prompt cancel
/prompt show
/prompt set 统一人设正文（支持多行）
/prompt reset
/profile name 爱
/profile nickname 小爱
/profile avatar
/profile avatar cancel
/task shell on
/task shell off
```

管理员发送 `/prompt upload` 后，5分钟内的下一条非命令私聊文本，或第一个 `.txt` / `.md` 文件，会原样替换统一 system prompt，下轮对话生效。支持多行与原换行，文件上限512KB，并受上下文长度限制；UTF-8、带BOM的UTF-16、GB18030文件可用。失败保留旧人设和剩余等待时间；`/prompt cancel` 取消。其他账号、群文件不会消耗等待；人设提交与确认不会进入聊天历史或调用模型，名字和昵称仍由 `/profile name`、`/profile nickname` 单独设置。

`/profile avatar` 后5分钟内收到的管理员第一张私聊图片用于设置头像；超时/取消后恢复普通识图。`/profile name` 设置正式角色名，`/profile nickname` 同步 QQ 昵称及角色昵称，身份独立保存，不改写原始人设文件。仅支持 `/profile` 下的资料命令。

未知 `/命令` 不进入模型；输入语音转文字尚未实现。

## 配置与数据

完整变量见 [`.env.example`](.env.example)，命令、任务恢复语义、Mem0/Letta 和排错见 [详细运行说明](docs/OPERATIONS.md)。

- 聊天默认 `deepseek-v4.1-flash`，识图默认跟随聊天模型，可用 `VISION_MODEL` 单独覆盖。
- 默认最大上下文260K，预计输入超过240K tokens时压缩，保留最近6轮；token均为估算值。
- 图片默认每条最多3张、每张5 MiB；不持久保存原图，识图描述作为标注来源的聊天资料保存。
- 语音默认关闭；`TTS_BACKEND=auto` 优先 Edge 在线语音，失败回退 Windows SAPI。设置 `sapi` 可仅本地合成。
- `MEMORY_BACKEND=none` 为默认值；接入 Mem0/Letta 需自行部署服务并配置独立密钥。
- SQLite与旧 DSH 成果文件位于 `data/`；QwenPaw 新任务的工作区在对应 QQ 工作区的 `files/.tasks/任务ID/`，需连同 QwenPaw state 备份。排队任务重启继续调度，执行中断且结果不确定的任务暂停等待 `/task resume ID`，不会盲目重放外部操作。`/chat reset` 保留独立任务、任务笔记及成果；停止定时工作用 `/task cancel ID`。

## 权限与隐私

默认只监听本机，日志不输出完整聊天或凭据，只发送模型最终正文。`.env`、`data/`、虚拟环境及个人角色文件均不应上传版本库。

图片会发送到配置的视觉模型服务。Edge 合成会把待朗读文本发送到微软语音服务；本地 SAPI 可避免这部分云端传输。外部记忆仅在显式启用后同步。

**DSH 默认关闭，仅供超级管理员使用。** `/task shell on` 开启后，任务在独立非 root Linux 容器执行，可运行 Python/bash 和 Chromium；不挂载机器人数据库、人设、Docker socket。取消不能撤销已发生的操作。部署与插件边界见 [DSH 配置](deploy/dsh/README.md)。

发送“帮我画一张雨夜街道的插画”或 `/draw 雨夜街道的插画` 可生成图片并直接显示在 QQ/网页，默认 `hunyuan-image-alpha`；明确画图请求不需要 `/tool`。生成图只展示在当前消息，不保存原图或签名 URL 到聊天历史。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

自动测试覆盖权限、上下文、记忆契约、情感状态、任务恢复、图片、语音、模拟 OneBot 收发和网页访问限制。DSH 使用官方 SDK 与独立持久会话；Mem0/Letta 仍以接口契约测试为主。

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

管理员私聊发送 **签到**，调用 buddyproxy 当前站点账号池签到并返回脱敏汇总。管理员通过 `/pool` 查看、`/pool cn` 切国内、`/pool global` 切国际，配置由代理持久化；`BUDDY_ADMIN_PASSWORD` 对应代理管理密码。国际站通常没有签到活动，返回不支持属于正常结果。

`/profile name 名字` 设置角色正式名字；不带参数可查看当前保存的名字及昵称。`/profile nickname 昵称` 单独修改昵称并同步 QQ。`/chat status` 也会显示两者。名字作为运行时身份覆盖旧人设和旧历史中的旧自称，原始人设与聊天历史保留。

GPT-SoVITS 纯云端部署和音色配置见 [语音部署](deploy/gpt-sovits/README.md)。

完整 GPT + SoVITS ONNX、多音色部署见 [ONNX 语音部署](deploy/onnx-speech/README.md)。设置 `TTS_BACKEND=genie` 后可使用 `/voice speaker`，默认仍为文字回复。三套克隆模型及各自参考音频独立挂载，只驻留当前选中的一套声学模型。选择 `edge` 时使用原微软晓晓语音；克隆生成失败会明确报错，不会自动换声音。
