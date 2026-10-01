"""阀门井室接口：维护阀门，覆盖安排启闭、卡涩复核、停用阀门等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.valve import ACTIONS, STATUS_ORDER, STATUS_DISABLED, ValveService

router = APIRouter(prefix="/api/valve", tags=["阀门井室"])

service = ValveService()

LIST_FIELDS = ["阀门编号", "阀门类别", "所在管段", "公称直径", "操作方向", "上次启闭日", "责任人员", "阀门状态"]
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按阀门编号检索"),
    status: str | None = Query(default=None, description="待启闭、操作正常、启闭卡涩、已停用"),
    include_disabled: bool = Query(default=False, description="是否一并列出已停用阀门"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按阀门编号与状态过滤阀门井室列表。

    默认返回待启闭清单，已停用阀门不出现；显式按「已停用」筛选或
    带上 include_disabled=true 时才包含停用记录。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        include_disabled=include_disabled,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def status_stats() -> dict[str, Any]:
    """阀门各状态计数；台账页面卡片与运营概览共用同一口径。"""
    return service.status_stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出阀门井室清单：含已停用阀门的全量数据，停用记录不会被悄悄抹掉。"""
    items, total = service.list_entries(include_disabled=True, page=1, size=10000)
    return {"module": "valve", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条阀门明细（含状态变更历史）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"阀门 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条阀门，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="阀门已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条阀门执行安排启闭、卡涩复核、停用阀门。

    跳级、复核未通过却转正常、停用不写原因等请求都会被拦下并说明原因，
    被拦时阀门保持原状态不变。
    """
    values = payload.values
    action = str(values.get("action") or "").strip()
    if action not in ACTIONS:
        return ActionResult(
            ok=False,
            message=f"动作「{action}」不属于阀门井室可执行范围，可选：{'、'.join(ACTIONS)}",
        )
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
