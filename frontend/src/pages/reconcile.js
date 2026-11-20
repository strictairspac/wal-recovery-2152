import {store} from '../stores/entities.js';
import {session} from '../stores/session.js';
import {reconciliationsAPI} from '../api/entities.js';
import {downloadReconciliation} from '../api/client.js';
import {table} from '../components/common/table.js';
import {esc} from '../utils/html.js';
import {action,message} from '../hooks/action.js';
import {RECONCILE_STATUSES,OUTBOX_STATUSES,MESSAGE_TYPES,RECEIVER_STATES,ALARM_VERDICTS} from '../constants/enums.js';

const rbadge=s=>`<span class="badge ${s==='confirmed'?'completed':'running'}">${esc(RECONCILE_STATUSES[s]||s)}</span>`;
const obadgeClass={acked:'completed',failed:'failed',held:'',pending:'running'};
const obadge=s=>`<span class="badge ${obadgeClass[s]??''}">${esc(OUTBOX_STATUSES[s]||s)}</span>`;
const vbadgeClass={valid:'completed',false_alarm:'failed',not_durable:''};
const vbadge=v=>`<span class="badge ${vbadgeClass[v]??''}">${esc(ALARM_VERDICTS[v]||v)}</span>`;
const sbadgeClass={active:'completed',withdrawn:'failed',absent:''};
const sbadge=s=>`<span class="badge ${sbadgeClass[s]??''}">${esc(RECEIVER_STATES[s]||s)}</span>`;
const canWrite=()=>session.role!=='viewer';

export function reconcilePage(){
 const completed=store.runs.filter(r=>r.status==='completed');
 const list=store.reconciliations.map(r=>[r.id,esc(r.label),`#${r.recovery_id}`,rbadge(r.status),
   r.sim_late?'迟到':'—',r.sim_lost_ack?'丢回执':'—',`<a href="#reconcile/${r.id}">打开对账 →</a>`]);
 return `<div class="section-title"><h2>警报补偿对账</h2><span>崩溃恢复后撤掉未提交写入的误报</span></div>
 ${table(['编号','对账记录','恢复','状态','迟到模拟','丢回执模拟','证据'],list)}
 <section class="split">
  <div><h2>发起一次补偿对账</h2>
   <p>恢复演算完成后，系统按事务结论判定每条警报：已提交写入的警报<b>有效保留</b>；未提交/已回滚写入的警报是<b>误报</b>，向接收方补发撤警补偿；写入未落盘的警报不发警。</p>
   <p class="big-note">账本可以先看，接收方确认后才算对账完成。</p>
   <p>发件箱消息带确定性幂等键：补偿与原警报乱序到达不会让误报复活；回执丢失后的重试不会重复撤警。全部状态落库，重启后接着对账。</p>
  </div>
  ${canWrite()?`<form id="rec-form">
   <label>恢复证据（仅已完成）<select name="recovery_id">${completed.length?completed.map(r=>`<option value="${r.id}">#${r.id} ${esc(r.label)}</option>`).join(''):''}</select></label>
   ${completed.length?'':'<p class="notice error">没有已完成的恢复，先到「恢复队列」执行一次恢复。</p>'}
   <label>对账标签<input name="label" value="晚班警报补偿核对" required></label>
   <label class="check"><input type="checkbox" name="sim_late" value="true"> 模拟迟到：原始警报先暂存，补偿先到</label>
   <label class="check"><input type="checkbox" name="sim_lost_ack" value="true"> 模拟丢回执：首次投递接收方已处理但回执丢失</label>
   <button type="submit" ${completed.length?'':'disabled'}>冻结判定并建账 →</button>
  </form>`:'<p class="readonly">观察员可查看下方对账与接收方状态。</p>'}
 </section>`;
}

function detailView(d){
 const verdictOf=alarmId=>(d.snapshot.plan||[]).find(p=>p.alarm_id===alarmId)?.verdict||'—';
 const expected=d.expected_final_state||{};
 const msgRows=d.messages.map(m=>[esc(m.message_id.slice(0,26)+'…'),esc(MESSAGE_TYPES[m.msg_type]||m.msg_type),
   `LSN${m.payload?.lsn??'—'} · ${esc(m.payload?.key??'—')}`,obadge(m.status),m.attempts,esc(m.last_error||'—')]);
 const recvRows=d.receiver_states.map(s=>[s.arrived_seq,`#${s.alarm_id}`,esc(MESSAGE_TYPES[s.msg_type]||s.msg_type),sbadge(s.alarm_state),esc(s.message_id.slice(0,22)+'…')]);
 const alarmRows=Object.values(d.alarms).filter(Boolean).map(a=>{const id=a.id;const exp=expected[String(id)]??'—';
   const cur=d.receiver_states.filter(s=>s.alarm_id===id).at(-1)?.alarm_state??'absent';
   return [`#${id} · LSN${a.lsn}`,esc(a.key),`${a.threshold} → ${a.observed}`,vbadge(verdictOf(id)),sbadge(exp),sbadge(cur),exp===cur?'<span class="badge completed">一致</span>':'<span class="badge failed">不一致</span>'];});
 return `<div class="section-title"><h2>${esc(d.label)} <small>#${d.id}</small></h2>${rbadge(d.status)}</div>
  <section class="verdict"><div><p>接收方核对</p><h2>${d.matches_expected?'终态与期望一致':'尚未核对一致'}</h2></div>
   <p>发件箱 ${d.messages.length} 条 · 已回执 ${d.messages.filter(m=>m.status==='acked').length} 条<br>
   接收方事件 ${d.receiver_states.length} 条 · 去重后无重复撤警<br>${d.status==='confirmed'?'全部回执已确认，对账完成':'仍有消息未确认，对账进行中'}</p></div>
  <h2>警报判定与接收方终态</h2>
  ${table(['警报 / 位置','采样键','阈值 → 实测','恢复判定','期望终态','接收方实际','核对'],alarmRows)}
  <h2>发件箱（至少一次投递 + 幂等键）</h2>
  ${table(['消息ID','类型','来源写入','发件箱状态','尝试次数','最近错误'],msgRows)}
  <h2>接收方去重账本（按到达顺序）</h2>
  ${table(['到达序','警报','消息','警报状态','消息ID'],recvRows)}
  <div class="toolbar">
   ${canWrite()?`<button class="secondary" id="release">放行迟到的原始警报</button>
   <button id="deliver">投递 / 重试到期消息</button>`:''}
   <button class="secondary" id="export">导出对账证据 JSON</button>
   <a class="secondary button-like" href="#reconcile">返回对账列表</a>
  </div>
  <details><summary>查看冻结判定计划与期望终态</summary><pre>${esc(JSON.stringify({plan:d.snapshot.plan,expected_final_state:expected},null,2))}</pre></details>`;
}

export async function reconcileDetailPage(id){
 if(!id){const first=store.reconciliations[0];if(first)return reconcileDetailPage(first.id);return '<section class="empty"><h2>还没有对账记录</h2><p>先完成一次恢复演练，再发起警报补偿对账。</p><a href="#reconcile">返回对账列表 →</a></section>';}
 const d=await reconciliationsAPI.get(Number(id));
 return detailView(d);
}

export function bindReconcile(render){
 action(document.querySelector('#rec-form'),async f=>{
   const fd=new FormData(f);const d={recovery_id:Number(fd.get('recovery_id')),label:fd.get('label'),
     sim_late:fd.get('sim_late')==='true',sim_lost_ack:fd.get('sim_lost_ack')==='true'};
   const obj=await reconciliationsAPI.create(d);location.hash='#reconcile/'+obj.id;
 });
}

export function bindReconcileDetail(render){
 const id=Number(location.hash.slice(1).split('/')[1]);
 document.querySelector('#release')?.addEventListener('click',async()=>{try{await reconciliationsAPI.releaseLate(id);message('迟到原始警报已放行，可继续投递');await render();}catch(e){message(e.message,true);}});
 document.querySelector('#deliver')?.addEventListener('click',async()=>{try{const d=await reconciliationsAPI.deliver(id);message(d.status==='confirmed'?'接收方已全部确认，对账完成':'已投递到期消息，查看接收方状态');await render();}catch(e){message(e.message,true);}});
 document.querySelector('#export')?.addEventListener('click',()=>downloadReconciliation(id).catch(e=>message(e.message,true)));
}
