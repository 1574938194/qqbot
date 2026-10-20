# GPT-SoVITS 云端语音

推理源码固定在 `UPSTREAM_REVISION` 指定的官方提交，支持已有 v2ProPlus 音色。QQ Bot 通过 API v2 调用独立服务，无需把 PyTorch 装进机器人容器。

## 准备

先运行 `python prepare-source.py` 下载固定版本到 `source/`，将已训练的 GPT、SoVITS 权重和参考音频上传服务器，不提交到 Git。`tts.yaml` 指向 `/voices/custom/gpt.ckpt`、`/voices/custom/sovits.pth`；基础 BERT、HuBERT、SV 与 v2ProPlus 资源位于 `/voices/pretrained/`，中文多音字模型及其字典、配置位于 `/voices/g2pw/`。提供与参考音频对应的转写文本和语言，参考音频建议为 3–10 秒。

上传权重和参考音频后运行 `python prepare-assets.py /opt/qqbot/voice/assets`，生成启动校验清单；不匹配或缺失会拒绝启动，避免静默回退其他模型。

## 构建

```bash
docker build --build-arg PYTHON_IMAGE=python:3.12-slim \
  --build-arg PIP_INDEX_URL=https://pypi.org/simple -t xiaoai-gsv:cpu .
```

运行依赖固定在 `requirements-cpu.lock`，CPU PyTorch 从官方 CPU wheel 源安装；Debian 和其他 Python 依赖可按网络环境选择镜像源。模型目录独立挂载，更新镜像不会替换模型。

## ONNX BERT 可选优化

`export-bert.py 原始BERT目录 空输出目录` 导出与上游 `hidden_states[-3]` 对应的特征图，再对线性运算做动态 INT8 量化，并对两个固定测试句检查 FP32 和 INT8 输出。导出环境需要 PyTorch、Transformers、NumPy、ONNX（已验证1.16.2）及 ONNX Runtime；原整合包的旧ONNX可能与量化工具不兼容，建议使用隔离环境。

将验证通过的 `bert.int8.onnx` 放到服务器 `/voices/custom/bert.int8.onnx`，重新运行 `prepare-assets.py` 生成包含ONNX校验值的清单，并在语音容器增加 `-e GSV_BERT_ONNX=/voices/custom/bert.int8.onnx`。启动器会直接加载 ONNX 特征图，不再加载完整 PyTorch BERT。这是 BERT 的混合推理优化，GPT/SoVITS仍使用PyTorch；v2ProPlus全链路ONNX需要另外适配声纹条件及解码流程，不能直接套用旧v1/v2导出入口。量化可能改变特征，仍需实际语音听感验收。

`export-g2pw.py 源码目录 原始G2PW目录 BERT分词器目录 空输出目录` 可量化已有G2PW ONNX，并用四个固定句子检查读音是否一致。只上传输出的 `g2pW.onnx` 及字典、配置文件，不上传用于导出的 `g2pW.source*.onnx` 中间文件。

## 运行

默认采用 host 网络且仅监听 `127.0.0.1:9880`，无需公网开放语音端口。对 2GB 小内存服务器必须先验证 CPU 推理的速度和内存，再设置独立内存/CPU上限及足够交换空间；不要直接让模型占满整机。

```bash
docker run -d --name xiaoai-speech --restart unless-stopped --network host \
  --memory=1400m --memory-swap=5g --cpus=1 \
  -v /opt/qqbot/voice/assets:/voices:ro \
  -v /opt/qqbot/voice/assets/pretrained:/srv/gpt-sovits/GPT_SoVITS/pretrained_models:ro \
  -v /opt/qqbot/voice/assets/g2pw:/srv/gpt-sovits/GPT_SoVITS/text/G2PWModel:ro \
  -v /opt/qqbot/voice/language/pyopenjtalk_dic:/usr/local/lib/python3.12/site-packages/pyopenjtalk/open_jtalk_dic_utf_8-1.11:ro \
  -v /opt/qqbot/voice/language/nltk_data:/root/nltk_data:ro \
  --log-opt max-size=5m --log-opt max-file=3 xiaoai-gsv:cpu
```

小内存实例可试用 `-e GSV_ORT_LOW_MEMORY=1`，关闭ONNX额外权重预打包和内存池；速度与内存收益需实测。

固定单一参考音色可增加 `-e GSV_FIXED_REF=/voices/reference/aoi.wav`，启动时预计算参考特征并释放HuBERT与声纹编码模型。此模式只开放 `/tts` 和 `/health`，拒绝更换参考音频、附加参考及运行中换权重，避免使用过期缓存。更换音色需更新资产校验清单并重启。

`/health` 在模型加载后返回 ready。服务串行合成，关闭原版推理器的逐句文本输出，错误日志仅保留异常类型及 HTTP 状态。

## QQ Bot 配置

```dotenv
TTS_BACKEND=gptsovits
TTS_VOICE=自定义克隆音色
TTS_BASE_URL=http://127.0.0.1:9880
TTS_REF_AUDIO=/voices/reference/aoi.wav
TTS_PROMPT_TEXT=与参考音频准确对应的转写
TTS_PROMPT_LANG=all_ja
TTS_TEXT_LANG=zh
TTS_TIMEOUT=180
TTS_MAX_CHARS=40
```

修改机器人环境变量后重建容器。默认仍是文字，`/say 内容` 单次合成，`/voice on` 语音、`/voice both` 文字及语音、`/voice off` 文字。GPT-SoVITS 失败不会自动改为其他音色；自动语音失败时保留/补发文字。

服务器上的模型、参考音频、转写文本和运行数据不进入仓库。原 Windows 整合包保留，新源码放在其 `cloud-release-提交号` 目录，云端使用独立 Python 3.12 CPU 环境。

## 本次云端实测

2 vCPU、约1.9GiB内存、无GPU，语音容器内存上限1400MiB、总内存及交换上限5GiB。BERT与G2PW使用INT8 ONNX，GPT/SoVITS仍为PyTorch，并启用固定参考缓存及ONNX低内存设置。固定测试中，2.18秒音频约42秒完成，4.04秒音频约58秒完成；普通话读音和最终音色仍需手机播放验收。此实例存在明显换页，不能视为实时语音性能。默认文字、按需开启语音，每段最多40字符、超时180秒。

完整v2ProPlus ONNX还可参考 [Genie](https://github.com/ayhsuic/Genie) 等实现，但它们的运行接口、导出图和分词流程需要单独适配及音质验证；本目录的部署不宣称已经完成全链路ONNX转换。
