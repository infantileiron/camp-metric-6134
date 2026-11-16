import {state} from '../stores/session.js';
import {esc} from '../utils/html.js';
import {table} from '../components/common/table.js';
import {FIELD_LABELS} from '../constants/enums.js';
import {field} from '../components/common/fields.js';
const STATE_TEXT={unchanged:'无改动',accepted:'离线单方改动·接纳',agreed:'双方同值·接纳',conflict:'双方异值·冲突',missing:'现值缺失',invalid:'人次关系违例'};
const rowClass=r=>r==='conflict'||r==='missing'||r==='invalid'?'danger':r==='accepted'||r==='agreed'?'ok':'';
function fieldCells(r){
 return ['enrolled','attended','completed','refunds','mode','note'].map(fld=>{
  const c=r.fields[fld];
  if(c.state==='unchanged')return `<td class="muted">${esc(c.original)}</td>`;
  return `<td class="${rowClass(c.state==='agreed'?'agreed':c.state)}"><b>${esc(FIELD_LABELS[fld])}</b> ${esc(c.original)} → 回传${esc(c.returned)} / 现值${esc(c.current)}<br><span class="eyebrow">${esc(STATE_TEXT[c.state]||c.state)}</span></td>`;
 }).join('');
}
function previewPanel(rec){
 const p=rec.preview;
 if(!p)return '<p class="notice">该核对单尚未生成预览。</p>';
 const conflicts=p.rows.filter(r=>r.state==='conflict'||r.state==='missing'||r.state==='invalid');
 return `<p>生成于 ${esc(p.generated_at)} · 接纳改动 <b>${p.change_count}</b> 行 · 冲突/违例 <b class="${p.conflict_count?'danger-text':''}">${p.conflict_count}</b> 行</p>
 ${conflicts.length?`<h3>冲突定位（班级 / 日期 / 原值 / 回传值 / 现值）</h3>${table(['班级','日期','结论','违例说明'],conflicts.map(r=>[r.class_code,r.day,STATE_TEXT[r.state],r.violations.join('；')]))}`:'<p class="notice">无冲突，可整单应用。应用在单事务内完成，任一行失败则整单不写入。</p>'}
 <h3>逐字段三方合并明细</h3>
 <div class="scroll"><table><thead><tr><th>班级</th><th>日期</th><th>行结论</th>${['enrolled','attended','completed','refunds','mode','note'].map(f=>`<th>${esc(FIELD_LABELS[f])}</th>`).join('')}</tr></thead>
 <tbody>${p.rows.map(r=>`<tr class="${rowClass(r.state)}"><td>${esc(r.class_code)}</td><td>${esc(r.day)}</td><td>${esc(STATE_TEXT[r.state]||r.state)}${r.violations.length?`<br><span class="danger-text">${esc(r.violations.join('；'))}</span>`:''}</td>${fieldCells(r)}</tr>`).join('')}</tbody></table></div>`;
}
export function render(){
 const canWrite=state.user.role!=='viewer';
 return `<div class="split"><section class="panel">
 <h2>离线核对单 / ${state.reconciliations.length} 张</h2>
 <p class="notice">班主任离线核对期间线上仍可修订。回传按 <b>原值 / 回传值 / 现值</b> 逐字段三方合并：仅一方改动或双方同值予以接纳，双方异值报冲突且整单不写入。原值带 HMAC 签名防篡改，回传不得增删班级日期；预览后若线上再修订，须重新核对才能应用。</p>
 <h3>核对单列表（待核对 → 已应用）</h3>
 ${state.reconciliations.length?table(['ID','单号','状态','导出时间','导出人','接纳行','冲突行','应用人','应用时间'],state.reconciliations.map(r=>[r.id,r.sheet_code.slice(0,8),r.state==='pending'?'待核对':'已应用',r.exported_at,r.exported_by,r.change_count,r.conflict_count,r.applied_by||'—',r.applied_at||'—'])):'<p class="notice">暂无核对单，先在右侧导出。</p>'}
 <div class="recon-list">${state.reconciliations.map(r=>`<article class="rec recon-card"><h3>#${r.id} ${esc(r.sheet_code.slice(0,8))} <span class="tag ${r.state==='applied'?'ok':'warn'}">${r.state==='pending'?'待核对':'已应用'}</span></h3>
 <p>原值摘要 <code>${esc((r.basis_digest||'').slice(0,16))}…</code>${r.applied_by?` · 应用人 ${esc(r.applied_by)} @ ${esc(r.applied_at)}`:''}</p>
 ${previewPanel(r)}
 <p class="recon-actions">
 <button data-recon-preview="${r.id}" ${r.state==='applied'?'disabled':''}>重新核对（预览）</button>
 <button data-recon-apply="${r.id}" class="primary" ${r.state==='applied'||!canWrite?'disabled':''}>${r.state==='applied'?'已应用（不可重复）':'整单应用'}</button>
 </p></article>`).join('')}</div>
 </section>
 <aside class="side">
 <h2>导出核对单</h2>
 <form id="recon-export">
 ${field('开始日（可选）','date_from','date','value="2026-10-17"')}
 ${field('结束日（可选）','date_to','date','value="2026-11-15"')}
 ${field('班级代码（可选，如 QH-01）','class_code','text')}
 <button class="primary">下载核对单 JSON</button>
 </form>
 <h2>回传核对单</h2>
 <label>选择离线核对后的 JSON<input type="file" id="recon-file" accept="application/json,.json" ${canWrite?'':'disabled'}></label>
 <p class="notice">文件仅在本页读取后上传，不会改写本地原件。观察员为只读，不能回传或应用。</p>
 <h3>状态流转</h3>
 <p class="notice">待核对 →（预览/重核）→ 应用 → 已应用（终态）。应用与试算读取相互隔离，读不到半单事实；已签核快照冻结的事实依据不受影响。</p>
 </aside></div>`;
}
