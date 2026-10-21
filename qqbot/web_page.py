"""无外部依赖的调试页面；纯文本渲染，不解释模型返回的 HTML。"""

PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QQ Bot · 对话调试</title><style nonce="__NONCE__">
:root{font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif;color:#24303d;background:#f3f5f8;color-scheme:light}
*{box-sizing:border-box}body{margin:0}main{max-width:900px;height:100dvh;margin:auto;display:flex;flex-direction:column;padding:24px 20px 16px}
header{display:flex;justify-content:space-between;align-items:center;gap:12px}h1{font-size:21px;margin:0}#status{font-size:13px;color:#65758a}
.note{font-size:13px;color:#65758a;margin:8px 0 16px}.note strong{color:#a25a26}#messages{flex:1;overflow-y:auto;padding:8px 0;min-height:100px}
.row{display:flex;flex-direction:column;align-items:flex-start;margin:0 0 18px}.row.user{align-items:flex-end}.label{font-size:12px;color:#7b8797;margin:0 6px 4px}
.bubble{max-width:88%;white-space:pre-wrap;overflow-wrap:anywhere;padding:12px 16px;border-radius:16px;background:white;border:1px solid #e4e9ef}
.user .bubble{background:#e4edff;border-color:#d9e4fa}.system .bubble{color:#895d30;background:#fff8ee}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
button{font:inherit;border:1px solid #d5dce6;background:white;color:#3d536d;border-radius:9px;padding:6px 12px;cursor:pointer}button:hover{background:#eaf0f9}button:disabled{opacity:.5;cursor:wait}
form{display:flex;gap:10px;align-items:flex-end}textarea{resize:vertical;min-height:80px;max-height:240px;flex:1;min-width:0;border:1px solid #d5dce6;border-radius:12px;padding:12px;font:inherit;background:white;color:inherit}
textarea:focus{outline:2px solid #95b6ef;border-color:transparent}#send{background:#426bd5;color:white;border:0;height:44px;padding:0 20px}#progress{min-height:24px;font-size:12px;color:#65758a;margin-top:6px}audio{max-width:100%;display:block;margin-top:8px}
@media(max-width:600px){main{padding:16px 12px 8px}.bubble{max-width:94%}header{align-items:flex-start;flex-direction:column;gap:0}#send{padding:0 12px}}
</style></head><body><main>
<header><h1 id="title">QQ Bot · 对话调试</h1><span id="status">正在连接…</span></header>
<p class="note">使用管理员 QQ <b>1574938194</b> 的同一份上下文。普通对话会保存；命令及命令回复不记入聊天历史。<br>
仅 <b>/tool</b> 调用工具；提醒和后台任务通知仍发送到 QQ。网页仅支持文本与 <b>/say</b> 语音试听。</p>
<div id="messages" role="log" aria-live="polite"></div>
<div class="toolbar"><button type="button" data-command="/help">帮助</button><button type="button" data-command="/status">上下文状态</button><button type="button" data-command="/compress">压缩</button><button type="button" id="refresh">刷新历史</button></div>
<form id="form"><textarea id="input" placeholder="输入消息，或 /help 查看命令。Enter 发送，Shift+Enter 换行。" aria-label="消息" required></textarea><button id="send">发送</button></form>
<div id="progress" role="status">历史显示最近 50 轮；刷新页面后，临时命令结果不保留。</div>
</main><script nonce="__NONCE__">
const token='__TOKEN__', box=document.getElementById('messages'), input=document.getElementById('input'), progress=document.getElementById('progress');
let busy=false,name='机器人';
function add(role,text,audio=[]){const row=document.createElement('div');row.className='row '+role;const label=document.createElement('div');label.className='label';label.textContent=role==='user'?'你':role==='system'?'提示':name;const bubble=document.createElement('div');bubble.className='bubble';bubble.textContent=text;row.append(label,bubble);for(const data of audio){const player=document.createElement('audio');player.controls=true;player.src='data:audio/wav;base64,'+data;bubble.append(player)}box.append(row);box.scrollTop=box.scrollHeight}
async function api(path,options={}){const r=await fetch('/debug/'+path,{...options,headers:{'X-Debug-Token':token,'Content-Type':'application/json'}});let data;try{data=await r.json()}catch{throw Error('服务未返回有效响应，请检查 SSH 转发和机器人状态。')}if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'请求失败。');return data}
function pending(active){busy=active;for(const button of document.querySelectorAll('button'))button.disabled=active;input.disabled=active}
async function refresh(){try{const s=await api('state');name=s.name;document.getElementById('title').textContent=name+' · 对话调试';document.getElementById('status').textContent=s.model+' · QQ '+(s.qq_online?'在线':'离线（网页可聊天）');box.replaceChildren();for(const [u,a] of s.history){add('user',u);add('assistant',a)}if(!s.history.length)add('system','开始一段对话吧。也可以输入 /help 查看命令。');if(s.prompt_pending)add('system','正在等待人设：5 分钟内下一条非命令文本会成为 system prompt。用 /setprompt cancel 取消。')}catch(e){add('system',e.message)}}
async function send(text){if(busy||!text.trim())return;pending(true);add('user',text);input.value='';const start=Date.now();progress.textContent='正在处理…';const timer=setInterval(()=>{progress.textContent='正在处理… '+Math.round((Date.now()-start)/1000)+' 秒，请勿重复提交。'},1000);try{const data=await api('chat',{method:'POST',body:JSON.stringify({text})});add('assistant',data.reply,data.audio);progress.textContent='已完成 · '+Math.round((Date.now()-start)/1000)+' 秒'}catch(e){add('system',e.message);progress.textContent='发送失败；连接中断时请先刷新历史，确认上一条是否完成。'}finally{clearInterval(timer);pending(false);input.focus()}}
document.getElementById('form').addEventListener('submit',e=>{e.preventDefault();send(input.value)});input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send(input.value)}});for(const button of document.querySelectorAll('[data-command]'))button.addEventListener('click',()=>send(button.dataset.command));document.getElementById('refresh').addEventListener('click',async()=>{pending(true);try{await refresh()}finally{pending(false)}});refresh();
</script></body></html>'''
