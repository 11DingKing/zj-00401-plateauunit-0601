"""领域枚举与中文标签定义。"""

from enum import Enum


class ConfigType(str, Enum):
    """机组专项配置类型。"""

    low_air_density = "low_air_density"            # 低空气密度适配
    strong_wind_turbulence = "strong_wind_turbulence"  # 强风乱流适配
    nacelle_temp_control = "nacelle_temp_control"      # 机舱温控
    blade_aero_optimization = "blade_aero_optimization"  # 叶片气动优化


CONFIG_TYPE_LABELS = {
    ConfigType.low_air_density: "低空气密度适配",
    ConfigType.strong_wind_turbulence: "强风乱流适配",
    ConfigType.nacelle_temp_control: "机舱温控",
    ConfigType.blade_aero_optimization: "叶片气动优化",
}


class GateStage(str, Enum):
    """投运前验收关卡，按执行顺序排列。"""

    foundation = "foundation"          # 基础验收
    hoisting = "hoisting"              # 吊装验收
    no_load_debug = "no_load_debug"   # 空载调试
    load_test_run = "load_test_run"   # 带负荷试运行
    grid_connection = "grid_connection"  # 并网确认


GATE_ORDER = [
    GateStage.foundation,
    GateStage.hoisting,
    GateStage.no_load_debug,
    GateStage.load_test_run,
    GateStage.grid_connection,
]

GATE_STAGE_LABELS = {
    GateStage.foundation: "基础验收",
    GateStage.hoisting: "吊装验收",
    GateStage.no_load_debug: "空载调试",
    GateStage.load_test_run: "带负荷试运行",
    GateStage.grid_connection: "并网确认",
}


class GateStatus(str, Enum):
    pending = "pending"   # 待执行
    passed = "passed"     # 通过
    failed = "failed"     # 未通过


GATE_STATUS_LABELS = {
    GateStatus.pending: "待执行",
    GateStatus.passed: "通过",
    GateStatus.failed: "未通过",
}


class IssueStatus(str, Enum):
    open = "open"       # 未关闭
    closed = "closed"   # 已关闭


class IssueSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


ISSUE_SEVERITY_LABELS = {
    IssueSeverity.low: "低",
    IssueSeverity.medium: "中",
    IssueSeverity.high: "高",
}


def stage_index(stage: GateStage) -> int:
    return GATE_ORDER.index(stage)
