"""阀门井室业务规则：状态流转、字段校验与筛选口径都收在这里。

状态只能顺着「安排启闭 → 操作正常/启闭卡涩 → 卡涩复核 → 停用」依次推进：

- 待启闭：确认正常 / 确认卡涩 / 停用阀门
- 操作正常：安排启闭（进入下一轮启闭）/ 停用阀门
- 启闭卡涩：卡涩复核（通过才允许回到操作正常）/ 停用阀门
- 已停用：终态，不再接受任何动作

任何校验失败都只返回原因、不改动数据；每次状态变化都会追加一条历史记录，
历史记录只增不改，按当时的口径留痕。
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
STATUS_RETIRED = "已停用"
STATUS_ORDER = [STATUS_PENDING, STATUS_NORMAL, STATUS_STUCK, STATUS_RETIRED]

ACTION_SCHEDULE = "安排启闭"
ACTION_CONFIRM_NORMAL = "确认正常"
ACTION_CONFIRM_STUCK = "确认卡涩"
ACTION_REVIEW = "卡涩复核"
ACTION_RETIRE = "停用阀门"

# 每个动作允许的前置状态：不在列出的状态上执行就是跳级或回退，一律拦下
ACTION_SOURCES = {
    ACTION_SCHEDULE: [STATUS_NORMAL],
    ACTION_CONFIRM_NORMAL: [STATUS_PENDING],
    ACTION_CONFIRM_STUCK: [STATUS_PENDING],
    ACTION_REVIEW: [STATUS_STUCK],
    ACTION_RETIRE: [STATUS_PENDING, STATUS_NORMAL, STATUS_STUCK],
}

# 无需额外结论的动作：动作 → 目标状态
ACTION_TARGETS = {
    ACTION_SCHEDULE: STATUS_PENDING,
    ACTION_CONFIRM_NORMAL: STATUS_NORMAL,
    ACTION_CONFIRM_STUCK: STATUS_STUCK,
}

REVIEW_PASS = "通过"
REVIEW_FAIL = "不通过"
REVIEW_RESULTS = [REVIEW_PASS, REVIEW_FAIL]


class ValveService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("阀门编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._with_ledger(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._with_ledger(entry)

    def summary(self) -> dict[str, Any]:
        """按状态汇总阀门台账：列表、详情与概览共用这一份口径。"""
        rows = store.rows(MODULE)
        by_status = {status: 0 for status in STATUS_ORDER}
        for row in rows:
            status = str(row.get("status") or "")
            if status in by_status:
                by_status[status] += 1
        return {
            "total": len(rows),
            "by_status": by_status,
            "pending": by_status[STATUS_PENDING],
            "abnormal": by_status[STATUS_STUCK],
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field)).strip() for field in REQUIRED_FIELDS})
        for field in ("公称直径", "操作方向", "上次启闭日", "责任人员"):
            text = str(values.get(field) or "").strip()
            if text:
                entry[field] = text
        entry["status"] = STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = False
        entry["history"] = []
        self._record(entry, "登记阀门", "—", STATUS_PENDING, "新登记，纳入待启闭清单")
        rows.append(entry)
        return self._with_ledger(entry), []

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        reason: str = "",
        result: str = "",
        note: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"阀门 {entry_id} 不存在或已归档"
        if action not in ACTION_SOURCES:
            return None, f"动作「{action}」不属于阀门井室可执行范围"
        current = str(entry.get("status") or "")
        if current == STATUS_RETIRED:
            return None, f"阀门已停用，不能再执行「{action}」"
        if current not in ACTION_SOURCES[action]:
            allowed = "、".join(ACTION_SOURCES[action])
            return None, f"「{action}」只能在「{allowed}」状态下执行，当前状态为「{current}」，不允许跳级或回退"
        if action == ACTION_RETIRE:
            reason = reason.strip()
            if not reason:
                return None, "停用阀门前必须写清停用原因"
            return self._transition(entry, action, STATUS_RETIRED, reason)
        if action == ACTION_REVIEW:
            if result not in REVIEW_RESULTS:
                return None, "卡涩复核必须给出「通过」或「不通过」的结论"
            note = note.strip() or f"复核{result}"
            if result == REVIEW_FAIL:
                # 复核不通过：状态保持启闭卡涩，只留复核记录，不许跳到操作正常
                self._record(entry, action, current, current, note)
                return self._with_ledger(entry), f"卡涩复核不通过，阀门保持「{STATUS_STUCK}」，待再次复核"
            return self._transition(entry, action, STATUS_NORMAL, note)
        return self._transition(entry, action, ACTION_TARGETS[action], note.strip())

    def _transition(
        self,
        entry: dict[str, Any],
        action: str,
        target: str,
        note: str,
    ) -> tuple[dict[str, Any], str]:
        before = str(entry.get("status") or "")
        entry["status"] = target
        # 待启闭清单只收「待启闭」；异常量只算「启闭卡涩」；已停用退出流程
        entry["pending"] = target == STATUS_PENDING
        entry["abnormal"] = target == STATUS_STUCK
        self._record(entry, action, before, target, note)
        return self._with_ledger(entry), f"阀门已{action}：{before} → {target}"

    def _record(self, entry: dict[str, Any], action: str, before: str, after: str, note: str) -> None:
        """追加一条状态变更记录：只增不改，历史按当时的口径保留。"""
        history = entry.setdefault("history", [])
        history.append({
            "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "动作": action,
            "变更前": before,
            "变更后": after,
            "说明": note,
        })

    def _with_ledger(self, row: dict[str, Any]) -> dict[str, Any]:
        """台账上的「阀门状态」始终与当前状态同源，列表、详情、概览看到的一致。"""
        row["阀门状态"] = str(row.get("status") or STATUS_PENDING)
        return row
