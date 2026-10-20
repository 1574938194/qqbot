"""固定参考音频：预计算参考特征，释放仅参考编码所需的模型。"""
import gc
import ctypes

from fastapi.responses import JSONResponse
import torch


def install(api, reference):
    pipeline = api.tts_pipeline
    pipeline.set_ref_audio(reference)
    if len(pipeline.prompt_cache['refer_spec']) != 1:
        raise RuntimeError('fixed voice requires one reference')
    if pipeline.is_v2pro:
        audio = pipeline.prompt_cache['refer_spec'][0][1]
        with torch.inference_mode():
            embedding = pipeline.sv_model.compute_embedding3(audio).detach().clone()

        class CachedSpeaker:
            def compute_embedding3(self, audio):
                return embedding

        pipeline.sv_model = CachedSpeaker()
    pipeline.cnhuhbert_model = None
    gc.collect()
    try:
        ctypes.CDLL(None).malloc_trim(0)
    except (AttributeError, OSError):
        pass

    @api.APP.middleware('http')
    async def fixed_reference(request, call_next):
        if request.url.path == '/health':
            return await call_next(request)
        if request.url.path != '/tts':
            return JSONResponse({'message': 'fixed voice endpoint'}, status_code=404)
        try:
            data = await request.json() if request.method == 'POST' else request.query_params
            if data.get('ref_audio_path') != reference or data.get('aux_ref_audio_paths'):
                return JSONResponse({'message': 'fixed reference required'}, status_code=400)
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({'message': 'invalid request'}, status_code=400)
        return await call_next(request)
