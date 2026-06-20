"""巨龙梁风电场扩建项目 - 机组管理后端入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, SessionLocal, engine
from app.routers import gates, issues, stats, units
from app.seed import seed_if_empty


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="巨龙梁风电场扩建项目 - 机组管理后端",
    description="11.1MW 高原山地风电机组：建档、专项配置、投运前五道关验收流转与统计",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["元信息"])
def root():
    return {
        "project": "巨龙梁风电场扩建项目",
        "rated_capacity_mw": 11.1,
        "docs": "/docs",
        "endpoints": {
            "units": "/api/units",
            "gates": "/api/units/{unit_id}/gates",
            "issues": "/api/issues",
            "stats": "/api/stats",
        },
    }


@app.get("/health", tags=["元信息"])
def health():
    return {"status": "ok"}


API_PREFIX = "/api"
app.include_router(units.router, prefix=API_PREFIX)
app.include_router(gates.router, prefix=API_PREFIX)
app.include_router(issues.router, prefix=API_PREFIX)
app.include_router(stats.router, prefix=API_PREFIX)
