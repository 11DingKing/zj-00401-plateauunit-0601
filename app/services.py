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
    REINSPECTION_LABELS,
    TEAM_LABELS,
    GateStage,
    GateStatus,
    IssueSeverity,
    IssueStatus,
    ReinspectionConclusion,
    Team,
    stage_index,
)
from app.models import Gate, Issue, SpecialConfig, Unit
from app.schemas import (
    GateStatusUpdate,
    IssueAssign,
    IssueClose,
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


def _is_overdue(issue: Issue, now: Optional[datetime] = None) -> bool:
    """判断问题是否逾期：状态为 open 且 due_date < 当前时间。"""
    if issue.status != IssueStatus.open.value:
        return False
    if issue.due_date is None:
        return False
    ref = now or datetime.utcnow()
    return issue.due_date < ref


def _issue_to_out(issue: Issue, unit_code: str, now: Optional[datetime] = None) -> dict:
    stage_label = GATE_STAGE_LABELS.get(GateStage(issue.stage)) if issue.stage else None
    team_label = TEAM_LABELS.get(Team(issue.team)) if issue.team else None
    rc_label = (
        REINSPECTION_LABELS.get(ReinspectionConclusion(issue.reinspection_conclusion))
        if issue.reinspection_conclusion else None
    )
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
        "team": issue.team,
        "team_label": team_label,
        "due_date": issue.due_date,
        "overdue": _is_overdue(issue, now),
        "reinspection_conclusion": issue.reinspection_conclusion,
        "reinspection_conclusion_label": rc_label,
        "reinspection_remark": issue.reinspection_remark,
        "reinspected_at": issue.reinspected_at,
        "reinspected_by": issue.reinspected_by,
        "created_at": issue.created_at,
        "closed_at": issue.closed_at,
        "closed_by": issue.closed_by,
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


def _overdue_issue_count(unit: Unit, now: Optional[datetime] = None) -> int:
    return sum(1 for i in unit.issues if _is_overdue(i, now))


def _grid_blocked_by_overdue(unit: Unit, now: Optional[datetime] = None) -> bool:
    """机组是否因逾期未关闭问题而被拦截进入并网确认关卡。"""
    ref = now or datetime.utcnow()
    for issue in unit.issues:
        if _is_overdue(issue, ref):
            return True
    return False


def _missing_config_types(unit: Unit) -> list[str]:
    """机组尚未启用的专项配置类型（按枚举顺序），与统计覆盖率同口径。"""
    enabled = {c.config_type for c in unit.configs if c.enabled}
    return [ct.value for ct in ConfigType if ct.value not in enabled]


def _config_coverage_complete(unit: Unit) -> bool:
    """机组专项配置是否已补齐（全部启用）。"""
    return not _missing_config_types(unit)


def _open_issues_for_stage(unit: Unit, stage_value: str) -> list[Issue]:
    """机组在指定关卡上仍未关闭的问题。"""
    return [
        i
        for i in unit.issues
        if i.status == IssueStatus.open.value and i.stage == stage_value
    ]


# ---------------- 机组 ----------------
def list_units(db: Session) -> list[dict]:
    units = db.query(Unit).order_by(Unit.code).all()
    result = []
    now = datetime.utcnow()
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
                "config_coverage_complete": _config_coverage_complete(u),
                "missing_config_types": _missing_config_types(u),
                "open_issue_count": _open_issue_count(u),
                "overdue_issue_count": _overdue_issue_count(u, now),
                "grid_blocked_by_overdue": _grid_blocked_by_overdue(u, now),
            }
        )
    return result


def get_unit_detail(db: Session, unit_id: int) -> dict:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="机组不存在")
    cur = _current_stage(unit)
    now = datetime.utcnow()
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
        "issues": [_issue_to_out(i, unit.code, now) for i in unit.issues],
        "current_stage": cur.value if cur else None,
        "current_stage_label": GATE_STAGE_LABELS[cur] if cur else "已投运",
        "operational": _is_operational(unit),
        "config_coverage_complete": _config_coverage_complete(unit),
        "missing_config_types": _missing_config_types(unit),
        "overdue_issue_count": _overdue_issue_count(unit, now),
        "grid_blocked_by_overdue": _grid_blocked_by_overdue(unit, now),
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
        # 问题清单联动：该关卡存在未关闭问题时不允许通过
        open_stage_issues = _open_issues_for_stage(unit, stage.value)
        if open_stage_issues:
            titles = "、".join(f"「{i.title}」" for i in open_stage_issues[:5])
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"该关卡存在 {len(open_stage_issues)} 项未关闭问题（{titles}），"
                f"需先整改关闭并复验通过后方可通过「{GATE_STAGE_LABELS[stage]}」。",
            )
        # 专项配置覆盖率联动：进入带负荷试运行及之后阶段，必须补齐全部专项配置
        if idx >= stage_index(GateStage.no_load_debug):
            missing = _missing_config_types(unit)
            if missing:
                missing_labels = "、".join(
                    CONFIG_TYPE_LABELS[ConfigType(m)] for m in missing
                )
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"专项配置未补齐（缺少 {missing_labels}），"
                    f"不能通过「{GATE_STAGE_LABELS[stage]}」推进至后续阶段，"
                    f"请先补齐专项配置。",
                )
        # 并网确认关卡：拦截逾期未关闭问题
        if stage == GateStage.grid_connection:
            if _grid_blocked_by_overdue(unit, now):
                od_count = _overdue_issue_count(unit, now)
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"该机组存在 {od_count} 项逾期未关闭问题，"
                    f"需先整改关闭后方可进行并网确认。",
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
            # 支持同步分派班组与约定时限
            if payload.issue_team:
                try:
                    Team(payload.issue_team)
                except ValueError:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        detail=f"非法的责任班组: {payload.issue_team}",
                    )
                issue.team = payload.issue_team
            if payload.issue_due_date is not None:
                issue.due_date = payload.issue_due_date
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
        "config_coverage_complete": _config_coverage_complete(unit),
        "missing_config_types": _missing_config_types(unit),
        "grid_blocked_by_overdue": _grid_blocked_by_overdue(unit, now),
    }


# ---------------- 问题清单 ----------------
def list_issues(
    db: Session,
    status_filter: Optional[str] = None,
    unit_id: Optional[int] = None,
    stage: Optional[str] = None,
    team: Optional[str] = None,
    overdue: Optional[bool] = None,
) -> list[dict]:
    q = db.query(Issue, Unit.code).join(Unit, Issue.unit_id == Unit.id)
    if status_filter:
        q = q.filter(Issue.status == status_filter)
    if unit_id is not None:
        q = q.filter(Issue.unit_id == unit_id)
    if stage:
        q = q.filter(Issue.stage == stage)
    if team:
        q = q.filter(Issue.team == team)
    q = q.order_by(Issue.created_at.desc())
    now = datetime.utcnow()
    result = []
    for issue, code in q.all():
        issue_out = _issue_to_out(issue, code, now)
        if overdue is not None:
            if issue_out["overdue"] != overdue:
                continue
        result.append(issue_out)
    return result


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
    if payload.team:
        try:
            Team(payload.team)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"非法的责任班组: {payload.team}")
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
        team=payload.team,
        due_date=payload.due_date,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    now = datetime.utcnow()
    return _issue_to_out(issue, unit.code, now)


def assign_issue(db: Session, issue_id: int, payload: IssueAssign) -> dict:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="问题不存在")
    if issue.status == IssueStatus.closed.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="已关闭的问题不能再分派")
    if payload.team:
        try:
            Team(payload.team)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"非法的责任班组: {payload.team}")
        issue.team = payload.team
    if payload.due_date is not None:
        issue.due_date = payload.due_date
    db.commit()
    db.refresh(issue)
    unit = db.get(Unit, issue.unit_id)
    now = datetime.utcnow()
    return _issue_to_out(issue, unit.code if unit else "", now)


def close_issue(
    db: Session, issue_id: int, payload: IssueClose
) -> dict:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="问题不存在")
    if issue.status == IssueStatus.closed.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="该问题已关闭")
    now = datetime.utcnow()
    # 需要复验通过方可关闭：高严重 / 关联验收关卡 / 曾复验未通过
    requires_reinspection = (
        issue.severity == IssueSeverity.high.value
        or bool(issue.stage)
        or issue.reinspection_conclusion == ReinspectionConclusion.failed.value
    )
    # 复验结论校验
    if payload.reinspection_conclusion:
        try:
            rc = ReinspectionConclusion(payload.reinspection_conclusion)
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"非法的复验结论: {payload.reinspection_conclusion}",
            )
        if rc == ReinspectionConclusion.not_inspected:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="复验结论不能为「未复验」，请提供「复验通过」或「复验未通过」。",
            )
        issue.reinspection_conclusion = rc.value
        issue.reinspection_remark = payload.reinspection_remark
        issue.reinspected_at = now
        issue.reinspected_by = payload.reinspected_by
        # 复验未通过：落库记录复验事件，问题保持开启，阻止带病关闭
        if rc == ReinspectionConclusion.failed:
            db.commit()
            db.refresh(issue)
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="复验结论为「复验未通过」，已记录复验事件，问题保持开启。"
                "请继续整改后再次复验通过方可关闭。",
            )
        # rc == passed：允许关闭，继续执行关闭流程
    elif requires_reinspection:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="该问题为高严重或关联验收关卡，需复验通过后方可关闭。",
        )
    issue.status = IssueStatus.closed.value
    issue.closed_at = now
    issue.closed_by = payload.closed_by
    db.commit()
    db.refresh(issue)
    unit = db.get(Unit, issue.unit_id)
    return _issue_to_out(issue, unit.code if unit else "", now)


# ---------------- 统计 ----------------
def compute_stats(db: Session) -> dict:
    units = db.query(Unit).all()
    total = len(units)
    operational = [u for u in units if _is_operational(u)]
    first_batch_op = [u for u in operational if u.grid_batch == "首批"]

    durations = [d for d in (_commissioning_hours(u) for u in operational) if d is not None]
    avg_hours = round(sum(durations) / len(durations), 2) if durations else None

    now = datetime.utcnow()

    open_issues_rows = (
        db.query(Issue, Unit.code, Unit.slope_position)
        .join(Unit, Issue.unit_id == Unit.id)
        .filter(Issue.status == IssueStatus.open.value)
        .order_by(Issue.created_at.desc())
        .all()
    )
    open_issue_out = []
    for issue, code, _ in open_issues_rows:
        open_issue_out.append(_issue_to_out(issue, code, now))
    overdue_count = sum(1 for i in open_issue_out if i["overdue"])

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

    # 机组专项配置补齐口径：与关卡流转「进入带负荷试运行需补齐全部专项配置」同口径
    config_complete_units = [u for u in units if _config_coverage_complete(u)]
    config_complete_count = len(config_complete_units)
    config_incomplete_count = total - config_complete_count
    config_incomplete_units = [
        {
            "unit_id": u.id,
            "code": u.code,
            "name": u.name,
            "missing_config_types": _missing_config_types(u),
            "current_stage": (_current_stage(u).value if _current_stage(u) else None),
        }
        for u in units
        if not _config_coverage_complete(u)
    ]

    # --- 按专项配置拆分未关闭问题 ---
    # 构建 unit_id -> enabled config_types 的映射
    unit_configs_map: dict[int, list[str]] = {}
    for cfg in db.query(SpecialConfig).filter(SpecialConfig.enabled.is_(True)).all():
        unit_configs_map.setdefault(cfg.unit_id, []).append(cfg.config_type)

    by_config: dict[str, dict] = {ct.value: [] for ct in ConfigType}
    # 还增加 "无专项配置" 桶
    no_config_issues: list = []

    for issue, code, _ in open_issues_rows:
        issue_out = _issue_to_out(issue, code, now)
        cts = unit_configs_map.get(issue.unit_id, [])
        if not cts:
            no_config_issues.append(issue_out)
        else:
            for ct in cts:
                by_config.setdefault(ct, []).append(issue_out)

    unclosed_by_config: list[dict] = []
    for ct in ConfigType:
        issues = by_config.get(ct.value, [])
        od = sum(1 for i in issues if i["overdue"])
        unclosed_by_config.append(
            {
                "config_type": ct.value,
                "config_type_label": CONFIG_TYPE_LABELS[ct],
                "count": len(issues),
                "overdue_count": od,
                "issues": issues,
            }
        )
    if no_config_issues:
        od = sum(1 for i in no_config_issues if i["overdue"])
        unclosed_by_config.append(
            {
                "config_type": "none",
                "config_type_label": "无专项配置",
                "count": len(no_config_issues),
                "overdue_count": od,
                "issues": no_config_issues,
            }
        )

    # --- 按坡位拆分未关闭问题 ---
    by_slope: dict[str, list] = {}
    for issue, code, slope_position in open_issues_rows:
        issue_out = _issue_to_out(issue, code, now)
        key = slope_position or "未知坡位"
        by_slope.setdefault(key, []).append(issue_out)
    unclosed_by_slope = [
        {
            "slope_position": sp,
            "count": len(items),
            "overdue_count": sum(1 for i in items if i["overdue"]),
            "issues": items,
        }
        for sp, items in sorted(by_slope.items())
    ]

    # --- 按责任班组拆分未关闭问题 ---
    by_team: dict[Optional[str], list] = {}
    for issue, code, _ in open_issues_rows:
        issue_out = _issue_to_out(issue, code, now)
        key = issue.team  # None 代表未分派
        by_team.setdefault(key, []).append(issue_out)

    unclosed_by_team: list[dict] = []
    # 先按预设顺序输出各班组
    for tm in Team:
        issues = by_team.get(tm.value, [])
        od = sum(1 for i in issues if i["overdue"])
        unclosed_by_team.append(
            {
                "team": tm.value,
                "team_label": TEAM_LABELS[tm],
                "count": len(issues),
                "overdue_count": od,
                "issues": issues,
            }
        )
    # 未分派
    unassigned = by_team.get(None, [])
    # 同时收集非标准班组值（以防万一）
    other_keys = [k for k in by_team.keys() if k not in (tm.value for tm in Team) and k is not None]
    if unassigned:
        od = sum(1 for i in unassigned if i["overdue"])
        unclosed_by_team.append(
            {
                "team": None,
                "team_label": "未分派",
                "count": len(unassigned),
                "overdue_count": od,
                "issues": unassigned,
            }
        )
    for k in other_keys:
        issues = by_team[k]
        od = sum(1 for i in issues if i["overdue"])
        unclosed_by_team.append(
            {
                "team": k,
                "team_label": k,
                "count": len(issues),
                "overdue_count": od,
                "issues": issues,
            }
        )

    return {
        "total_units": total,
        "operational_count": len(operational),
        "first_batch_operational_count": len(first_batch_op),
        "average_debug_hours": avg_hours,
        "average_debug_hours_display": _hours_display(avg_hours),
        "unclosed_issue_count": len(open_issue_out),
        "overdue_unclosed_count": overdue_count,
        "unclosed_issues": open_issue_out,
        "config_coverage": coverage,
        "config_complete_count": config_complete_count,
        "config_incomplete_count": config_incomplete_count,
        "config_incomplete_units": config_incomplete_units,
        "unclosed_by_config": unclosed_by_config,
        "unclosed_by_slope": unclosed_by_slope,
        "unclosed_by_team": unclosed_by_team,
    }


# ---------------- 坡位适配复盘 ----------------
def _unit_summary_for_review(unit: Unit, now: datetime) -> dict:
    """生成复盘用的机组摘要，与 list_units 逻辑一致。"""
    cur = _current_stage(unit)
    return {
        "id": unit.id,
        "code": unit.code,
        "name": unit.name,
        "rated_capacity_mw": unit.rated_capacity_mw,
        "altitude_m": unit.altitude_m,
        "slope_position": unit.slope_position,
        "grid_batch": unit.grid_batch,
        "current_stage": cur.value if cur else None,
        "current_stage_label": GATE_STAGE_LABELS[cur] if cur else "已投运",
        "operational": _is_operational(unit),
        "enabled_config_types": _enabled_config_types(unit),
        "config_coverage_complete": _config_coverage_complete(unit),
        "missing_config_types": _missing_config_types(unit),
        "open_issue_count": _open_issue_count(unit),
        "overdue_issue_count": _overdue_issue_count(unit, now),
        "grid_blocked_by_overdue": _grid_blocked_by_overdue(unit, now),
    }


def _stage_pass_rate_for_units(units: list[Unit], stage: GateStage) -> float:
    """计算一批机组在指定关卡的通过率。"""
    total = len(units)
    if total == 0:
        return 0.0
    passed = sum(
        1 for u in units
        if _gate_by_stage(u, stage) and _gate_by_stage(u, stage).status == GateStatus.passed.value
    )
    return round(passed / total, 4)


def _compute_risk_score(
    acceptance_rate: float,
    avg_rework: float,
    avg_debug_hours: Optional[float],
    unit_count: int,
) -> float:
    """
    计算拖慢投运风险评分（0~100）。
    维度：验收通过率权重40%、返工次数权重30%、调试耗时权重30%。
    通过率越低、返工越多、耗时越长 → 风险越高。
    """
    score = 0.0
    score += (1 - acceptance_rate) * 40
    rework_factor = min(avg_rework / 5.0, 1.0)
    score += rework_factor * 30
    if avg_debug_hours is not None:
        hours_factor = min(avg_debug_hours / 720.0, 1.0)
        score += hours_factor * 30
    else:
        score += 30
    return round(score, 2)


def _risk_level(score: float) -> str:
    if score < 30:
        return "低"
    elif score < 60:
        return "中"
    else:
        return "高"


def _analyze_config_group(
    config_type: Optional[str],
    units: list[Unit],
    now: datetime,
) -> dict:
    """分析某坡位下某配置类型的机组群指标。"""
    unit_count = len(units)
    if unit_count == 0:
        return None

    operational_units = [u for u in units if _is_operational(u)]
    operational_count = len(operational_units)
    acceptance_rate = round(operational_count / unit_count, 4) if unit_count else 0.0

    rework_count = sum(len(u.issues) for u in units)
    avg_rework = round(rework_count / unit_count, 2) if unit_count else 0.0

    durations = [d for d in (_commissioning_hours(u) for u in operational_units) if d is not None]
    avg_debug_hours = round(sum(durations) / len(durations), 2) if durations else None

    stage_pass_rates = {}
    for stage in GATE_ORDER:
        stage_pass_rates[stage.value] = _stage_pass_rate_for_units(units, stage)

    ct = ConfigType(config_type) if config_type else None
    return {
        "config_type": config_type if config_type else "none",
        "config_type_label": CONFIG_TYPE_LABELS[ct] if ct else "无专项配置",
        "unit_count": unit_count,
        "operational_count": operational_count,
        "acceptance_rate": acceptance_rate,
        "acceptance_rate_pct": round(acceptance_rate * 100, 2),
        "rework_count": rework_count,
        "avg_rework_per_unit": avg_rework,
        "avg_debug_hours": avg_debug_hours,
        "avg_debug_hours_display": _hours_display(avg_debug_hours),
        "stage_pass_rates": stage_pass_rates,
    }


def compute_slope_review(db: Session) -> dict:
    """
    坡位适配复盘：按坡位归组，对比各专项配置的验收通过率、返工次数、平均调试耗时。
    串联机组档案、验收记录、专项配置，输出风险评分帮助判断哪类坡位最易拖慢投运。
    """
    now = datetime.utcnow()
    units = db.query(Unit).order_by(Unit.code).all()
    total_units = len(units)

    units_by_slope: dict[str, list[Unit]] = {}
    for u in units:
        key = u.slope_position or "未知坡位"
        units_by_slope.setdefault(key, []).append(u)

    slope_reviews = []
    for slope_position, slope_units in units_by_slope.items():
        slope_unit_count = len(slope_units)
        slope_operational = [u for u in slope_units if _is_operational(u)]
        slope_operational_count = len(slope_operational)
        slope_acceptance_rate = round(slope_operational_count / slope_unit_count, 4) if slope_unit_count else 0.0
        slope_total_rework = sum(len(u.issues) for u in slope_units)
        slope_avg_rework = round(slope_total_rework / slope_unit_count, 2) if slope_unit_count else 0.0

        slope_durations = [d for d in (_commissioning_hours(u) for u in slope_operational) if d is not None]
        slope_avg_debug = round(sum(slope_durations) / len(slope_durations), 2) if slope_durations else None

        unit_config_map: dict[Optional[str], list[Unit]] = {}
        for u in slope_units:
            enabled_configs = _enabled_config_types(u)
            if not enabled_configs:
                unit_config_map.setdefault(None, []).append(u)
            else:
                for ct in enabled_configs:
                    unit_config_map.setdefault(ct, []).append(u)

        by_config = []
        for ct in ConfigType:
            group = unit_config_map.get(ct.value, [])
            analysis = _analyze_config_group(ct.value, group, now)
            if analysis:
                by_config.append(analysis)

        none_group = unit_config_map.get(None, [])
        none_analysis = _analyze_config_group(None, none_group, now)
        if none_analysis:
            by_config.append(none_analysis)

        risk_score = _compute_risk_score(
            slope_acceptance_rate,
            slope_avg_rework,
            slope_avg_debug,
            slope_unit_count,
        )

        slope_reviews.append({
            "slope_position": slope_position,
            "unit_count": slope_unit_count,
            "operational_count": slope_operational_count,
            "overall_acceptance_rate": slope_acceptance_rate,
            "overall_acceptance_rate_pct": round(slope_acceptance_rate * 100, 2),
            "total_rework_count": slope_total_rework,
            "avg_rework_per_unit": slope_avg_rework,
            "overall_avg_debug_hours": slope_avg_debug,
            "overall_avg_debug_hours_display": _hours_display(slope_avg_debug),
            "by_config": by_config,
            "risk_score": risk_score,
            "risk_level": _risk_level(risk_score),
            "unit_codes": [u.code for u in slope_units],
            "unit_summaries": [_unit_summary_for_review(u, now) for u in slope_units],
        })

    slope_reviews.sort(key=lambda x: x["risk_score"], reverse=True)

    config_legend = [
        {"value": ct.value, "label": CONFIG_TYPE_LABELS[ct]}
        for ct in ConfigType
    ]
    config_legend.append({"value": "none", "label": "无专项配置"})

    stage_legend = [
        {"value": stage.value, "label": GATE_STAGE_LABELS[stage], "index": stage_index(stage)}
        for stage in GATE_ORDER
    ]

    return {
        "total_units": total_units,
        "slope_count": len(units_by_slope),
        "slope_reviews": slope_reviews,
        "config_type_legend": config_legend,
        "stage_legend": stage_legend,
    }
