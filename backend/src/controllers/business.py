from fastapi import HTTPException
from src.models.entities import Metric,Snapshot,Reconciliation
def metric(s,i):
 x=s.get(Metric,i)
 if not x:raise HTTPException(404,'口径版本不存在')
 return x
def snapshot(s,i):
 x=s.get(Snapshot,i)
 if not x:raise HTTPException(404,'试算快照不存在')
 return x
def reconciliation(s,i):
 x=s.get(Reconciliation,i)
 if not x:raise HTTPException(404,'核对单不存在')
 return x
