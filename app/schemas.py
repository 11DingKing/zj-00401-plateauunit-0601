"""Pydantic 请求/响应模型。"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------- 机组 ----------------
class UnitBase(BaseModel):
    code: str = Field(..., description="机组编号，如 JLL-01")
    name: str = Field(..., description="机组名称")
    rated_capacity_mw: float = Field(11.1, description="额定容量(MW)")
    altitude_m: float = Field(..., description="海拔(m)")
    tower_height_m: float = Field(..., description="塔架高度(m)")
    rotor_diameter_m: float = Field(..., description="叶轮直径(m)")
    swept_area_m2: Optional[float] = Field(None, description="扫风面积(m²)，留空时按叶轮直径自动计算")
    slope_position: str = Field(..., description="安装坡位")
    slope_aspect: Optional[str] = Field(None, description="坡向")
    slope_degree: Optional[float] = Field(None, description="坡度(°)")
    grid_batch: str = Field(..., description="并网批次，如 首批 / 第二批")
    custom_params: dict[str, Any] = Field(default_factory=dict, description="定制化参数")


class UnitCreate(UnitBase):
    pass


class UnitUpdate(BaseModel):
    name: Optional[str] = None
    rated_capacity_mw: Optional[float] = None
    altitude_m: Optional[float] = None
    tower_height_m: Optional[float] = None
    rotor_diameter_m: Optional[float] = None
    swept_area_m2: Optional[float] = None
    slope_position: Optional[str] = None
    slope_aspect: Optional[str] = None
    slope_degree: Optional[float] = None
    grid_batch: Optional[str] = None
    custom_params: Optional[dict[str, Any]] = None


class SpecialConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    config_type: str
    config_type_label: str
    enabled: bool
    params: dict[str, Any]
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class GateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage: str
    stage_index: int
    stage_label: str
    status: str
    status_label: str
    operator: Optional[str] = None
    remarks: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    unit_id: int
    unit_code: str
    stage: Optional[str] = None
    stage_label: Optional[str] = None
    title: str
    description: Optional[str] = None
    severity: str
    severity_label: str
    status: str
    team: Optional[str] = None
    team_label: Optional[str] = None
    due_date: Optional[datetime] = None
    overdue: Optional[bool] = None
    reinspection_conclusion: Optional[str] = None
    reinspection_conclusion_label: Optional[str] = None
    reinspection_remark: Optional[str] = None
    reinspected_at: Optional[datetime] = None
    reinspected_by: Optional[str] = None
    created_at: datetime
    closed_at: Optional[datetime] = None
    closed_by: Optional[str] = None


class UnitSummary(BaseModel):
    """机组列表摘要。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    rated_capacity_mw: float
    altitude_m: float
    slope_position: str
    grid_batch: str
    current_stage: Optional[str] = None
    current_stage_label: Optional[str] = None
    operational: bool
    enabled_config_types: list[str]
    config_coverage_complete: bool = Field(
        ..., description="专项配置是否已补齐（全部启用），与关卡流转同口径"
    )
    missing_config_types: list[str] = Field(
        ..., description="尚未启用的专项配置类型列表"
    )
    open_issue_count: int
    overdue_issue_count: int
    grid_blocked_by_overdue: bool


class UnitDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    rated_capacity_mw: float
    altitude_m: float
    tower_height_m: float
    rotor_diameter_m: float
    swept_area_m2: float
    slope_position: str
    slope_aspect: Optional[str] = None
    slope_degree: Optional[float] = None
    grid_batch: str
    custom_params: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    configs: list[SpecialConfigOut]
    gates: list[GateOut]
    issues: list[IssueOut]
    current_stage: Optional[str] = None
    current_stage_label: Optional[str] = None
    operational: bool
    config_coverage_complete: bool = Field(
        ..., description="专项配置是否已补齐（全部启用），与关卡流转同口径"
    )
    missing_config_types: list[str] = Field(
        ..., description="尚未启用的专项配置类型列表"
    )
    overdue_issue_count: int
    grid_blocked_by_overdue: bool


# ---------------- 专项配置 ----------------
class SpecialConfigUpsert(BaseModel):
    config_type: str = Field(..., description="专项配置类型")
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


# ---------------- 验收关卡 ----------------
class GateStatusUpdate(BaseModel):
    status: str = Field(..., description="目标状态: passed / failed")
    operator: Optional[str] = None
    remarks: Optional[str] = None
    issue_title: Optional[str] = Field(None, description="当 status=failed 时可同时登记一条问题")
    issue_description: Optional[str] = None
    issue_severity: Optional[str] = "medium"
    issue_team: Optional[str] = None
    issue_due_date: Optional[datetime] = None


# ---------------- 问题 ----------------
class IssueCreate(BaseModel):
    unit_id: int
    stage: Optional[str] = None
    title: str
    description: Optional[str] = None
    severity: str = "medium"
    team: Optional[str] = None
    due_date: Optional[datetime] = None


class IssueAssign(BaseModel):
    """分派责任班组、约定关闭时限。"""
    team: Optional[str] = None
    due_date: Optional[datetime] = None


class IssueClose(BaseModel):
    closed_by: Optional[str] = None
    reinspection_conclusion: Optional[str] = None
    reinspection_remark: Optional[str] = None
    reinspected_by: Optional[str] = None


# ---------------- 统计 ----------------
class ConfigCoverageItem(BaseModel):
    config_type: str
    config_type_label: str
    enabled_count: int
    total_units: int
    coverage: float          # 0~1
    coverage_pct: float      # 百分比


class ConfigIncompleteUnit(BaseModel):
    """专项配置未补齐的机组（与关卡流转同口径）。"""

    unit_id: int
    code: str
    name: str
    missing_config_types: list[str]
    current_stage: Optional[str] = None


class UnclosedByConfig(BaseModel):
    """按专项配置拆的未关闭问题。"""
    config_type: str
    config_type_label: str
    count: int
    overdue_count: int
    issues: list[IssueOut]


class UnclosedBySlope(BaseModel):
    """按坡位拆的未关闭问题。"""
    slope_position: str
    count: int
    overdue_count: int
    issues: list[IssueOut]


class UnclosedByTeam(BaseModel):
    """按责任班组拆的未关闭问题。"""
    team: Optional[str]
    team_label: Optional[str]
    count: int
    overdue_count: int
    issues: list[IssueOut]


class StatsOut(BaseModel):
    total_units: int
    operational_count: int
    first_batch_operational_count: int
    average_debug_hours: Optional[float] = Field(
        None, description="平均投运调试全程耗时(小时)：基础验收启动 → 并网确认完成"
    )
    average_debug_hours_display: Optional[str] = None
    unclosed_issue_count: int
    overdue_unclosed_count: int
    unclosed_issues: list[IssueOut]
    config_coverage: list[ConfigCoverageItem]
    config_complete_count: int = Field(
        ..., description="专项配置已补齐的机组数（与关卡流转同口径）"
    )
    config_incomplete_count: int = Field(
        ..., description="专项配置未补齐的机组数"
    )
    config_incomplete_units: list[ConfigIncompleteUnit] = Field(
        ..., description="专项配置未补齐的机组明细"
    )
    unclosed_by_config: list[UnclosedByConfig]
    unclosed_by_slope: list[UnclosedBySlope]
    unclosed_by_team: list[UnclosedByTeam]


# ---------------- 坡位适配复盘 ----------------
class SlopeConfigMetric(BaseModel):
    """坡位×配置类型的指标数据。"""

    config_type: str
    config_type_label: str
    unit_count: int = Field(..., description="该配置下的机组数")
    operational_count: int = Field(..., description="已投运机组数")
    acceptance_rate: float = Field(..., description="验收通过率（0~1）：已通过全部关卡的机组占比")
    acceptance_rate_pct: float = Field(..., description="验收通过率百分比")
    rework_count: int = Field(..., description="返工次数：该组所有机组的问题总数")
    avg_rework_per_unit: float = Field(..., description="平均每台机组返工次数")
    avg_debug_hours: Optional[float] = Field(
        None, description="平均调试耗时(小时)，仅统计已投运机组"
    )
    avg_debug_hours_display: Optional[str] = None
    stage_pass_rates: dict[str, float] = Field(
        ..., description="各关卡通过率，key 为关卡 stage 值"
    )


class SlopeReviewItem(BaseModel):
    """单坡位复盘数据。"""

    slope_position: str
    unit_count: int = Field(..., description="该坡位机组总数")
    operational_count: int = Field(..., description="已投运机组数")
    overall_acceptance_rate: float = Field(..., description="整体验收通过率")
    overall_acceptance_rate_pct: float = Field(..., description="整体验收通过率百分比")
    total_rework_count: int = Field(..., description="该坡位总返工次数")
    avg_rework_per_unit: float = Field(..., description="平均每台机组返工次数")
    overall_avg_debug_hours: Optional[float] = Field(
        None, description="该坡位平均调试耗时(小时)"
    )
    overall_avg_debug_hours_display: Optional[str] = None
    by_config: list[SlopeConfigMetric] = Field(
        ..., description="按专项配置类型拆分的指标"
    )
    risk_score: float = Field(
        ..., description="拖慢投运风险评分（0~100，越高越容易拖慢）"
    )
    risk_level: str = Field(..., description="风险等级：低/中/高")
    unit_codes: list[str] = Field(..., description="该坡位机组编号列表")
    unit_summaries: list[UnitSummary] = Field(..., description="机组摘要列表，可下钻查看详情")


class SlopeReviewOut(BaseModel):
    """坡位适配复盘完整输出。"""

    total_units: int
    slope_count: int = Field(..., description="涉及坡位数量")
    slope_reviews: list[SlopeReviewItem] = Field(
        ..., description="按风险评分降序排列的各坡位复盘数据"
    )
    config_type_legend: list[dict[str, str]] = Field(
        ..., description="配置类型图例说明"
    )
    stage_legend: list[dict[str, object]] = Field(
        ..., description="验收关卡图例说明"
    )
