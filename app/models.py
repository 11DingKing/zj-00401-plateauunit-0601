"""SQLAlchemy ORM 模型：机组、专项配置、验收关卡、问题清单。"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Unit(Base):
    """风电机组档案。"""

    __tablename__ = "units"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)        # 机组编号，如 JLL-01
    name = Column(String, nullable=False)                                # 机组名称
    rated_capacity_mw = Column(Float, nullable=False, default=11.1)       # 额定容量(MW)
    altitude_m = Column(Float, nullable=False)                            # 海拔(m)
    tower_height_m = Column(Float, nullable=False)                        # 塔架高度(m)
    rotor_diameter_m = Column(Float, nullable=False)                     # 叶轮直径(m)
    swept_area_m2 = Column(Float, nullable=False)                        # 扫风面积(m²)
    slope_position = Column(String, nullable=False)                      # 安装坡位
    slope_aspect = Column(String, nullable=True)                         # 坡向
    slope_degree = Column(Float, nullable=True)                           # 坡度(°)
    grid_batch = Column(String, nullable=False)                          # 并网批次
    custom_params = Column(JSON, nullable=False, default=dict)           # 定制化参数
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    configs = relationship(
        "SpecialConfig", back_populates="unit", cascade="all, delete-orphan"
    )
    gates = relationship(
        "Gate",
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by="Gate.stage_index",
    )
    issues = relationship("Issue", back_populates="unit", cascade="all, delete-orphan")


class SpecialConfig(Base):
    """机组专项配置（低空气密度适配 / 强风乱流适配 / 机舱温控 / 叶片气动优化）。"""

    __tablename__ = "special_configs"
    __table_args__ = (UniqueConstraint("unit_id", "config_type", name="uq_unit_config_type"),)

    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    config_type = Column(String, nullable=False)        # ConfigType 枚举值
    enabled = Column(Boolean, nullable=False, default=True)
    params = Column(JSON, nullable=False, default=dict)  # 该专项配置的具体参数
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    unit = relationship("Unit", back_populates="configs")


class Gate(Base):
    """投运前验收关卡记录。"""

    __tablename__ = "gates"
    __table_args__ = (UniqueConstraint("unit_id", "stage", name="uq_unit_stage"),)

    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String, nullable=False)             # GateStage 枚举值
    stage_index = Column(Integer, nullable=False)      # 关卡顺序
    status = Column(String, nullable=False, default="pending")  # GateStatus
    operator = Column(String, nullable=True)           # 执行人
    remarks = Column(Text, nullable=True)              # 备注
    started_at = Column(DateTime, nullable=True)       # 该关卡启动时间
    completed_at = Column(DateTime, nullable=True)     # 该关卡完成时间
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    unit = relationship("Unit", back_populates="gates")


class Issue(Base):
    """问题清单。"""

    __tablename__ = "issues"

    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String, nullable=True)              # 关联的关卡(可空)
    title = Column(String, nullable=False)             # 问题标题
    description = Column(Text, nullable=True)           # 问题描述
    severity = Column(String, nullable=False, default="medium")  # IssueSeverity
    status = Column(String, nullable=False, default="open")      # IssueStatus
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(String, nullable=True)

    unit = relationship("Unit", back_populates="issues")
