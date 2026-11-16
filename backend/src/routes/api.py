import os,json
import redis
from pydantic import ValidationError
from fastapi import APIRouter,Depends,HTTPException,Response,Body
from src.config.database import db
from src.models.entities import User,Metric,Fact,Snapshot,Audit,Reconciliation
from src.schemas.business import Login,MetricInput,FactInput,RunInput,NoteInput,ReconExportInput,ReconReturnRow
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.repository import save_metric,save_fact
from src.services import reconciliation as recon
from src.controllers import business as ensure
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/metrics')
def metrics(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Metric).order_by(Metric.code,Metric.version).all()]
@router.post('/metrics')
def create_metric(data:MetricInput,u=Depends(editor),s=Depends(db)):
 r=save_metric(s,data);audit(s,u,'建立口径 '+r.code+' v'+str(r.version));return dump(r)
@router.put('/metrics/{i}')
def edit_metric(i:int,data:MetricInput,u=Depends(editor),s=Depends(db)):
 r=save_metric(s,data,i);audit(s,u,'修订口径 '+str(i));return dump(r)
@router.get('/facts')
def facts(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Fact).order_by(Fact.day.desc(),Fact.class_code).all()]
@router.post('/facts')
def create_fact(data:FactInput,u=Depends(editor),s=Depends(db)):
 r=save_fact(s,data);audit(s,u,'录入事实 '+str(r.id));return dump(r)
@router.put('/facts/{i}')
def edit_fact(i:int,data:FactInput,u=Depends(editor),s=Depends(db)):
 r=save_fact(s,data,i);audit(s,u,'修订事实 '+str(i));return dump(r)
@router.get('/snapshots')
def snapshots(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Snapshot).order_by(Snapshot.id.desc()).all()]
@router.post('/snapshots')
def run(data:RunInput,u=Depends(editor),s=Depends(db)):
 m=ensure.metric(s,data.metric_id);baseline=None
 if data.baseline_id:
  b=ensure.snapshot(s,data.baseline_id)
  if b.state!='done':raise HTTPException(409,'仅成功快照可作为比较基线')
  if b.result['metric']['code']!=m.code:raise HTTPException(409,'只能比较同一指标代码的口径版本')
  baseline=dict(id=b.id,date_from=b.date_from,date_to=b.date_to,result={k:b.result[k] for k in ['metric','value','facts_checksum']})
 values=data.model_dump(mode='json');rows=[dump(f) for f in s.query(Fact).filter(Fact.day>=values['date_from'],Fact.day<=values['date_to']).order_by(Fact.day,Fact.class_code).all()]
 frozen={'metric':dump(m),'facts':rows,'baseline':baseline,'date_from':values['date_from'],'date_to':values['date_to']}
 r=Snapshot(**values,result={'snapshot':frozen});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('camp:snapshots',r.id)
 except redis.RedisError:r.state='failed';r.error='队列不可用，请恢复后重新试算';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交试算 '+str(r.id));return dump(r)
@router.get('/snapshots/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure.snapshot(s,i))
@router.put('/snapshots/{i}/note')
def note(i:int,data:NoteInput,u=Depends(editor),s=Depends(db)):
 r=ensure.snapshot(s,i)
 if r.state!='done' or r.approval=='approved':raise HTTPException(409,'仅成功且未签核快照可编辑意见')
 r.note=data.note;s.commit();audit(s,u,'起草签核意见 '+str(i));return dump(r)
@router.post('/snapshots/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=ensure.snapshot(s,i)
 if r.state!='done' or r.approval=='approved':raise HTTPException(409,'仅成功且未签核快照可签核')
 if r.result['value'] is None:raise HTTPException(409,'零分母undefined快照不能签核，请修正口径')
 if len(r.note)<8:raise HTTPException(409,'先填写至少8字业务解释')
 m=ensure.metric(s,r.metric_id)
 if any(getattr(m,k)!=v for k,v in r.result['metric'].items() if k not in ['locked']):raise HTTPException(409,'口径在试算后已变更，请用当前版本重新试算再签核')
 r.approval='approved';r.approved_by=u.email;m.locked=True;s.commit();audit(s,u,'签核冻结 '+str(i));return dump(r)
@router.get('/snapshots/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure.snapshot(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功快照可导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="camp-metric-{i}.json"'})
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
# ---------- 离线核对单：导出 / 回传 / 预览重核 / 应用 ----------
@router.post('/reconciliations/export')
def export_recon(data:ReconExportInput,u=Depends(current),s=Depends(db)):
 flt=data.model_dump(mode='json')
 env=recon.build_sheet(s,u,flt)
 audit(s,u,'导出离线核对单 '+env['sheet_code'])
 return Response(json.dumps(env,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="camp-recon-{env["sheet_code"][:8]}.json"'})
@router.get('/reconciliations')
def list_recon(u=Depends(current),s=Depends(db)):
 return [dump(r) for r in s.query(Reconciliation).order_by(Reconciliation.id.desc()).all()]
@router.post('/reconciliations/upload')
def upload_recon(env:dict=Body(...),u=Depends(editor),s=Depends(db)):
 # 先按原始字节载荷验签，避免模型规范化改变签名依据
 env=recon.verify_envelope(env)
 # 再对回传行做白名单结构与取值校验（不改写 basis 原值依据）
 rows=(env.get('returned') or {}).get('rows')
 if not isinstance(rows,list) or not rows:raise HTTPException(400,'回传内容为空')
 try:
  env['returned']['rows']=[ReconReturnRow(**r).model_dump(mode='json') for r in rows]
 except ValidationError as e:
  msgs='；'.join('.'.join(map(str,x['loc']))+': '+x['msg'] for x in e.errors())
  raise HTTPException(422,'回传行不符合白名单结构或取值约束：'+msgs)
 existing=s.query(Reconciliation).filter_by(sheet_code=env['sheet_code']).first()
 if existing:
  # 同一核对单重复回传：幂等返回已存记录，不重复建单
  return dump(existing)
 preview=recon.merge_preview(s,env)
 rec=recon.persist_upload(s,u,env,preview)
 audit(s,u,'回传离线核对单 '+rec.sheet_code+('，冲突 %d 行'%preview['conflict_count'] if preview['conflict_count'] else ''))
 return dump(rec)
@router.get('/reconciliations/{i}')
def recon_detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure.reconciliation(s,i))
@router.post('/reconciliations/{i}/preview')
def recon_preview(i:int,u=Depends(current),s=Depends(db)):
 r=ensure.reconciliation(s,i)
 if r.state=='applied':return dump(r)
 preview=recon.merge_preview(s,r.sheet)
 r.preview=preview;r.conflict_count=preview['conflict_count'];r.change_count=preview['change_count']
 # 预览指纹：应用时据此判定预览后是否发生并发修订
 r.preview_digest=preview['current_digest'];s.commit()
 audit(s,u,'重新核对离线核对单 '+r.sheet_code)
 return dump(r)
@router.post('/reconciliations/{i}/apply')
def recon_apply(i:int,u=Depends(editor),s=Depends(db)):
 r=ensure.reconciliation(s,i)
 r,idempotent=recon.apply_sheet(s,r,u)
 if idempotent:audit(s,u,'重复应用已跳过 '+r.sheet_code)
 return dump(r)
