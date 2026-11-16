/** @typedef {{id:number,code:string,version:number,name:string,numerator:string,denominator:string,locked:boolean}} Metric */
/** @typedef {{id:number,class_code:string,day:string,mode:string,enrolled:number,attended:number,completed:number,refunds:number}} Fact */
/** @typedef {{id:number,metric_id:number,state:string,result:object,approval:string,note:string}} Snapshot */
/** @typedef {{id:number,sheet_code:string,state:'pending'|'applied',exported_by:string,exported_at:string,applied_by:string,applied_at:string,basis_digest:string,preview_digest:string,sheet:object,preview:object,conflict_count:number,change_count:number}} Reconciliation */
/** @typedef {{original:*,returned:*,current:*,merged:*,state:'unchanged'|'accepted'|'agreed'|'conflict'}} ReconField */
