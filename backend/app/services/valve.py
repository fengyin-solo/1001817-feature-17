"""阀门井室业务规则：状态流转、字段校验与筛选口径都收在这里。

阀门状态只能顺着安排启闭 → 操作正常/启闭卡涩 → 卡涩复核 → 停用 推进：
- 安排启闭只能在「待启闭」阶段执行，结果为操作正常或启闭卡涩，不允许跳级；
- 卡涩复核只能在「启闭卡涩」阶段执行，复核通过才能回到操作正常，
  复核不通过就停留在启闭卡涩，不许跳到操作正常；
- 停用阀门可以在任何在役状态执行，但必须写明停用原因；
- 已停用是终态，不再参与待启闭清单，也不允许任何后续动作；
- 每次状态变更（含复核未通过的复核记录）都追加到 history，只增不改，
  历史按当时的口径保留。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "valve"
REQUIRED_FIELDS = ["阀门编号", "阀门类别", "所在管段"]
STATUS_PENDING = "待启闭"
STATUS_NORMAL = "操作正常"
STATUS_STUCK = "启闭卡涩"
STATUS_DISABLED = "已停用"
STATUS_ORDER = [STATUS_PENDING, STATUS_NORMAL, STATUS_STUCK, STATUS_DISABLED]

ACTION_SCHEDULE = "安排启闭"
ACTION_RECHECK = "卡涩复核"
ACTION_DISABLE = "停用阀门"
ACTIONS = [ACTION_SCHEDULE, ACTION_RECHECK, ACTION_DISABLE]

RESULT_NORMAL = "操作正常"
RESULT_STUCK = "启闭卡涩"
RECHECK_PASS = "复核通过"
RECHECK_FAIL = "复核未通过"
RECHECK_RESULTS = [RECHECK_PASS, RECHECK_FAIL]

# 待启闭清单的口径：待启闭 + 启闭卡涩（操作正常与已停用都不算待办）
WORKLIST_STATUSES = {STATUS_PENDING, STATUS_STUCK}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _is_pending(status: str) -> bool:
    return status in WORKLIST_STATUSES


def _is_abnormal(status: str) -> bool:
    return status == STATUS_STUCK


class ValveService:
    def __init__(self) -> None:
        # 种子数据来自统一示例表，状态相关字段在这里对齐一次，
        # 保证台账、详情、概览从同一个 status 口径读数据。
        for row in store.rows(MODULE):
            self._sync_row(row)

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        include_disabled: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("阀门编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 默认是待启闭清单：被停用的阀门不再出现；显式带上已停用或
        # include_disabled 时才把停用记录查出来。
        if not include_disabled and status != STATUS_DISABLED:
            rows = [row for row in rows if row.get("status") != STATUS_DISABLED]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def status_stats(self) -> dict[str, int]:
        """各状态计数与待启闭口径，台账页面卡片和运营概览共用这一份。"""
        counts = {status: 0 for status in STATUS_ORDER}
        for row in store.rows(MODULE):
            status = str(row.get("status") or STATUS_PENDING)
            counts[status] = counts.get(status, 0) + 1
        return {
            "total": sum(counts.values()),
            "pending": counts[STATUS_PENDING],
            "normal": counts[STATUS_NORMAL],
            "stuck": counts[STATUS_STUCK],
            "disabled": counts[STATUS_DISABLED],
            "worklist": counts[STATUS_PENDING] + counts[STATUS_STUCK],
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_PENDING
        entry["停用原因"] = ""
        entry["history"] = []
        self._sync_row(entry)
        rows.append(entry)
        self._append_history(entry, ACTION_SCHEDULE, STATUS_PENDING, STATUS_PENDING, note="阀门登记入册")
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """执行状态动作。失败时返回 (None, 原因)，记录保持原状态不动。"""
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"阀门 {entry_id} 不存在或已归档"
        if action not in ACTIONS:
            return None, f"动作「{action}」不属于阀门井室可执行范围"

        status = str(entry.get("status") or "")

        if status == STATUS_DISABLED:
            return None, "阀门已停用，不能再执行启闭操作"

        if action == ACTION_SCHEDULE:
            if status != STATUS_PENDING:
                return None, f"当前状态为「{status}」，安排启闭只能在「{STATUS_PENDING}」阶段执行，不能跳级"
            result = str(values.get("result") or "").strip()
            if result not in (RESULT_NORMAL, RESULT_STUCK):
                return None, "请说明本次启闭结果：操作正常或启闭卡涩"
            return self._change(entry, action, result, result)

        if action == ACTION_RECHECK:
            if status != STATUS_STUCK:
                return None, f"当前状态为「{status}」，卡涩复核只能在「{STATUS_STUCK}」阶段执行"
            result = str(values.get("result") or "").strip()
            if result not in RECHECK_RESULTS:
                return None, "请给出卡涩复核结论：复核通过或复核未通过"
            if result == RECHECK_PASS:
                return self._change(entry, action, STATUS_NORMAL, RECHECK_PASS)
            # 复核未通过：状态停留在启闭卡涩，绝不允许切回操作正常。
            self._append_history(entry, action, STATUS_STUCK, STATUS_STUCK, note=RECHECK_FAIL)
            return entry, "卡涩复核未通过，阀门保持「启闭卡涩」，请处理后重新复核"

        # action == ACTION_DISABLED
        reason = str(values.get("reason") or "").strip()
        if not reason:
            return None, "停用阀门前必须写清停用原因"
        self._change(entry, action, STATUS_DISABLED, reason, extra={"停用原因": reason})
        return entry, f"阀门已停用（原因：{reason}），不再出现在待启闭清单"

    def _change(
        self,
        entry: dict[str, Any],
        action: str,
        target: str,
        note: str,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        old_status = str(entry.get("status") or "")
        entry["status"] = target
        if extra:
            entry.update(extra)
        self._sync_row(entry)
        self._append_history(entry, action, old_status, target, note=note)
        return entry, f"阀门已{action}，状态更新为「{target}」"

    def _append_history(
        self,
        entry: dict[str, Any],
        action: str,
        old_status: str,
        new_status: str,
        *,
        note: str = "",
    ) -> None:
        entry.setdefault("history", []).append({
            "time": _now(),
            "action": action,
            "from": old_status,
            "to": new_status,
            "note": note,
        })

    def _sync_row(self, entry: dict[str, Any]) -> None:
        """以 status 为唯一口径同步派生字段与展示字段。"""
        status = str(entry.get("status") or STATUS_PENDING)
        if status not in STATUS_ORDER:
            status = STATUS_PENDING
            entry["status"] = status
        entry["pending"] = _is_pending(status)
        entry["abnormal"] = _is_abnormal(status)
        entry.setdefault("停用原因", "")
        entry.setdefault("history", [])
        # 台账列「阀门状态」与内部 status 保持一致，
        # 井室列表、阀门详情、概览看到的状态都来自这里。
        entry["阀门状态"] = status
