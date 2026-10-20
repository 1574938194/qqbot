from pathlib import Path
import argparse,json,time
parser=argparse.ArgumentParser()
parser.add_argument("bert",type=Path)
parser.add_argument("output",type=Path)
args=parser.parse_args()
import numpy as np
import torch
from transformers import AutoModelForMaskedLM,AutoTokenizer
import onnxruntime as ort
from onnxruntime.quantization import quantize_dynamic,QuantType

torch.set_num_threads(2)
root=args.bert.resolve()
out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
if any(out.iterdir()):raise SystemExit('Use a new, empty output directory')
print('Loading original BERT for export',flush=True)
tokenizer=AutoTokenizer.from_pretrained(str(root),local_files_only=True)
original=AutoModelForMaskedLM.from_pretrained(str(root),local_files_only=True).eval()
class Feature(torch.nn.Module):
 def __init__(self,model):super().__init__();self.model=model.bert
 def forward(self,input_ids,attention_mask,token_type_ids):
  return self.model(input_ids=input_ids,attention_mask=attention_mask,token_type_ids=token_type_ids,output_hidden_states=True,return_dict=True).hidden_states[-3]
feature=Feature(original).eval()
texts=['你好，我是梦梦。','今天有点累，想和你聊一会儿。']
feeds=[dict(tokenizer(t,return_tensors='pt')) for t in texts]
expected=[]
with torch.inference_mode():
 for f in feeds:expected.append(feature(**f).numpy())
print('Exporting FP32 ONNX feature graph',flush=True)
axes={n:{0:'batch',1:'sequence'} for n in ('input_ids','attention_mask','token_type_ids','features')}
torch.onnx.export(feature,tuple(feeds[0][n] for n in ('input_ids','attention_mask','token_type_ids')),str(out/'bert.fp32.onnx'),input_names=['input_ids','attention_mask','token_type_ids'],output_names=['features'],dynamic_axes=axes,opset_version=17,do_constant_folding=True)
del feature, original
import gc
gc.collect()
print('Quantizing ONNX linear operators to INT8',flush=True)
quantize_dynamic(str(out/'bert.fp32.onnx'),str(out/'bert.int8.onnx'),weight_type=QuantType.QUInt8,per_channel=True,op_types_to_quantize=['MatMul','Gemm'])
options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
results=[]
for name in ('bert.fp32.onnx','bert.int8.onnx'):
 session=ort.InferenceSession(str(out/name),sess_options=options,providers=['CPUExecutionProvider'])
 for feed,reference in zip(feeds,expected):
  started=time.monotonic();value=session.run(['features'],{n:v.numpy() for n,v in feed.items()})[0]
  cosine=float(np.dot(value.ravel(),reference.ravel())/(np.linalg.norm(value)*np.linalg.norm(reference)))
  error=float(np.max(np.abs(value-reference)))
  results.append({'model':name,'tokens':value.shape[1],'cosine':cosine,'max_abs_error':error,'seconds':round(time.monotonic()-started,3)})
  assert cosine>(.9999 if name=='bert.fp32.onnx' else .98),results[-1]
 del session
report={'files':{p.name:p.stat().st_size for p in out.glob('*.onnx')},'checks':results}
(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
