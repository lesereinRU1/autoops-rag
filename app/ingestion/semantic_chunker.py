from __future__ import annotations

import re


TOKEN_PATTERN = re.compile(r"16#[0-9A-Fa-f]+|[\u4e00-\u9fff]|[A-Za-z]+(?:_[A-Za-z]+)*|\d+(?:\.\d+)?")
SENTENCE_PATTERN = re.compile(r"(?<=[。！？!?；;])|\n+")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text)


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in SENTENCE_PATTERN.split(text) if item.strip()]


def fixed_chunks(text: str, size: int = 450, overlap: int = 60) -> list[str]:
    sentences = _sentences(text)
    if not sentences:
        return []
    result: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        sentence_tokens = len(tokenize(sentence))
        if current and count + sentence_tokens > size:
            result.append("\n".join(current))
            tail: list[str] = []
            tail_count = 0
            for old in reversed(current):
                old_count = len(tokenize(old))
                if tail and tail_count + old_count > overlap:
                    break
                tail.insert(0, old)
                tail_count += old_count
            current, count = tail, tail_count
        current.append(sentence)
        count += sentence_tokens
    if current:
        result.append("\n".join(current))
    return [chunk for chunk in result if len(chunk.strip()) >= 20]


def semantic_chunks(text: str, minimum: int = 300, target: int = 450, maximum: int = 600) -> list[str]:
    """轻量语义切分：句子词集相似度突降且达到最小长度时切块。"""
    sentences = _sentences(text)
    result: list[str] = []
    current: list[str] = []
    count = 0
    previous_tokens: set[str] = set()
    for sentence in sentences:
        tokens = set(tokenize(sentence.lower()))
        union = previous_tokens | tokens
        similarity = len(previous_tokens & tokens) / max(1, len(union))
        sentence_count = len(tokens)
        boundary = count >= minimum and (count >= target and similarity < 0.05)
        if current and (boundary or count + sentence_count > maximum):
            result.append("\n".join(current))
            current, count = [], 0
        current.append(sentence)
        count += sentence_count
        previous_tokens = tokens
    if current:
        result.append("\n".join(current))
    return [chunk for chunk in result if len(chunk.strip()) >= 20]
