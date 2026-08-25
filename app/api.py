from __future__ import annotations

import asyncio
import json
import logging
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Query, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
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
    LivenessResponse,
    RagTraceResponse,
    SearchRequest,
    SearchResponse,
    SavedFeedbackResponse,
    SavedSolutionResponse,
    VerifiedSolutionRequest,
    WorkflowEvent,
)
from app.service import AutoOpsService
from app.config import get_settings
from app.http_guard import SlidingWindowRateLimiter
from app.tracing import sanitize_trace


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_service()
    try:
        yield
    finally:
        close_service()


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
    lifespan=lifespan,
)
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
FRONTEND_DIST_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount(
    "/demo/assets",
    StaticFiles(directory=FRONTEND_DIST_DIR / "assets", check_dir=False),
    name="react-demo-assets",
)
SETTINGS = get_settings()
QUERY_GATE = asyncio.Semaphore(max(1, SETTINGS.max_concurrent_queries))
RATE_LIMITER = SlidingWindowRateLimiter(
    SETTINGS.rate_limit_per_minute,
    max_clients=SETTINGS.rate_limit_max_clients,
)
LOGGER = logging.getLogger("autoops.api")


def require_index_admin(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    configured = SETTINGS.index_admin_api_key.strip()
    if not configured:
        raise HTTPException(status_code=503, detail="索引维护接口未启用")
    if not x_admin_key or not secrets.compare_digest(x_admin_key, configured):
        raise HTTPException(
            status_code=401,
            detail="索引管理凭据无效",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def internal_error(operation: str, request: Request, exc: Exception) -> HTTPException:
    request_id = getattr(request.state, "request_id", "unknown")
    LOGGER.exception(
        "%s failed request_id=%s error_type=%s",
        operation,
        request_id,
        type(exc).__name__,
    )
    return HTTPException(
        status_code=500,
        detail="内部服务错误，请使用响应头 X-Request-ID 排查",
    )


@app.middleware("http")
async def request_guard(request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    stream_path = request.url.path == "/api/chat/stream"
    guarded = request.url.path in {"/api/search", "/api/chat", "/api/chat/stream"}
    if guarded:
        client = request.client.host if request.client else "unknown"
        allowed, retry_after = RATE_LIMITER.check(client)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试", "request_id": request_id},
                headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
            )
        if stream_path:
            # The stream generator owns the concurrency slot for its full lifetime.
            response = await call_next(request)
        else:
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


_SERVICE: AutoOpsService | None = None
_SERVICE_LOCK = threading.Lock()


def get_service() -> AutoOpsService:
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = AutoOpsService()
    return _SERVICE


def close_service() -> None:
    global _SERVICE
    with _SERVICE_LOCK:
        service = _SERVICE
        _SERVICE = None
    if service is not None:
        service.close()


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/demo", include_in_schema=False)
@app.get("/demo/", include_in_schema=False)
def react_demo():
    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse(
            "React Demo 尚未构建。请在 frontend 目录运行 npm install 和 npm run build。",
            status_code=503,
        )
    return FileResponse(index_file)


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


def readiness_payload(request: Request) -> dict:
    try:
        return {"status": "ok", **get_service().status()}
    except Exception as exc:
        request_id = getattr(request.state, "request_id", "unknown")
        LOGGER.exception(
            "readiness check failed request_id=%s error_type=%s",
            request_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="服务尚未就绪") from exc


@app.get(
    "/health/live",
    response_model=LivenessResponse,
    response_description="进程存活",
    tags=["服务状态"],
    summary="轻量存活检查",
)
def liveness():
    return {"status": "ok"}


@app.get(
    "/health/ready",
    response_model=HealthResponse,
    response_description="依赖与索引就绪",
    tags=["服务状态"],
    summary="完整就绪检查",
)
def readiness(request: Request):
    return readiness_payload(request)


@app.get(
    "/health",
    response_model=HealthResponse,
    response_description="请求成功",
    tags=["服务状态"],
    summary="兼容健康检查",
)
def health(request: Request):
    return readiness_payload(request)


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
def ingest(
    http_request: Request,
    mode: str = Query(default="semantic", pattern="^(semantic|fixed)$"),
    _: None = Depends(require_index_admin),
):
    try:
        return get_service().reindex(mode)
    except Exception as exc:
        raise internal_error("index_ingest", http_request, exc) from exc


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
        raise internal_error("chat", http_request, exc) from exc


def _sse_payload(event: WorkflowEvent) -> str:
    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"


def _workflow_event(
    event: str,
    request_id: str,
    message: str,
    data: dict | None = None,
) -> WorkflowEvent:
    return WorkflowEvent(
        event=event,
        request_id=request_id,
        timestamp=datetime.now(timezone.utc),
        stage=event,
        message=message,
        data=sanitize_trace(data or {}),
    )


async def _chat_event_stream(request: ChatRequest, request_id: str):
    queue: asyncio.Queue[tuple[str, str, dict]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def observe(stage: str, message: str, data: dict) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (stage, message, data))
        except RuntimeError:
            # The client may have disconnected while synchronous work was finishing.
            return

    yield _sse_payload(
        _workflow_event(
            "request_started",
            request_id,
            "请求已接收，准备执行固定 LangGraph 工作流",
            {"query": request.query, "model": request.model, "version": request.version},
        )
    )

    async def execute_chat() -> ChatResponse:
        async with QUERY_GATE:
            call = partial(
                get_service().chat,
                request,
                request_id,
                workflow_event_callback=observe,
            )
            return await asyncio.wait_for(
                asyncio.to_thread(call),
                timeout=SETTINGS.request_timeout_seconds,
            )

    task = asyncio.create_task(execute_chat())
    try:
        while not task.done():
            try:
                stage, message, data = await asyncio.wait_for(
                    queue.get(), timeout=0.1
                )
            except TimeoutError:
                continue
            yield _sse_payload(_workflow_event(stage, request_id, message, data))

        while not queue.empty():
            stage, message, data = queue.get_nowait()
            yield _sse_payload(_workflow_event(stage, request_id, message, data))

        response = await task
        yield _sse_payload(
            _workflow_event(
                "completed",
                request_id,
                "工作流执行完成",
                {"response": response.model_dump(mode="json")},
            )
        )
    except asyncio.CancelledError:
        task.cancel()
        raise
    except TimeoutError:
        LOGGER.warning("chat_stream timed out request_id=%s", request_id)
        yield _sse_payload(
            _workflow_event(
                "error",
                request_id,
                "请求处理超时，服务端已停止等待；底层同步任务可能短暂继续",
                {"error_type": "request_timeout"},
            )
        )
    except Exception as exc:
        LOGGER.exception(
            "chat_stream failed request_id=%s error_type=%s",
            request_id,
            type(exc).__name__,
        )
        yield _sse_payload(
            _workflow_event(
                "error",
                request_id,
                "内部服务错误，请使用 request_id 排查",
                {"error_type": "internal_error"},
            )
        )


@app.post(
    "/api/chat/stream",
    response_class=StreamingResponse,
    tags=["检索问答"],
    summary="以 SSE 返回工作流阶段事件和最终回答",
)
async def chat_stream(request: ChatRequest, http_request: Request):
    return StreamingResponse(
        _chat_event_stream(request, http_request.state.request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
