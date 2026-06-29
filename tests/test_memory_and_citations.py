from app.agent.memory import MemoryStore
from app.generation.citation_guard import validate_citations
from app.models import Chunk, SearchHit


def test_alarm_seed_and_citation_guard(tmp_path):
    seed = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "seed"
    memory = MemoryStore(tmp_path / "test.db", seed)
    assert memory.lookup_alarm("80C8")["code"] == "16#80C8"
    item = SearchHit(chunk=Chunk(chunk_id="c1", doc_id="d", doc_name="手册", text="证据"), score=1)
    ok, warnings = validate_citations("结论 [手册-第1页-正文 | c1]", [item])
    assert ok and not warnings
    ok, warnings = validate_citations("结论 [来源1：手册，第1页]", [item])
    assert ok and not warnings
    ok, warnings = validate_citations("结论 [来源2：不存在]", [item])
    assert not ok and warnings


def test_graph_feedback_and_verified_solution_loop(tmp_path):
    seed = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "seed"
    memory = MemoryStore(tmp_path / "loop.db", seed)
    graph = memory.expand_knowledge_graph("MB_CLIENT 报错 16#80C8")
    assert any(item["label"] == "MB_CLIENT" for item in graph["matched_entities"])
    assert any(item["target"] == "16#80C8" for item in graph["relations"])

    solution_id = memory.save_verified_solution(
        {
            "model": "S7-1200",
            "version": "V4.6",
            "problem": "MB_CLIENT 出现 16#80C8 通信超时",
            "solution": "核对端口、Unit ID 和寄存器地址",
            "source_chunk_ids": ["c1"],
            "confirmed_by": "tester",
        }
    )
    reused = memory.find_verified_solution("MB_CLIENT 16#80C8 通信超时怎么处理", "S7-1200")
    assert reused and reused["id"] == solution_id
    feedback_id = memory.save_feedback(
        {
            "session_id": "s1", "question": "q", "answer": "a", "helpful": True,
            "reason": "", "selected_tool": "lookup_alarm_code", "source_chunk_ids": ["c1"],
        }
    )
    assert feedback_id > 0
    assert memory.business_metrics()["helpful_rate"] == 1.0


def test_bounded_followup_memory_and_clear(tmp_path):
    seed = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "seed"
    memory = MemoryStore(tmp_path / "turns.db", seed)
    memory.save_turn(
        "s1", "S7-1200", "", "RD_MB_DATA_LEN允许读取多少个寄存器？",
        "允许读取1到125个寄存器。", "check_parameter_range", ["c1"],
    )
    memory.save_turn(
        "s1", "S7-1200", "", "这个参数在哪一页？",
        "位于第938页。", "search_manual", ["c1"],
    )
    resolved, used = memory.build_followup_query("s1", "那写入最多多少个呢？")
    assert used == 2
    assert "WR_MB_DATA_LEN" in resolved
    assert "RD_MB_DATA_LEN" not in resolved
    assert memory.find_parameter_in_text(resolved)["name"] == "WR_MB_DATA_LEN"
    assert "当前追问" in resolved
    independent, used = memory.build_followup_query("s1", "Modbus TCP默认端口是多少？")
    assert independent == "Modbus TCP默认端口是多少？"
    assert used == 0
    assert memory.clear_session("s1") == 2
    assert memory.recent_turns("s1") == []
