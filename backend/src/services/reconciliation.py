import json,hashlib,hmac,uuid
from datetime import datetime,timezone
from fastapi import HTTPException
from src.constants.enums import FIELDS,RECON_FORMAT
from src.models.entities import Fact,Reconciliation
from src.utils.security import KEY
# 参与逐字段三方合并的字段（四项人次 + 授课方式 + 说明）
MERGE_FIELDS=list(FIELDS)+['mode','note']
def now_iso():return datetime.now(timezone.utc).isoformat()
def canonical(obj):
 # 稳定序列化：签名与指纹均以此为唯一字节依据
 return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def digest(obj):return hashlib.sha256(canonical(obj).encode()).hexdigest()
def _sign(payload):return hmac.new(KEY.encode(),canonical(payload).encode(),hashlib.sha256).hexdigest()
def fact_row(f):
 return dict(class_code=f.class_code,day=f.day,mode=f.mode,enrolled=f.enrolled,attended=f.attended,completed=f.completed,refunds=f.refunds,note=f.note or '')
def row_key(r):return (r['class_code'],r['day'])
def build_sheet(s,actor,flt):
 q=s.query(Fact)
 if flt.get('date_from'):q=q.filter(Fact.day>=flt['date_from'])
 if flt.get('date_to'):q=q.filter(Fact.day<=flt['date_to'])
 if flt.get('class_code'):q=q.filter(Fact.class_code==flt['class_code'])
 facts=q.order_by(Fact.day,Fact.class_code).all()
 if not facts:raise HTTPException(409,'筛选范围内没有班级日事实，无法导出核对单')
 rows=[fact_row(f) for f in facts]
 exported_at=now_iso();sheet_code=uuid.uuid4().hex
 basis=dict(digest=digest(rows),rows=rows)
 envelope=dict(format=RECON_FORMAT,sheet_code=sheet_code,exported_at=exported_at,exported_by=actor.email,filter=dict(date_from=flt.get('date_from') or '',date_to=flt.get('date_to') or '',class_code=flt.get('class_code') or ''),basis=basis,returned=dict(rows=[dict(r) for r in rows]))
 envelope['signature']=_sign({k:v for k,v in envelope.items()})
 return envelope
def verify_envelope(env):
 if not isinstance(env,dict) or env.get('format')!=RECON_FORMAT:raise HTTPException(400,'核对单格式无法识别')
 sig=env.get('signature')
 payload={k:v for k,v in env.items() if k!='signature'}
 if not sig or not hmac.compare_digest(sig,_sign(payload)):
  raise HTTPException(409,'核对单签名校验失败，原值依据可能已被篡改，请重新导出')
 basis=env.get('basis') or {}
 if basis.get('digest')!=digest(basis.get('rows') or []):
  raise HTTPException(409,'核对单原值摘要不一致，拒绝按该依据合并')
 return env
def _violations(r):
 out=[]
 for k in FIELDS:
  if not isinstance(r.get(k),int) or isinstance(r.get(k),bool) or r[k]<0:out.append(k+' 必须为非负整数')
 if out:return out
 if r['attended']>r['enrolled']:out.append('实到人次不得大于报名人次')
 if r['completed']>r['attended']:out.append('结课人次不得大于实到人次')
 if r['refunds']>r['enrolled']:out.append('退款人次不得大于报名人次')
 return out
def merge_preview(s,env):
 basis_rows=env['basis']['rows'];returned_rows=env['returned']['rows']
 basis_map={};returned_map={}
 for r in basis_rows:
  k=row_key(r)
  if k in basis_map:raise HTTPException(409,'核对单存在重复班级日期，原值依据已损坏')
  basis_map[k]=r
 for r in returned_rows:
  k=row_key(r)
  if k in returned_map:raise HTTPException(409,'回传存在重复班级日期行')
  returned_map[k]=r
 # 回传不得增删班级日期：键集合必须与导出原值完全一致
 if set(returned_map)!=(set(basis_map)):
  added=sorted(set(returned_map)-set(basis_map));removed=sorted(set(basis_map)-set(returned_map))
  raise HTTPException(409,'回传不得增删班级日期；新增 %s 个、缺失 %s 个班级日期行'%(len(added),len(removed)))
 current_map={row_key(fact_row(f)):fact_row(f) for f in s.query(Fact).all()}
 rows=[];conflict_count=0;change_count=0
 for k in sorted(basis_map):
  b=basis_map[k];rt=returned_map[k];cur=current_map.get(k)
  item=dict(class_code=k[0],day=k[1],basis=b,returned=rt,current=cur,merged=None,state='unchanged',violations=[],fields={})
  if cur is None:
   item['state']='missing';item['violations']=['现值中该班级日期事实已不存在，无法合并']
  else:
   merged=dict(cur);blocked=False
   for fld in MERGE_FIELDS:
    o,rv,cv=b.get(fld),rt.get(fld),cur.get(fld)
    cell=dict(original=o,returned=rv,current=cv,merged=cv,state='unchanged')
    if rv!=o:
     if cv==o:cell['state']='accepted';cell['merged']=rv;merged[fld]=rv
     elif cv==rv:cell['state']='agreed'
     else:cell['state']='conflict';cell['merged']=None;blocked=True
    item['fields'][fld]=cell
   if blocked:
    item['state']='conflict'
   else:
    v=_violations(merged)
    if v:item['state']='invalid';item['violations']=v
    else:
     item['merged']=merged
     if any(c['state']=='accepted' for c in item['fields'].values()):item['state']='accepted';change_count+=1
  if item['state'] in ('conflict','missing','invalid'):conflict_count+=1
  rows.append(item)
 preview=dict(generated_at=now_iso(),rows=rows,conflict_count=conflict_count,change_count=change_count,current_digest=digest([current_map[k] for k in sorted(basis_map) if k in current_map]))
 return preview
def current_fingerprint(s,env):
 keys=[row_key(r) for r in env['basis']['rows']]
 facts={row_key(fact_row(f)):fact_row(f) for f in s.query(Fact).all()}
 present=[facts[k] for k in sorted(keys) if k in facts]
 return digest(present),len(present)!=len(keys)
def persist_upload(s,u,env,preview):
 rec=Reconciliation(sheet_code=env['sheet_code'],state='pending',exported_by=env.get('exported_by') or '',exported_at=env.get('exported_at') or '',basis_digest=env['basis']['digest'],preview_digest=preview['current_digest'],sheet=env,preview=preview,conflict_count=preview['conflict_count'],change_count=preview['change_count'])
 s.add(rec);s.commit();return rec
def apply_sheet(s,rec,actor):
 if rec.state=='applied':return rec,True
 # 先锁核对单，串行化同一单据的应用与中断重试
 rec=s.query(Reconciliation).filter_by(id=rec.id).with_for_update().first()
 if rec.state=='applied':return rec,True
 env=rec.sheet
 # 预览后若线上发生并发修订，指纹变化，必须重新核对
 fp,missing=current_fingerprint(s,env)
 if missing or fp!=rec.preview_digest:
  raise HTTPException(409,'预览后线上事实已发生修订，请重新预览核对后再应用')
 preview=merge_preview(s,env)
 if preview['conflict_count']:
  rec.preview=preview;rec.conflict_count=preview['conflict_count'];rec.change_count=preview['change_count'];rec.preview_digest=preview['current_digest'];s.commit()
  raise HTTPException(409,'存在 %d 行冲突或校验失败，整单不写入，请逐行处理后重新回传'%preview['conflict_count'])
 # 行锁 + 单事务：整单全部成功或全部回滚，试算读取不会看到半单事实
 keys=[row_key(r) for r in env['basis']['rows']]
 locked={row_key(fact_row(f)):f for f in s.query(Fact).filter(Fact.day.in_({k[1] for k in keys}),Fact.class_code.in_({k[0] for k in keys})).with_for_update().all()}
 applied_rows=0
 for item in preview['rows']:
  if item['state']!='accepted':continue
  f=locked.get((item['class_code'],item['day']))
  if f is None:raise HTTPException(409,'班级 %s 日期 %s 的现值缺失，整单不写入'%(item['class_code'],item['day']))
  for fld in MERGE_FIELDS:setattr(f,fld,item['merged'][fld])
  applied_rows+=1
 rec.state='applied';rec.applied_by=actor.email;rec.applied_at=now_iso();rec.preview=preview;rec.conflict_count=0;rec.change_count=preview['change_count'];rec.preview_digest=preview['current_digest']
 s.add(rec)
 from src.services.business import audit
 audit(s,actor,'应用离线核对单 %s（写入 %d 行）'%(rec.sheet_code,applied_rows))
 return rec,False
