from app.ingestion.semantic_chunker import fixed_chunks, semantic_chunks, tokenize
from app.ingestion.pdf_loader import _looks_like_link_layout, _table_row_pages, _unique_headers


def test_tokenize_chinese_and_technical_code():
    tokens = tokenize("S7-1200 报错 16#80C8，检查 MB_CLIENT")
    assert "16#80C8" in tokens
    assert "MB_CLIENT" in tokens
    assert "报" in tokens


def test_chunkers_keep_content():
    text = "。".join([f"这是第{i}条通信检查说明，包含足够的技术内容和参数" for i in range(80)]) + "。"
    fixed = fixed_chunks(text, size=80, overlap=10)
    semantic = semantic_chunks(text, minimum=40, target=60, maximum=90)
    assert len(fixed) > 2
    assert len(semantic) > 2
    assert "第0条" in fixed[0]


def test_table_rows_preserve_headers_and_coordinates():
    class FakeTable:
        bbox = (10, 20, 300, 200)

        @staticmethod
        def extract():
            return [["参数", "范围", "单位"], ["RemotePort", "502", "TCP"], ["DATA_LEN", "1-125", "寄存器"]]

    class Finder:
        tables = [FakeTable()]

    class FakePage:
        @staticmethod
        def find_tables(**kwargs):
            assert kwargs == {"strategy": "lines_strict"}
            return Finder()

        @staticmethod
        def get_text(kind):
            assert kind == "blocks"
            return [(10, 1, 300, 15, "表 1 通信参数", 0, 0)]

    pages = _table_row_pages(FakePage(), "doc", "manual.pdf", 7, {"model": "S7-1200"})
    assert len(pages) == 2
    assert "参数=RemotePort" in pages[0].text
    assert "范围=502" in pages[0].text
    assert pages[0].metadata["representation"] == "table_row"
    assert pages[0].metadata["table_id"] == "doc_p0007_t01"
    assert _unique_headers(["值", "值"], 2) == ["值", "值_2"]


def test_link_wrapping_is_not_treated_as_a_table():
    assert _looks_like_link_layout(["说明", "https://support.industry.siemens.com", "论坛"])
    assert not _looks_like_link_layout(["参数", "RemotePort", "502"])
