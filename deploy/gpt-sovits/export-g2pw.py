from pathlib import Path
import sys,argparse
parser=argparse.ArgumentParser()
for name in ('source','model','bert','output'):parser.add_argument(name,type=Path)
args=parser.parse_args()
import json,shutil,time
from onnxruntime.quantization import quantize_dynamic,QuantType
root=args.model.resolve()
out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
if any(out.iterdir()):raise SystemExit('Use a new, empty output directory')
for name in ('config.py','version','POLYPHONIC_CHARS.txt','MONOPHONIC_CHARS.txt','bopomofo_to_pinyin_wo_tune_dict.json','char_bopomofo_dict.json'):shutil.copy2(root/name,out/name)
print('Quantizing existing G2PW ONNX',flush=True)
shutil.copy2(root/'g2pW.onnx',out/'g2pW.source.onnx')
quantize_dynamic(str(out/'g2pW.source.onnx'),str(out/'g2pW.onnx'),weight_type=QuantType.QUInt8,per_channel=True,op_types_to_quantize=['MatMul','Gemm'])
sys.path.insert(0,str(args.source.resolve()/'GPT_SoVITS'))
import onnxruntime
onnxruntime.get_available_providers=lambda: ['CPUExecutionProvider']
from text.g2pw import G2PWPinyin
from pypinyin import Style
bert=str(args.bert.resolve())
texts=['你好，我是梦梦。','今天有点累，想和你聊一会儿。','重庆银行的行长喜欢听音乐。','重要的事情要认真处理。']
reference=G2PWPinyin(model_dir=str(root),model_source=bert)
expected=[reference.pinyin(t,style=Style.TONE3) for t in texts];del reference
import gc
gc.collect()
optimized=G2PWPinyin(model_dir=str(out),model_source=bert)
actual=[optimized.pinyin(t,style=Style.TONE3) for t in texts]
print('G2PW pronunciation matches:',actual==expected,flush=True)
assert actual==expected,(expected,actual)
report={'source_bytes':(root/'g2pW.onnx').stat().st_size,'int8_bytes':(out/'g2pW.onnx').stat().st_size,'pronunciation_tests':len(texts),'matched':True}
(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
