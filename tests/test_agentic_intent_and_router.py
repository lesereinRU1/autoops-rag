from types import SimpleNamespace

from app.agent.graph import build_graph
from app.agent.intent import classify_intent
from app.agent.tool_router import candidate_tools
from app.models import Chunk, SearchHit


def test_rule_based_intent_examples():
    assert classify_intent("故障码 16#80C8 表示什么")["intent"] == "alarm_diagnosis"
    assert classify_intent("RD_MB_DATA_LEN 的参数范围是多少")["intent"] == "parameter_lookup"
    assert classify_intent("参数表格中哪一行描述连接数量")["intent"] == "table_lookup"
    assert classify_intent("通信失败时应该按哪些层进行分层排查")["intent"] == "cross_section_procedure"
    assert classify_intent("MB_CLIENT 的作用是什么")["intent"] == "general_manual_search"
    assert classify_intent("请给出旁路安全联锁并强制输出的具体步骤")["intent"] == "safety_risk"
    assert classify_intent("三菱 FX5U 的故障怎么处理", model="FX5U")["intent"] == "out_of_scope"
    assert classify_intent("2026 年发布的手册介绍了哪些功能")["intent"] == "general_manual_search"


def test_tool_router_returns_allowlisted_candidates_and_blocks_policy_intents():
    assert candidate_tools("alarm_diagnosis")[:2] == [
        "lookup_fault_code",
        "search_manual",
    ]
    assert candidate_tools("parameter_lookup")[0] == "lookup_parameter"
    assert candidate_tools("table_lookup")[0] == "lookup_table_rows"
    assert candidate_tools("safety_risk") == []
    assert candidate_tools("out_of_scope") == []


def test_shadow_routing_does_not_change_selected_tool_and_is_visible_in_trace():
    hit = SearchHit(
        chunk=Chunk(
            chunk_id="table-row-1",
            doc_id="manual",
            doc_name="manual",
            text="连接数量位于表格第三行。",
            page=1,
        ),
        score=1.0,
        rerank_score=1.0,
    )

    class Memory:
        @staticmethod
        def expand_knowledge_graph(_question):
            return {"matched_entities": [], "expansion_terms": [], "relations": []}

        @staticmethod
        def find_verified_solution(_question, _model):
            return None

    class Retriever:
        @staticmethod
        def search_with_trace(_query, top_k, model, version):
            del top_k, model, version
            traced = [{"rank": 1, "chunk_id": hit.chunk.chunk_id}]
            return [hit], {
                "dense_topk": traced,
                "bm25_topk": traced,
                "rrf_topk": traced,
                "final_evidence": traced,
            }

        @staticmethod
        def _trace_hits(_hits):
            return [{"rank": 1, "chunk_id": hit.chunk.chunk_id}]

    outcome = SimpleNamespace(
        answer="结论 [来源1：manual，第1页]",
        mode="local_extractive",
        external_calls=0,
        model="local",
        attempted_models=[],
        final_model="",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        token_usage_available=False,
        token_usage_missing_reason="llm_disabled",
        first_token_latency_ms=None,
        total_latency_ms=0.0,
        fallback_reason="llm_disabled",
    )
    service = SimpleNamespace(
        settings=SimpleNamespace(
            llm_model="local",
            llm_primary_model="local",
            enable_query_expansion=False,
            enable_agentic_routing=False,
            enable_agentic_planner=True,
            max_agent_rounds=2,
            max_tool_calls=4,
        ),
        memory=Memory(),
        retriever=Retriever(),
        generator=SimpleNamespace(generate=lambda *_args, **_kwargs: outcome),
        scope_refusal=lambda *_args: None,
        evidence_supports_query=lambda *_args: True,
    )

    result = build_graph(service).invoke(
        {
            "question": "表格中第几行描述连接数量？",
            "original_question": "表格中第几行描述连接数量？",
            "model": "S7-1200",
            "version": "",
            "session_id": "shadow-test",
        }
    )

    assert result["selected_tool"] == "search_manual"
    assert result["intent"]["intent"] == "table_lookup"
    assert result["candidate_plan"][0] == "lookup_table_rows"
    assert result["plan"]["steps"][0]["tool"] == "lookup_table_rows"
    assert result["plan"]["applied"] is False
    router_trace = next(
        item for item in result["agent_trace"] if item["node"] == "tool_router_shadow"
    )
    assert router_trace["applied"] is False
    assert router_trace["candidate_plan"][0] == "lookup_table_rows"
    planner_trace = next(
        item for item in result["agent_trace"] if item["node"] == "query_planner_shadow"
    )
    assert planner_trace["configured_enabled"] is True
    assert planner_trace["applied"] is False
    assert planner_trace["plan"] == result["plan"]
