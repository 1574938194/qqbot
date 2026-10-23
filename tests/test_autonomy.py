import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import pytest

spec = importlib.util.spec_from_file_location('qqbot_autonomy_test', Path(__file__).resolve().parents[1]/'deploy/qwenpaw/qqbot-plugin/autonomy.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

@pytest.mark.parametrize('text,expected', [
 ('开发一个CLI计算器', True), ('帮我修复这个Python项目', True), ('Can you build a CLI calculator?', True),
 ('今天写代码好累', False), ('开发一个计算器需要多久？', False), ('只要解释代码，不要执行', False),
 ('/task list', False), ('帮我查一下天气', False),
])
def test_scope(text, expected):
 assert module.coding_request(text) is expected

@pytest.fixture
def workflow(tmp_path):
 (tmp_path/'files').mkdir()
 return module.Workflow(tmp_path, '开发一个CLI计算器')

def certificate(w, *, status='passed'):
 artifact=w.workspace/'files'/'calculator.zip';artifact.write_bytes(b'test archive')
 w.receipt.parent.mkdir(parents=True,exist_ok=True)
 data={'task_id':w.task_id,'status':status,'checks':[
  {'kind':kind,'command':'python verify.py','exit_code':0,'expected_exit_code':0,'passed':True,'observed':'all cases passed'}
  for kind in ('baseline','boundary','package')],
  'artifacts':[{'path':str(artifact),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}]}
 w.receipt.write_text(json.dumps(data))
 return artifact,data

def independent_review(w):
 for cid,args in [('implement',{'action':'start','runner':'deepseek_harness','message':'实现CLI项目'}),
                   ('close',{'action':'close','runner':'deepseek_harness'}),
                   ('review',{'action':'start','runner':'deepseek_harness','message':w.review_tag+' independent review'})]:
  w.before_delegate(cid,args);w.after_delegate(cid,True)

def test_self_report_does_not_replace_independent_review(workflow):
 certificate(workflow)
 assert not workflow.check()[0]
 workflow.before_delegate('fake-review',{'runner':'deepseek_harness','action':'start','message':workflow.review_tag})
 workflow.after_delegate('fake-review',True)
 assert not workflow.check()[0]  # 没关闭执行会话，不能算独立验收。

def test_passed_receipt_and_artifact_are_required(workflow):
 independent_review(workflow)
 assert not workflow.check()[0]
 artifact,_=certificate(workflow)
 assert workflow.check(str(artifact))[0]
 assert workflow.check('calculator.zip')[0]
 artifact.write_bytes(b'changed after review')
 assert not workflow.check()[0]

def test_failed_review_requires_repair_and_recheck(workflow):
 independent_review(workflow)
 certificate(workflow,status='failed')
 assert not workflow.check()[0]
 workflow.before_delegate('repair',{'runner':'deepseek_harness','action':'message','message':'修复失败并重验'})
 certificate(workflow)
 assert not workflow.check()[0]
 workflow.after_delegate('repair',True)
 assert workflow.check()[0]

def test_stale_missing_boundary_and_other_files_rejected(workflow):
 independent_review(workflow);artifact,data=certificate(workflow)
 data['task_id']='old';workflow.receipt.write_text(json.dumps(data))
 assert not workflow.check()[0]
 artifact,data=certificate(workflow);data['checks']=data['checks'][:1];workflow.receipt.write_text(json.dumps(data))
 assert not workflow.check()[0]
 certificate(workflow)
 another=workflow.workspace/'files'/'unreviewed.zip';another.write_bytes(b'no')
 assert not workflow.check(str(another))[0]

def test_memory_isolation_and_no_prompt_in_audit(workflow,tmp_path):
 independent_review(workflow);certificate(workflow);workflow.check()
 audit=json.loads((workflow.directory/'state.json').read_text())
 assert 'request_text' not in audit and '开发' not in json.dumps(audit,ensure_ascii=False)
 other=module.Workflow(tmp_path,'开发一个CLI计算器')
 assert other.task_id!=workflow.task_id and not other.check()[0]

def test_path_escape_rejected(workflow,tmp_path):
 independent_review(workflow);artifact,data=certificate(workflow)
 outside=tmp_path.parent/'outside.zip';outside.write_bytes(b'outside')
 data['artifacts']=[{'path':str(outside),'sha256':hashlib.sha256(outside.read_bytes()).hexdigest()}]
 workflow.receipt.write_text(json.dumps(data))
 assert not workflow.check()[0]
