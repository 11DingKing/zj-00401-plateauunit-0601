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
    created_at: datetime
    closed_at: Optional[datetime] = None


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
    open_issue_count: int


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


# ---------------- 问题 ----------------
class IssueCreate(BaseModel):
    unit_id: int
    stage: Optional[str] = None
    title: str
    description: Optional[str] = None
    severity: str = "medium"


class IssueClose(BaseModel):
    closed_by: Optional[str] = None


# ---------------- 统计 ----------------
class ConfigCoverageItem(BaseModel):
    config_type: str
    config_type_label: str
    enabled_count: int
    total_units: int
    coverage: float          # 0~1
    coverage_pct: float      # 百分比


class StatsOut(BaseModel):
    total_units: int
    operational_count: int
    first_batch_operational_count: int
    average_debug_hours: Optional[float] = Field(
        None, description="平均投运调试全程耗时(小时)：基础验收启动 → 并网确认完成"
    )
    average_debug_hours_display: Optional[str] = None
    unclosed_issue_count: int
    unclosed_issues: list[IssueOut]
    config_coverage: list[ConfigCoverageItem]
