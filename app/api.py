from __future__ import annotations

import asyncio
import json
import time
import uuid
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    ChatRequest,
    ChatResponse,
    ClearedSessionResponse,
    AlarmResponse,
    BusinessMetricsResponse,
    FeedbackRequest,
    GraphContextResponse,
    HealthResponse,
    IndexStatusResponse,
    IngestResponse,
    RagTraceResponse,
    SearchRequest,
    SearchResponse,
    SavedFeedbackResponse,
    SavedSolutionResponse,
    VerifiedSolutionRequest,
)
from app.service import AutoOpsService
from app.config import get_settings
from app.http_guard import SlidingWindowRateLimiter


app = FastAPI(
    title="AutoOps RAG 工业手册检索",
    version="4.1.0",
    description="用于检索 S7-1200 和 Modbus 手册，返回中文回答、来源页码和检索结果。接口路径使用英文，说明和示例使用中文。",
    openapi_tags=[
        {"name": "服务状态", "description": "查看服务、资料和索引是否正常。"},
        {"name": "检索问答", "description": "执行手册检索或带处理流程的问答。"},
        {"name": "知识工具", "description": "查询结构化故障码和知识关系。"},
        {"name": "反馈记录", "description": "保存用户反馈和人工确认的方案。"},
        {"name": "索引维护", "description": "耗时维护操作，执行前应先确认没有其他重建任务。"},
    ],
    docs_url=None,
    redoc_url=None,
)
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
SETTINGS = get_settings()
QUERY_GATE = asyncio.Semaphore(max(1, SETTINGS.max_concurrent_queries))
RATE_LIMITER = SlidingWindowRateLimiter(SETTINGS.rate_limit_per_minute)


@app.middleware("http")
async def request_guard(request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    guarded = request.url.path in {"/api/search", "/api/chat"}
    if guarded:
        client = request.client.host if request.client else "unknown"
        allowed, retry_after = RATE_LIMITER.check(client)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试", "request_id": request_id},
                headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
            )
        try:
            async with QUERY_GATE:
                response = await asyncio.wait_for(
                    call_next(request), timeout=SETTINGS.request_timeout_seconds
                )
        except TimeoutError:
            return JSONResponse(
                status_code=504,
                content={"detail": "请求处理超时，已停止等待结果", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
    else:
        response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Elapsed-MS"] = f"{(time.perf_counter() - started) * 1000:.2f}"
    return response


@app.middleware("http")
async def force_utf8_content_type(request, call_next):
    """Make UTF-8 explicit for clients that do not apply the JSON default correctly."""
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset=" not in content_type.lower():
        response.headers["content-type"] = f"{content_type}; charset=utf-8"
    return response


@lru_cache(maxsize=1)
def get_service() -> AutoOpsService:
    return AutoOpsService()


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/docs", include_in_schema=False)
def chinese_api_console():
    return FileResponse(STATIC_DIR / "docs.html")


@app.get("/swagger", include_in_schema=False)
def swagger_docs():
    page = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="AutoOps RAG 接口结构",
        swagger_ui_parameters={
            "defaultModelsExpandDepth": -1,
            "defaultModelExpandDepth": 2,
            "displayRequestDuration": True,
            "docExpansion": "list",
        },
    )
    content = page.body.decode("utf-8").replace(
        "</head>",
        "<style>.response-col_links{display:none!important}</style></head>",
    )
    return HTMLResponse(content)


@app.get(
    "/health",
    response_model=HealthResponse,
    response_description="请求成功",
    tags=["服务状态"],
    summary="健康检查",
)
def health():
    return {"status": "ok", **get_service().status()}


@app.get(
    "/api/index/status",
    response_model=IndexStatusResponse,
    response_description="请求成功",
    tags=["服务状态"],
    summary="查看索引状态",
)
def index_status():
    return get_service().status()


@app.post(
    "/api/index/ingest",
    response_model=IngestResponse,
    response_description="索引构建完成",
    tags=["索引维护"],
    summary="重新解析资料并构建索引",
)
def ingest(mode: str = Query(default="semantic", pattern="^(semantic|fixed)$")):
    try:
        return get_service().reindex(mode)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(
    "/api/search",
    response_model=SearchResponse,
    response_description="检索完成",
    tags=["检索问答"],
    summary="检索相关手册证据",
)
def search(request: SearchRequest):
    return {
        "query": request.query,
        "strategy": request.strategy,
        "hits": get_service().search(
            request.query, request.top_k, request.model, request.version, request.strategy
        ),
    }


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    response_description="回答生成完成",
    tags=["检索问答"],
    summary="生成带来源的中文回答",
)
def chat(request: ChatRequest, http_request: Request):
    try:
        return get_service().chat(request, http_request.state.request_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(
    "/api/traces/recent",
    response_model=list[RagTraceResponse],
    response_description="查询成功",
    tags=["服务状态"],
    summary="查看最近的RAG Trace",
)
def recent_traces(limit: int = Query(default=20, ge=1, le=200)):
    return get_service().recent_traces(limit)


@app.get(
    "/api/traces/{request_id}",
    response_model=RagTraceResponse,
    response_description="查询成功",
    responses={404: {"description": "没有找到该请求的Trace"}},
    tags=["服务状态"],
    summary="按请求编号查看RAG Trace",
)
def get_trace(request_id: str = PathParam(min_length=8, max_length=128)):
    trace = get_service().get_trace(request_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="没有找到该请求的Trace")
    return trace


@app.get(
    "/api/alarms/{code}",
    response_model=AlarmResponse,
    response_description="查询成功",
    responses={404: {"description": "未找到该故障码"}},
    tags=["知识工具"],
    summary="查询故障码",
)
def alarm(
    code: str = PathParam(description="故障码，可输入80C8或16#80C8", examples=["80C8"]),
    model: str = Query(default="S7-1200", description="设备型号"),
):
    record = get_service().memory.lookup_alarm(code, model)
    if not record:
        raise HTTPException(status_code=404, detail="故障码未收录")
    return {
        **record,
        "causes": json.loads(record["causes"]) if record.get("causes", "").startswith("[") else [record.get("causes", "")],
        "checks": json.loads(record["checks"]) if record.get("checks", "").startswith("[") else [record.get("checks", "")],
    }


@app.post(
    "/api/solutions/verify",
    response_model=SavedSolutionResponse,
    response_description="保存成功",
    tags=["反馈记录"],
    summary="保存人工确认的方案",
)
def save_verified_solution(request: VerifiedSolutionRequest):
    try:
        solution_id = get_service().save_solution(request)
        return {"saved": True, "solution_id": solution_id, "verified": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/feedback",
    response_model=SavedFeedbackResponse,
    response_description="保存成功",
    tags=["反馈记录"],
    summary="记录回答反馈",
)
def save_feedback(request: FeedbackRequest):
    feedback_id = get_service().save_feedback(request)
    return {"saved": True, "feedback_id": feedback_id}


@app.delete(
    "/api/sessions/{session_id}",
    response_model=ClearedSessionResponse,
    response_description="清理完成",
    tags=["反馈记录"],
    summary="清空会话记录",
)
def clear_session(
    session_id: str = PathParam(description="页面会话编号", examples=["web-demo"]),
):
    removed = get_service().clear_session(session_id)
    return {"cleared": True, "removed_turns": removed}


@app.get(
    "/api/metrics/business",
    response_model=BusinessMetricsResponse,
    response_description="查询成功",
    tags=["服务状态"],
    summary="查看反馈统计",
)
def business_metrics():
    return get_service().memory.business_metrics()


@app.get(
    "/api/graph/context",
    response_model=GraphContextResponse,
    response_description="查询成功",
    tags=["知识工具"],
    summary="查看问题命中的知识关系",
)
def graph_context(query: str = Query(min_length=1, max_length=500)):
    return get_service().graph_context(query)


@app.on_event("shutdown")
def shutdown() -> None:
    if get_service.cache_info().currsize:
        get_service().close()
