from app.agent.evidence_terms import (
    filter_retry_identifiers,
    generic_terms_in_text,
    is_generic_term,
    normalize_technical_terms,
)


def test_normalize_terms_is_case_insensitive_and_stable():
    assert normalize_technical_terms([" mb_client ", "MB_CLIENT", "16#80c8"]) == [
        "MB_CLIENT",
        "16#80C8",
    ]


def test_generic_industrial_words_and_single_digits_are_filtered():
    terms = ["0", "1", "PLC", "manual", "手册", "参数", "故障", "报警", "设备", "S7", "S7-1200"]
    assert filter_retry_identifiers(terms) == []
    assert all(is_generic_term(term) for term in terms)
    assert set(generic_terms_in_text("PLC 手册参数故障报警设备 manual")) >= {
        "PLC",
        "MANUAL",
        "手册",
        "参数",
        "故障",
        "报警",
        "设备",
    }


def test_discriminative_short_and_domain_identifiers_are_preserved():
    terms = [
        "MB_CLIENT",
        "MB_SERVER",
        "CONNECT",
        "DISCONNECT",
        "16#80C8",
        "16#809A",
        "REQ",
        "ID",
        "IP",
        "DB",
        "PORT",
        "BAUD",
        "PARITY",
        "502",
    ]
    assert filter_retry_identifiers(terms) == terms
