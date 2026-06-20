"""示例数据：不同坡位的 11.1MW 机组，覆盖不同投运进度。"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.enums import ConfigType, GateStage, GateStatus, IssueSeverity, IssueStatus, stage_index
from app.models import Gate, Issue, SpecialConfig, Unit


def _gate(
    stage: GateStage,
    status: GateStatus,
    *,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
    operator: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Gate:
    return Gate(
        stage=stage.value,
        stage_index=stage_index(stage),
        status=status.value,
        started_at=started_at,
        completed_at=completed_at,
        operator=operator,
        remarks=remarks,
    )


# 各专项配置的典型参数
CONFIG_PARAMS = {
    ConfigType.low_air_density: {
        "空气密度_kg_m3": 0.88,
        "功率曲线标定": "高原型低密度",
        "叶片加长": True,
        "发电机冷却强化": True,
    },
    ConfigType.strong_wind_turbulence: {
        "湍流强度等级": "C",
        "偏航控制": "主动寻风",
        "独立变桨": True,
        "极端阵风缓冲": True,
    },
    ConfigType.nacelle_temp_control: {
        "设计温区_℃": [-30, 45],
        "冷却方式": "液冷+风冷",
        "加热功率_kW": 15,
        "低温自启动": True,
    },
    ConfigType.blade_aero_optimization: {
        "翼型": "高原专用翼型",
        "前缘防蚀": "气溶胶涂层",
        "叶尖小翼": True,
        "气动粗化修正": True,
    },
}


def _config(unit_id: int, ct: ConfigType, enabled: bool = True) -> SpecialConfig:
    return SpecialConfig(
        unit_id=unit_id,
        config_type=ct.value,
        enabled=enabled,
        params=CONFIG_PARAMS[ct],
        notes=None,
    )


def _build_unit(spec: dict, db: Session) -> Unit:
    unit = Unit(
        code=spec["code"],
        name=spec["name"],
        rated_capacity_mw=spec.get("rated_capacity_mw", 11.1),
        altitude_m=spec["altitude_m"],
        tower_height_m=spec["tower_height_m"],
        rotor_diameter_m=spec["rotor_diameter_m"],
        swept_area_m2=spec["swept_area_m2"],
        slope_position=spec["slope_position"],
        slope_aspect=spec.get("slope_aspect"),
        slope_degree=spec.get("slope_degree"),
        grid_batch=spec["grid_batch"],
        custom_params=spec.get("custom_params", {}),
    )
    db.add(unit)
    db.flush()  # 取得 unit.id

    for ct in spec.get("configs", []):
        unit.configs.append(_config(unit.id, ct))
    # 显式登记“未启用”的专项配置，便于覆盖率统计与档案完整
    for ct in ConfigType:
        if ct not in spec.get("configs", []):
            unit.configs.append(SpecialConfig(
                unit_id=unit.id, config_type=ct.value, enabled=False, params={}
            ))

    for g in spec["gates"]:
        g.unit_id = unit.id
        unit.gates.append(g)

    for issue_spec in spec.get("issues", []):
        unit.issues.append(Issue(
            unit_id=unit.id,
            stage=issue_spec.get("stage"),
            title=issue_spec["title"],
            description=issue_spec.get("description"),
            severity=issue_spec.get("severity", IssueSeverity.medium).value,
            status=issue_spec.get("status", IssueStatus.open).value,
            created_at=issue_spec.get("created_at", datetime(2026, 3, 1)),
            closed_at=issue_spec.get("closed_at"),
        ))

    return unit


def seed_if_empty(db: Session) -> None:
    if db.query(Unit).count() > 0:
        return

    P = GateStatus.passed
    F = GateStatus.failed
    ND = GateStatus.pending  # no data / 待执行

    D = datetime  # 别名

    units_spec = [
        {
            "code": "JLL-01",
            "name": "巨龙梁1号机",
            "altitude_m": 3205,
            "tower_height_m": 120,
            "rotor_diameter_m": 220,
            "swept_area_m2": 38013.27,
            "slope_position": "东坡上段",
            "slope_aspect": "东坡",
            "slope_degree": 18.0,
            "grid_batch": "首批",
            "custom_params": {
                "轮毂高度_m": 120,
                "发电机型号": "DD110-11.1MW",
                "叶片长度_m": 107,
                "控制策略": "高海拔低密度优化",
                "抗震设防烈度": 7,
            },
            "configs": [
                ConfigType.low_air_density,
                ConfigType.strong_wind_turbulence,
                ConfigType.nacelle_temp_control,
                ConfigType.blade_aero_optimization,
            ],
            "gates": [
                _gate(GateStage.foundation, P, started_at=D(2026, 2, 10), completed_at=D(2026, 2, 12), operator="王建国", remarks="基础沉降稳定"),
                _gate(GateStage.hoisting, P, started_at=D(2026, 2, 13), completed_at=D(2026, 2, 19), operator="李志强", remarks="塔筒吊装到位"),
                _gate(GateStage.no_load_debug, P, started_at=D(2026, 2, 20), completed_at=D(2026, 2, 26), operator="陈敏", remarks="空载参数合格"),
                _gate(GateStage.load_test_run, P, started_at=D(2026, 2, 27), completed_at=D(2026, 3, 3), operator="陈敏", remarks="满负荷振动正常"),
                _gate(GateStage.grid_connection, P, started_at=D(2026, 3, 4), completed_at=D(2026, 3, 5), operator="赵伟", remarks="并网确认通过"),
            ],
            "issues": [
                {
                    "stage": GateStage.grid_connection.value,
                    "title": "并网前控制柜端子松动",
                    "description": "巡检发现部分端子螺栓力矩不足，已复紧复测",
                    "severity": IssueSeverity.medium,
                    "status": IssueStatus.closed,
                    "created_at": D(2026, 3, 4),
                    "closed_at": D(2026, 3, 5),
                },
            ],
        },
        {
            "code": "JLL-02",
            "name": "巨龙梁2号机",
            "altitude_m": 3340,
            "tower_height_m": 130,
            "rotor_diameter_m": 226,
            "swept_area_m2": 40114.95,
            "slope_position": "北脊中段",
            "slope_aspect": "北坡",
            "slope_degree": 22.0,
            "grid_batch": "首批",
            "custom_params": {
                "轮毂高度_m": 130,
                "发电机型号": "DD110-11.1MW",
                "叶片长度_m": 110,
                "控制策略": "强湍流自适应",
            },
            "configs": [
                ConfigType.low_air_density,
                ConfigType.strong_wind_turbulence,
                ConfigType.nacelle_temp_control,
                ConfigType.blade_aero_optimization,
            ],
            "gates": [
                _gate(GateStage.foundation, P, started_at=D(2026, 2, 15), completed_at=D(2026, 2, 18), operator="王建国", remarks="验收合格"),
                _gate(GateStage.hoisting, P, started_at=D(2026, 2, 19), completed_at=D(2026, 2, 25), operator="李志强", remarks="吊装完成"),
                _gate(GateStage.no_load_debug, P, started_at=D(2026, 2, 26), completed_at=D(2026, 3, 4), operator="陈敏", remarks="空载合格"),
                _gate(GateStage.load_test_run, P, started_at=D(2026, 3, 5), completed_at=D(2026, 3, 9), operator="陈敏", remarks="试运行稳定"),
                _gate(GateStage.grid_connection, P, started_at=D(2026, 3, 10), completed_at=D(2026, 3, 12), operator="赵伟", remarks="并网通过"),
            ],
            "issues": [],
        },
        {
            "code": "JLL-03",
            "name": "巨龙梁3号机",
            "altitude_m": 3055,
            "tower_height_m": 115,
            "rotor_diameter_m": 218,
            "swept_area_m2": 37332.28,
            "slope_position": "南坡下段",
            "slope_aspect": "南坡",
            "slope_degree": 14.0,
            "grid_batch": "首批",
            "custom_params": {
                "轮毂高度_m": 115,
                "发电机型号": "DD110-11.1MW",
                "叶片长度_m": 106,
                "控制策略": "标准型",
            },
            "configs": [
                ConfigType.low_air_density,
                ConfigType.strong_wind_turbulence,
                ConfigType.nacelle_temp_control,
            ],
            "gates": [
                _gate(GateStage.foundation, P, started_at=D(2026, 3, 1), completed_at=D(2026, 3, 4), operator="王建国", remarks="合格"),
                _gate(GateStage.hoisting, P, started_at=D(2026, 3, 6), completed_at=D(2026, 3, 12), operator="李志强", remarks="合格"),
                _gate(GateStage.no_load_debug, P, started_at=D(2026, 3, 14), completed_at=D(2026, 3, 20), operator="陈敏", remarks="空载合格"),
                _gate(GateStage.load_test_run, F, started_at=D(2026, 3, 22), completed_at=D(2026, 3, 22), operator="陈敏", remarks="齿轮箱高速端振动超限"),
                _gate(GateStage.grid_connection, ND),
            ],
            "issues": [
                {
                    "stage": GateStage.load_test_run.value,
                    "title": "带负荷试运行齿轮箱振动超限",
                    "description": "满负荷下齿轮箱高速端振动速度达 9.8mm/s，超限，需复alignment并复测",
                    "severity": IssueSeverity.high,
                    "status": IssueStatus.open,
                    "created_at": D(2026, 3, 22),
                },
            ],
        },
        {
            "code": "JLL-04",
            "name": "巨龙梁4号机",
            "altitude_m": 3460,
            "tower_height_m": 135,
            "rotor_diameter_m": 230,
            "swept_area_m2": 41547.56,
            "slope_position": "西坡陡坡",
            "slope_aspect": "西坡",
            "slope_degree": 31.0,
            "grid_batch": "第二批",
            "custom_params": {
                "轮毂高度_m": 135,
                "发电机型号": "DD110-11.1MW",
                "叶片长度_m": 112,
                "控制策略": "陡坡抗风偏航优化",
            },
            "configs": [
                ConfigType.low_air_density,
                ConfigType.nacelle_temp_control,
            ],
            "gates": [
                _gate(GateStage.foundation, P, started_at=D(2026, 3, 10), completed_at=D(2026, 3, 14), operator="王建国", remarks="合格"),
                _gate(GateStage.hoisting, F, started_at=D(2026, 3, 18), completed_at=D(2026, 3, 18), operator="李志强", remarks="吊装平台承载力不足"),
                _gate(GateStage.no_load_debug, ND),
                _gate(GateStage.load_test_run, ND),
                _gate(GateStage.grid_connection, ND),
            ],
            "issues": [
                {
                    "stage": GateStage.hoisting.value,
                    "title": "陡坡吊装平台承载力不足",
                    "description": "履带吊站位区域坡度大，需增设碎石垫层与挡土墙后复吊",
                    "severity": IssueSeverity.high,
                    "status": IssueStatus.open,
                    "created_at": D(2026, 3, 18),
                },
            ],
        },
        {
            "code": "JLL-05",
            "name": "巨龙梁5号机",
            "altitude_m": 3180,
            "tower_height_m": 120,
            "rotor_diameter_m": 220,
            "swept_area_m2": 38013.27,
            "slope_position": "山脊鞍部",
            "slope_aspect": "鞍部",
            "slope_degree": 8.0,
            "grid_batch": "第二批",
            "custom_params": {
                "轮毂高度_m": 120,
                "发电机型号": "DD110-11.1MW",
                "叶片长度_m": 107,
            },
            "configs": [],
            "gates": [
                _gate(GateStage.foundation, ND),
                _gate(GateStage.hoisting, ND),
                _gate(GateStage.no_load_debug, ND),
                _gate(GateStage.load_test_run, ND),
                _gate(GateStage.grid_connection, ND),
            ],
            "issues": [],
        },
    ]

    for spec in units_spec:
        _build_unit(spec, db)
    db.commit()
