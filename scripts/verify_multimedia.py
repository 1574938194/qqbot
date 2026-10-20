"""真实视觉及语音验收，使用自造测试图与固定短句，不连接QQ。"""
import asyncio
import io
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

from qqbot.config import Settings
from qqbot.llm import LLM
from qqbot.media import Media, image_data


async def main():
    config = replace(Settings.load(), llm_rate_retries=0)
    llm = LLM(config)
    media = Media(None, llm, config)
    try:
        if 'voice' in sys.argv:
            audio = await media.synthesize('你好，我是小爱，很高兴见到你。')
            assert len(audio) > 1000
            Path('data').mkdir(exist_ok=True)
            Path('data/voice-verification.wav' if audio.startswith(b'RIFF') else 'data/voice-verification.mp3').write_bytes(audio)
            print('PASS: real speech synthesis; bytes=' + str(len(audio)), flush=True)
            return
        image = Image.new('RGB', (360, 110), 'yellow')
        ImageDraw.Draw(image).text((20, 25), 'TULIP 4729', font=ImageFont.load_default(size=40), fill='black')
        output = io.BytesIO()
        image.save(output, format='PNG')
        payload = image_data(output.getvalue(), config.vision_max_bytes)
        for model in [config.vision_model] if config.vision_model else ['glm-5v-turbo', 'glm-4.6v', 'gemini-3.5-flash']:
            print('Checking vision: ' + model, flush=True)
            try:
                async with asyncio.timeout(45):
                    result = await llm.create(model=model, messages=[{'role': 'system', 'content': '你是图片识别助手，只根据图片中的可见信息回答。'}, {'role': 'user', 'content': [
                        {'type': 'text', 'text': '请读取图中的英文和四位数字，并说明背景颜色。'},
                        {'type': 'image_url', 'image_url': {'url': payload}}]}], max_tokens=180)
                body = result.choices[0].message.content or ''
                if '4729' not in body or 'tulip' not in body.lower():
                    print('FAIL: vision OCR did not match test image.', flush=True)
                    continue
                print('PASS: real image recognition; model=' + model, flush=True)
                return
            except Exception as exc:
                print('FAIL: ' + type(exc).__name__, flush=True)
        raise RuntimeError('No verified vision model.')
    finally:
        await media.close()
        await llm.close()


if __name__ == '__main__':
    asyncio.run(main())
