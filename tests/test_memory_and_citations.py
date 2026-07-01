from app.agent.memory import MemoryStore
from app.generation.citation_guard import validate_citations, validate_grounded_citations
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


def test_grounded_citation_guard_requires_one_adjacent_source_per_atomic_claim():
    evidence = [
        SearchHit(chunk=Chunk(chunk_id="c1", doc_id="d", doc_name="手册", text="事实一"), score=1),
        SearchHit(chunk=Chunk(chunk_id="c2", doc_id="d", doc_name="手册", text="事实二"), score=1),
    ]
    valid = (
        "1. 结论\n- 事实一。[来源1]\n"
        "2. 原因\n- 事实二。[来源2]\n"
        "3. 排查 / 换算建议\n- 核对事实一。[来源1]\n"
        "4. 引用来源\n5. 安全提示\n"
    )
    ok, warnings = validate_grounded_citations(valid, evidence)
    assert ok and not warnings

    broad = valid.replace("事实一。[来源1]", "事实一和事实二。[来源1][来源2]", 1)
    ok, warnings = validate_grounded_citations(broad, evidence)
    assert not ok
    assert any("只能引用一个" in warning for warning in warnings)

    uncited = valid.replace("事实二。[来源2]", "事实二。", 1)
    ok, warnings = validate_grounded_citations(uncited, evidence)
    assert not ok
    assert any("没有来源编号" in warning for warning in warnings)


def test_grounded_citation_guard_rejects_question_only_identifier():
    evidence = [
        SearchHit(
            chunk=Chunk(
                chunk_id="c1",
                doc_id="d",
                doc_name="手册",
                text="不要在上一条请求仍处于 BUSY 时反复产生新的 REQ 上升沿。",
            ),
            score=1,
        )
    ]
    answer = (
        "1. 结论\n- MB_CLIENT 在 BUSY 时不要反复触发 REQ。[来源1]\n"
        "2. 原因\n- 在 BUSY 时反复触发 REQ 不符合当前证据中的请求触发要求。[来源1]\n"
        "3. 排查 / 换算建议\n- 核对 BUSY 与 REQ 的触发关系。[来源1]\n"
        "4. 引用来源\n5. 安全提示\n"
    )

    ok, warnings = validate_grounded_citations(answer, evidence)

    assert not ok
    assert any("MB_CLIENT" in warning for warning in warnings)


def test_grounded_citation_guard_rejects_unsupported_generalization_term():
    evidence = [
        SearchHit(
            chunk=Chunk(
                chunk_id="c1",
                doc_id="d",
                doc_name="手册",
                text="多寄存器数值的字顺序由设备实现决定。",
            ),
            score=1,
        )
    ]
    answer = (
        "1. 结论\n- 不同设备可能采用不同字节排列。[来源1]\n"
        "2. 原因\n- 多寄存器数值的字顺序由设备实现决定。[来源1]\n"
        "3. 排查 / 换算建议\n- 核对设备资料中的字顺序。[来源1]\n"
        "4. 引用来源\n5. 安全提示\n"
    )

    ok, warnings = validate_grounded_citations(answer, evidence)

    assert not ok
    assert any("可能" in warning for warning in warnings)


def test_grounded_citation_guard_accepts_two_targeted_direct_rewrites():
    busy_evidence = [
        SearchHit(
            chunk=Chunk(
                chunk_id="c1",
                doc_id="d",
                doc_name="手册",
                text="不要在上一条请求仍处于 BUSY 时反复产生新的 REQ 上升沿。",
            ),
            score=1,
        )
    ]
    busy_answer = (
        "1. 结论\n- 在 BUSY 时反复触发 REQ 不符合当前证据中的请求触发要求。[来源1]\n"
        "2. 原因\n- 上一条请求处于 BUSY 时不要产生新的 REQ 上升沿。[来源1]\n"
        "3. 排查 / 换算建议\n- 核对 BUSY 时是否产生新的 REQ 上升沿。[来源1]\n"
        "4. 引用来源\n5. 安全提示\n"
    )
    ok, warnings = validate_grounded_citations(busy_answer, busy_evidence)
    assert ok and not warnings

    order_evidence = [
        SearchHit(
            chunk=Chunk(
                chunk_id="c2",
                doc_id="d",
                doc_name="手册",
                text="多寄存器数值的字顺序由设备实现决定。",
            ),
            score=1,
        )
    ]
    order_answer = (
        "1. 结论\n- 多寄存器数值的字顺序由设备实现决定。[来源1]\n"
        "2. 原因\n- 多寄存器数值的字顺序由设备实现决定。[来源1]\n"
        "3. 排查 / 换算建议\n- 核对设备资料中的字顺序。[来源1]\n"
        "4. 引用来源\n5. 安全提示\n"
    )
    ok, warnings = validate_grounded_citations(order_answer, order_evidence)
    assert ok and not warnings


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
