import json

from app.agent.memory import MemoryStore
from app.agent.tool_router import TOOL_CANDIDATES
from app.agent.tools import SQLiteToolbox
from app.models import ToolResult


def _toolbox(tmp_path):
    seed = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "seed"
    memory = MemoryStore(tmp_path / "tools.db", seed)
    return SQLiteToolbox(memory), memory


def test_tool_result_defaults_and_json_serialization():
    result = ToolResult(tool="lookup_parameter")

    assert result.success is False
    assert result.content == ""
    assert result.evidence == []
    assert result.provenance == []
    assert result.latency_ms == 0.0
    assert result.error == ""
    assert result.metadata == {}
    assert json.loads(result.model_dump_json())["tool"] == "lookup_parameter"
    tool_calls = [result.model_dump(mode="json")]
    assert json.loads(json.dumps(tool_calls))[0]["evidence"] == []


def test_fault_code_tool_handles_unknown_and_known_codes(tmp_path):
    tools, _ = _toolbox(tmp_path)

    unknown = tools.lookup_fault_code("16#FFFF")
    known = tools.lookup_fault_code("故障码 16#80C8 是什么意思")

    assert unknown.success is True
    assert unknown.metadata["found"] is False
    assert unknown.latency_ms > 0
    assert known.success is True
    assert known.metadata["found"] is True
    assert "16#80C8" in known.content
    assert known.evidence == []
    assert known.provenance or known.metadata
    assert known.latency_ms > 0


def test_parameter_tool_supports_name_and_stable_empty_result(tmp_path):
    tools, _ = _toolbox(tmp_path)

    known = tools.lookup_parameter("RD_MB_DATA_LEN 的范围")
    unknown = tools.lookup_parameter("NOT_A_REAL_PARAMETER")

    assert known.success is True
    assert known.metadata["found"] is True
    assert known.metadata["name"] == "Read Holding Registers quantity"
    assert "允许范围" in known.content
    assert known.evidence == []
    assert known.provenance or known.metadata
    assert unknown.success is True
    assert unknown.metadata["found"] is False
    assert unknown.content == "未找到匹配的参数记录。"
    assert known.latency_ms > 0 and unknown.latency_ms > 0


def test_table_tool_reports_unavailable_without_store(tmp_path):
    tools, _ = _toolbox(tmp_path)

    result = tools.lookup_table_rows("参数表")

    assert result.success is False
    assert result.error == "table_rows_store_unavailable"
    assert result.metadata == {"available": False, "rows": 0}
    assert result.evidence == []
    assert result.provenance == []
    assert result.latency_ms > 0


def test_table_tool_uses_bound_values_and_malicious_input_is_inert(tmp_path):
    tools, memory = _toolbox(tmp_path)
    with memory.connect() as db:
        db.execute(
            "CREATE TABLE manual_table_rows ("
            "chunk_id TEXT PRIMARY KEY, source TEXT, page INTEGER, section TEXT, "
            "table_id TEXT, row_id TEXT, headers TEXT, text TEXT, model TEXT, version TEXT)"
        )
        db.execute(
            "INSERT INTO manual_table_rows VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "chunk-1",
                "manual.pdf",
                12,
                "Parameters",
                "table-1",
                "row-1",
                "Parameter | Range",
                "RD_MB_DATA_LEN | 1..125",
                "S7-1200",
                "V4.6",
            ),
        )

    found = tools.lookup_table_rows("RD_MB_DATA_LEN", model="S7-1200")
    malicious = tools.lookup_table_rows("'; DROP TABLE manual_table_rows; --")

    assert found.success is True
    assert found.metadata["rows"] == 1
    assert found.provenance == [
        {
            "chunk_id": "chunk-1",
            "source": "manual.pdf",
            "page": 12,
            "section": "Parameters",
            "table_id": "table-1",
            "row_id": "row-1",
        }
    ]
    assert found.evidence == []
    assert malicious.success is True
    with memory.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM manual_table_rows"
        ).fetchone()[0] == 1


def test_sqlite_toolbox_does_not_expose_internal_table_tool_to_router(tmp_path):
    tools, _ = _toolbox(tmp_path)
    results = [
        tools.lookup_fault_code(""),
        tools.lookup_parameter(""),
        tools.lookup_table_rows(""),
    ]

    assert {result.tool for result in results} == {
        "lookup_fault_code",
        "lookup_parameter",
        "lookup_table_rows",
    }
    assert all(result.latency_ms > 0 for result in results)
    router_tools = {
        tool for candidates in TOOL_CANDIDATES.values() for tool in candidates
    }
    assert router_tools <= {
        "search_manual",
        "lookup_fault_code",
        "lookup_parameter",
        "get_document_page",
    }
    assert "lookup_table_rows" not in router_tools
    assert "lookup_verified_solution" not in router_tools
