"""业务逻辑层：机组建档、专项配置、验收关卡流转、问题清单与统计。"""

import math
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.enums import (
    CONFIG_TYPE_LABELS,
    ConfigType,
    GATE_ORDER,
    GATE_STAGE_LABELS,
    GATE_STATUS_LABELS,
    ISSUE_SEVERITY_LABELS,
    GateStage,
    GateStatus,
    IssueSeverity,
    IssueStatus,
    stage_index,
)
from app.models import Gate, Issue, SpecialConfig, Unit
from app.schemas import (
    GateStatusUpdate,
    IssueCreate,
    SpecialConfigUpsert,
    UnitCreate,
    UnitUpdate,
)


# ---------------- 工具函数 ----------------
def _compute_swept_area(rotor_diameter_m: float) -> float:
    radius = rotor_diameter_m / 2.0
    return round(math.pi * radius * radius, 2)


def _gate_by_stage(unit: Unit, stage: GateStage) -> Optional[Gate]:
    for g in unit.gates:
        if g.stage == stage.value:
            return g
    return None


def _is_operational(unit: Unit) -> bool:
    g = _gate_by_stage(unit, GateStage.grid_connection)
    return bool(g and g.status == GateStatus.passed.value)


def _current_stage(unit: Unit) -> Optional[GateStage]:
    """当前应执行的关卡：第一个非 passed 的关卡；全部通过则返回 None。"""
    for stage in GATE_ORDER:
        g = _gate_by_stage(unit, stage)
        if g is None or g.status != GateStatus.passed.value:
            return stage
    return None


def _commissioning_hours(unit: Unit) -> Optional[float]:
    """投运调试全程耗时(小时)：基础验收启动 → 并网确认完成。仅对已投运机组有效。"""
    if not _is_operational(unit):
        return None
    foundation = _gate_by_stage(unit, GateStage.foundation)
    grid = _gate_by_stage(unit, GateStage.grid_connection)
    if not foundation or not grid or not foundation.started_at or not grid.completed_at:
        return None
    delta = grid.completed_at - foundation.started_at
    return round(delta.total_seconds() / 3600.0, 2)


def _hours_display(hours: Optional[float]) -> Optional[str]:
    if hours is None:
        return None
    days = int(hours // 24)
    rem = hours - days * 24
    if days > 0:
        return f"{days}天 {round(rem, 1)}小时"
    return f"{round(rem, 1)}小时"


def _issue_to_out(issue: Issue, unit_code: str) -> dict:
    stage_label = GATE_STAGE_LABELS.get(GateStage(issue.stage)) if issue.stage else None
    return {
        "id": issue.id,
        "unit_id": issue.unit_id,
        "unit_code": unit_code,
        "stage": issue.stage,
        "stage_label": stage_label,
        "title": issue.title,
        "description": issue.description,
        "severity": issue.severity,
        "severity_label": ISSUE_SEVERITY_LABELS.get(IssueSeverity(issue.severity), issue.severity),
        "status": issue.status,
        "created_at": issue.created_at,
        "closed_at": issue.closed_at,
    }


def _config_to_out(cfg: SpecialConfig) -> dict:
    ct = ConfigType(cfg.config_type)
    return {
        "id": cfg.id,
        "config_type": cfg.config_type,
        "config_type_label": CONFIG_TYPE_LABELS[ct],
        "enabled": cfg.enabled,
        "params": cfg.params or {},
        "notes": cfg.notes,
        "created_at": cfg.created_at,
        "updated_at": cfg.updated_at,
    }


def _gate_to_out(g: Gate) -> dict:
    st = GateStage(g.stage)
    return {
        "id": g.id,
        "stage": g.stage,
        "stage_index": g.stage_index,
        "stage_label": GATE_STAGE_LABELS[st],
        "status": g.status,
        "status_label": GATE_STATUS_LABELS.get(GateStatus(g.status), g.status),
        "operator": g.operator,
        "remarks": g.remarks,
        "started_at": g.started_at,
        "completed_at": g.completed_at,
    }


def _enabled_config_types(unit: Unit) -> list[str]:
    return sorted(
        {
            c.config_type
            for c in unit.configs
            if c.enabled
        }
    )


def _open_issue_count(unit: Unit) -> int:
    return sum(1 for i in unit.issues if i.status == IssueStatus.open.value)


# ---------------- 机组 ----------------
def list_units(db: Session) -> list[dict]:
    units = db.query(Unit).order_by(Unit.code).all()
    result = []
    for u in units:
        cur = _current_stage(u)
        result.append(
            {
                "id": u.id,
                "code": u.code,
                "name": u.name,
                "rated_capacity_mw": u.rated_capacity_mw,
                "altitude_m": u.altitude_m,
                "slope_position": u.slope_position,
                "grid_batch": u.grid_batch,
                "current_stage": cur.value if cur else None,
                "current_stage_label": GATE_STAGE_LABELS[cur] if cur else "已投运",
                "operational": _is_operational(u),
                "enabled_config_types": _enabled_config_types(u),
                "open_issue_count": _open_issue_count(u),
            }
        )
    return result


def get_unit_detail(db: Session, unit_id: int) -> dict:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="机组不存在")
    cur = _current_stage(unit)
    return {
        "id": unit.id,
        "code": unit.code,
        "name": unit.name,
        "rated_capacity_mw": unit.rated_capacity_mw,
        "altitude_m": unit.altitude_m,
        "tower_height_m": unit.tower_height_m,
        "rotor_diameter_m": unit.rotor_diameter_m,
        "swept_area_m2": unit.swept_area_m2,
        "slope_position": unit.slope_position,
        "slope_aspect": unit.slope_aspect,
        "slope_degree": unit.slope_degree,
        "grid_batch": unit.grid_batch,
        "custom_params": unit.custom_params or {},
        "created_at": unit.created_at,
        "updated_at": unit.updated_at,
        "configs": [_config_to_out(c) for c in unit.configs],
        "gates": [_gate_to_out(g) for g in unit.gates],
        "issues": [_issue_to_out(i, unit.code) for i in unit.issues],
        "current_stage": cur.value if cur else None,
        "current_stage_label": GATE_STAGE_LABELS[cur] if cur else "已投运",
        "operational": _is_operational(unit),
    }


def create_unit(db: Session, payload: UnitCreate) -> dict:
    if db.query(Unit).filter(Unit.code == payload.code).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"机组编号 {payload.code} 已存在")
    swept = payload.swept_area_m2
    if swept is None or swept <= 0:
        swept = _compute_swept_area(payload.rotor_diameter_m)
    unit = Unit(
        code=payload.code,
        name=payload.name,
        rated_capacity_mw=payload.rated_capacity_mw,
        altitude_m=payload.altitude_m,
        tower_height_m=payload.tower_height_m,
        rotor_diameter_m=payload.rotor_diameter_m,
        swept_area_m2=swept,
        slope_position=payload.slope_position,
        slope_aspect=payload.slope_aspect,
        slope_degree=payload.slope_degree,
        grid_batch=payload.grid_batch,
        custom_params=payload.custom_params or {},
    )
    # 初始化全部验收关卡为待执行
    for idx, stage in enumerate(GATE_ORDER):
        unit.gates.append(
            Gate(
                stage=stage.value,
                stage_index=idx,
                status=GateStatus.pending.value,
            )
        )
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return get_unit_detail(db, unit.id)


def update_unit(db: Session, unit_id: int, payload: UnitUpdate) -> dict:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="机组不存在")
    data = payload.model_dump(exclude_unset=True)
    if "rotor_diameter_m" in data and data["rotor_diameter_m"] is not None:
        # 塔架/叶轮变更后，若未显式指定扫风面积，则重算
        if "swept_area_m2" not in data or data.get("swept_area_m2") in (None, 0):
            data["swept_area_m2"] = _compute_swept_area(data["rotor_diameter_m"])
    for k, v in data.items():
        setattr(unit, k, v)
    db.commit()
    db.refresh(unit)
    return get_unit_detail(db, unit.id)


def delete_unit(db: Session, unit_id: int) -> None:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="机组不存在")
    db.delete(unit)
    db.commit()


# ---------------- 专项配置 ----------------
def list_configs(db: Session, unit_id: int) -> list[dict]:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="机组不存在")
    return [_config_to_out(c) for c in unit.configs]


def upsert_config(db: Session, unit_id: int, payload: SpecialConfigUpsert) -> dict:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="机组不存在")
    try:
        ct = ConfigType(payload.config_type)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"非法的专项配置类型: {payload.config_type}",
        )
    cfg = (
        db.query(SpecialConfig)
        .filter(SpecialConfig.unit_id == unit_id, SpecialConfig.config_type == ct.value)
        .first()
    )
    if cfg is None:
        cfg = SpecialConfig(
            unit_id=unit_id,
            config_type=ct.value,
            enabled=payload.enabled,
            params=payload.params or {},
            notes=payload.notes,
        )
        db.add(cfg)
    else:
        cfg.enabled = payload.enabled
        cfg.params = payload.params or {}
        cfg.notes = payload.notes
    db.commit()
    db.refresh(cfg)
    return _config_to_out(cfg)


def delete_config(db: Session, unit_id: int, config_id: int) -> None:
    cfg = db.get(SpecialConfig, config_id)
    if cfg is None or cfg.unit_id != unit_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="专项配置不存在")
    db.delete(cfg)
    db.commit()


# ---------------- 验收关卡 ----------------
def list_gates(db: Session, unit_id: int) -> list[dict]:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="机组不存在")
    return [_gate_to_out(g) for g in unit.gates]


def update_gate_status(
    db: Session, unit_id: int, stage_value: str, payload: GateStatusUpdate
) -> dict:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="机组不存在")
    try:
        stage = GateStage(stage_value)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"非法的关卡: {stage_value}")
    try:
        new_status = GateStatus(payload.status)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"非法的目标状态: {payload.status}")

    target = _gate_by_stage(unit, stage)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="该关卡不存在")

    ordered = sorted(unit.gates, key=lambda g: g.stage_index)
    idx = stage_index(stage)

    now = datetime.utcnow()

    if new_status == GateStatus.passed:
        # 关卡顺序强制：上一关必须已通过
        if idx > 0:
            prev = ordered[idx - 1]
            if prev.status != GateStatus.passed.value:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"上一关「{GATE_STAGE_LABELS[GATE_ORDER[idx - 1]]}」尚未通过，"
                    f"不能进入「{GATE_STAGE_LABELS[stage]}」",
                )
        if target.started_at is None:
            target.started_at = now
        target.status = GateStatus.passed.value
        target.completed_at = now
        target.operator = payload.operator or target.operator
        target.remarks = payload.remarks or target.remarks

    elif new_status == GateStatus.failed:
        # 登记失败，并把后续关卡回退为待执行，保证不变式：失败关卡之后的关卡不可先行
        if target.started_at is None:
            target.started_at = now
        target.status = GateStatus.failed.value
        target.completed_at = now
        target.operator = payload.operator or target.operator
        target.remarks = payload.remarks or target.remarks
        for later in ordered[idx + 1:]:
            later.status = GateStatus.pending.value
            later.completed_at = None
            later.operator = None
            later.remarks = None
        # 可选：同时登记一条问题
        if payload.issue_title:
            issue = Issue(
                unit_id=unit_id,
                stage=stage.value,
                title=payload.issue_title,
                description=payload.issue_description,
                severity=IssueSeverity(payload.issue_severity or "medium").value,
                status=IssueStatus.open.value,
            )
            db.add(issue)

    elif new_status == GateStatus.pending:
        # 重置该关卡及后续
        for g in ordered[idx:]:
            g.status = GateStatus.pending.value
            g.completed_at = None
            g.started_at = None
            g.operator = None
            g.remarks = None

    db.commit()
    db.refresh(unit)
    return {
        "unit_id": unit_id,
        "stage": stage.value,
        "stage_label": GATE_STAGE_LABELS[stage],
        "gates": [_gate_to_out(g) for g in unit.gates],
        "operational": _is_operational(unit),
    }


# ---------------- 问题清单 ----------------
def list_issues(
    db: Session,
    status_filter: Optional[str] = None,
    unit_id: Optional[int] = None,
    stage: Optional[str] = None,
) -> list[dict]:
    q = db.query(Issue, Unit.code).join(Unit, Issue.unit_id == Unit.id)
    if status_filter:
        q = q.filter(Issue.status == status_filter)
    if unit_id is not None:
        q = q.filter(Issue.unit_id == unit_id)
    if stage:
        q = q.filter(Issue.stage == stage)
    q = q.order_by(Issue.created_at.desc())
    return [_issue_to_out(i, code) for i, code in q.all()]


def create_issue(db: Session, payload: IssueCreate) -> dict:
    if payload.stage:
        try:
            GateStage(payload.stage)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"非法的关卡: {payload.stage}")
    try:
        sev = IssueSeverity(payload.severity)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"非法的严重程度: {payload.severity}")
    unit = db.get(Unit, payload.unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="机组不存在")
    issue = Issue(
        unit_id=payload.unit_id,
        stage=payload.stage,
        title=payload.title,
        description=payload.description,
        severity=sev.value,
        status=IssueStatus.open.value,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return _issue_to_out(issue, unit.code)


def close_issue(db: Session, issue_id: int, closed_by: Optional[str]) -> dict:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="问题不存在")
    if issue.status == IssueStatus.closed.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="该问题已关闭")
    issue.status = IssueStatus.closed.value
    issue.closed_at = datetime.utcnow()
    issue.closed_by = closed_by
    db.commit()
    db.refresh(issue)
    unit = db.get(Unit, issue.unit_id)
    return _issue_to_out(issue, unit.code if unit else "")


# ---------------- 统计 ----------------
def compute_stats(db: Session) -> dict:
    units = db.query(Unit).all()
    total = len(units)
    operational = [u for u in units if _is_operational(u)]
    first_batch_op = [u for u in operational if u.grid_batch == "首批"]

    durations = [d for d in (_commissioning_hours(u) for u in operational) if d is not None]
    avg_hours = round(sum(durations) / len(durations), 2) if durations else None

    open_issues = (
        db.query(Issue, Unit.code)
        .join(Unit, Issue.unit_id == Unit.id)
        .filter(Issue.status == IssueStatus.open.value)
        .order_by(Issue.created_at.desc())
        .all()
    )
    open_issue_out = [_issue_to_out(i, code) for i, code in open_issues]

    coverage = []
    for ct in ConfigType:
        enabled_count = (
            db.query(SpecialConfig)
            .filter(SpecialConfig.config_type == ct.value, SpecialConfig.enabled.is_(True))
            .count()
        )
        ratio = (enabled_count / total) if total else 0.0
        coverage.append(
            {
                "config_type": ct.value,
                "config_type_label": CONFIG_TYPE_LABELS[ct],
                "enabled_count": enabled_count,
                "total_units": total,
                "coverage": round(ratio, 4),
                "coverage_pct": round(ratio * 100, 2),
            }
        )

    return {
        "total_units": total,
        "operational_count": len(operational),
        "first_batch_operational_count": len(first_batch_op),
        "average_debug_hours": avg_hours,
        "average_debug_hours_display": _hours_display(avg_hours),
        "unclosed_issue_count": len(open_issue_out),
        "unclosed_issues": open_issue_out,
        "config_coverage": coverage,
    }
