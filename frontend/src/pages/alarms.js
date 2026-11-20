import {store} from '../stores/entities.js';
import {session} from '../stores/session.js';
import {alarmsAPI} from '../api/entities.js';
import {table} from '../components/common/table.js';
import {esc,formObject} from '../utils/html.js';
import {action} from '../hooks/action.js';

const writeRows=(records)=>records.map((r,i)=>({lsn:i+1,...r})).filter(r=>r.op==='write');

export function alarmsPage(){
 const log=store.logs[0];
 const writes=log?writeRows(log.records):[];
 const rows=store.alarms.map(a=>{
   const set=store.logs.find(l=>l.id===a.log_set_id);
   const rec=set?.records[a.lsn-1];
   return [a.id,esc(set?.name||'#')+` · LSN${a.lsn}`,esc(a.key),`${a.threshold} → ${a.observed}`,esc(rec?.tx||'—'),esc(a.note||'—')];
 });
 const logOptions=store.logs.map((l,i)=>`<option value="${l.id}"${i===0?' selected':''}>${esc(l.name)} · ${l.records.length}条</option>`).join('');
 const lsnOptions=(set)=>writeRows(set.records).map(w=>`<option value="${w.lsn}">LSN ${w.lsn} · ${esc(w.tx)} · ${esc(w.key)}=${w.value}</option>`).join('');
 return `<div class="section-title"><h2>超限警报台账</h2><span>警报锚定采样写入的日志位置</span></div>
 ${table(['编号','日志集 / 位置','采样键','阈值 → 实测','锚定事务','说明'],rows)}
 <section class="split">
  <div><h2>录入警报及其日志位置</h2>
   <p>每条警报必须锚定一条 <b>write</b> 日志（含事务与采样键）。断电前发出的警报，可能来自崩溃后被撤销的未提交写入。</p>
   <p class="big-note">先记位置，恢复后再判真假。</p>
   ${writes.length?`<details><summary>当前日志集可锚定的写入位置（${writes.length}条）</summary><div class="table-wrap"><table><thead><tr><th>LSN</th><th>事务</th><th>键</th><th>写入值</th></tr></thead><tbody>${writes.map(w=>`<tr><td>${w.lsn}</td><td>${esc(w.tx)}</td><td>${esc(w.key)}</td><td>${w.value}</td></tr>`).join('')}</tbody></table></div></details>`:'<p class="notice">先在「事务日志集」保存日志。</p>'}
  </div>
  ${session.role!=='viewer'?`<form id="alarm-form">
   <label>日志集<select name="log_set_id">${logOptions}</select></label>
   <label>日志位置 LSN<select name="lsn">${log?lsnOptions(log):''}</select></label>
   <label>采样键<input name="key" value="${esc(writes[0]?.key||'')}" required></label>
   <div class="fields"><label>阈值<input name="threshold" type="number" value="70" required></label>
   <label>实测值（须大于阈值）<input name="observed" type="number" value="75" required></label></div>
   <label>说明<input name="note" value="断电前超限警报"></label>
   <button type="submit">校验并登记警报</button>
  </form>`:'<p class="readonly">观察员仅查看，警报登记需要操作员或管理员。</p>'}
 </section>`;
}
export function bindAlarms(render){
 const form=document.querySelector('#alarm-form');
 const logSel=form?.querySelector('select[name=log_set_id]');
 const lsnSel=form?.querySelector('select[name=lsn]');
 const keyInput=form?.querySelector('input[name=key]');
 logSel?.addEventListener('change',()=>{
   const set=store.logs.find(l=>l.id===Number(logSel.value));
   if(!set)return;
   const ws=writeRows(set.records);
   lsnSel.innerHTML=ws.map(w=>`<option value="${w.lsn}">LSN ${w.lsn} · ${w.tx} · ${w.key}=${w.value}</option>`).join('');
   if(ws[0])keyInput.value=ws[0].key;
 });
 lsnSel?.addEventListener('change',()=>{
   const set=store.logs.find(l=>l.id===Number(logSel.value));
   const rec=set?.records[Number(lsnSel.value)-1];
   if(rec&&keyInput)keyInput.value=rec.key;
 });
 action(form,async f=>{const d=formObject(f);d.log_set_id=Number(d.log_set_id);d.lsn=Number(d.lsn);d.threshold=Number(d.threshold);d.observed=Number(d.observed);await alarmsAPI.create(d);await render();});
}
