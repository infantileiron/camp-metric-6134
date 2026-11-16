ROLES=('admin','analyst','viewer')
STATES=('queued','running','done','failed')
MODES=('全部','线上','线下')
APPROVALS=('draft','approved')
FIELDS=('enrolled','attended','completed','refunds')
# 离线核对单状态：待核对 -> 已应用（终态，不可重复应用）
RECON_STATES=('pending','applied')
# 核对行逐字段合并结论（agreed 仅用于字段级：双方改成同值）
RECON_ROW_STATES=('unchanged','accepted','agreed','conflict','missing','invalid')
# 核对单导出文件格式版本
RECON_FORMAT='camp-fact-reconciliation-v1'
