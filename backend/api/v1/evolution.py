from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional
from backend.eval.harness import evaluation_harness
from backend.evolution.critic import critic_agent
from backend.evolution.optimizer import optimizer_agent
from backend.core.database import db

router = APIRouter(prefix="/evolution", tags=["Evolution & Evaluation"])

class SandboxRequest(BaseModel):
    concurrency: Optional[int] = Field(25, description="并发断言线程数")
    sample_size: Optional[int] = Field(100, description="抽取测试用例数(默认100题快速回归)")

class RollbackRequest(BaseModel):
    target_version: str = Field(..., description="目标回滚版本，如 v2.0.0")

@router.post("/run-sandbox")
async def run_sandbox(req: SandboxRequest):
    """触发金标自动化评测沙箱回归跑分"""
    report = await evaluation_harness.run_sandbox(
        concurrency=req.concurrency or 25,
        sample_size=req.sample_size
    )
    return {"code": 200, "data": report}

@router.post("/diagnose")
async def diagnose_conversations():
    """触发离线 Critic 流失归因诊断分析"""
    report = critic_agent.analyze_recent_conversations()
    return {"code": 200, "data": report}

@router.post("/optimize")
async def optimize_and_release():
    """触发进化工坊：诊断 -> 生成增量候选补丁 -> 跑沙箱回归 -> 自动热发布/熔断"""
    res = await optimizer_agent.optimize_and_evaluate()
    return {"code": 200, "data": res}

@router.post("/rollback")
async def rollback_prompt(req: RollbackRequest):
    """一键秒级版本回滚接口"""
    res = optimizer_agent.rollback_version(req.target_version)
    return {"code": 200, "data": res}

@router.get("/versions")
async def list_versions():
    """查看 Prompt 历史版本与跑分快照"""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT version, eval_score, is_active, created_at FROM prompt_versions ORDER BY created_at DESC")
        rows = cursor.fetchall()
        versions = [
            {
                "version": r["version"],
                "eval_score": r["eval_score"],
                "is_active": bool(r["is_active"]),
                "created_at": r["created_at"]
            }
            for r in rows
        ]
    return {"code": 200, "data": versions}

