from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.repositories import RuntimeDatabase, RuntimeRepositories


class MemoryStore:
    """Static SQLite knowledge plus compatibility delegates for runtime repositories."""

    def __init__(
        self,
        db_path: Path,
        seed_dir: Path,
        *,
        runtime_repositories: "RuntimeRepositories | None" = None,
        initialize_runtime: bool = True,
    ) -> None:
        self.db_path = db_path
        self.seed_dir = seed_dir
        self._runtime_repositories = runtime_repositories
        self._owned_runtime_database: "RuntimeDatabase | None" = None
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if self._runtime_repositories is None and initialize_runtime:
            # Direct MemoryStore users retain the legacy behavior. AutoOpsService
            # supplies the selected SQLite/PostgreSQL repository bundle instead.
            from app.repositories import create_runtime_database

            self._owned_runtime_database = create_runtime_database(
                backend="sqlite",
                sqlite_path=db_path,
            )
            self._runtime_repositories = self._owned_runtime_database.repositories

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS alarm_codes (
                    code TEXT PRIMARY KEY, title TEXT, meaning TEXT, causes TEXT,
                    checks TEXT, model TEXT, source TEXT
                );
                CREATE TABLE IF NOT EXISTS parameters (
                    name TEXT PRIMARY KEY, aliases TEXT, minimum REAL, maximum REAL,
                    unit TEXT, notes TEXT, model TEXT, source TEXT
                );
                CREATE TABLE IF NOT EXISTS kg_nodes (
                    id TEXT PRIMARY KEY, type TEXT, label TEXT, aliases TEXT
                );
                CREATE TABLE IF NOT EXISTS kg_edges (
                    id TEXT PRIMARY KEY, source TEXT, relation TEXT,
                    target TEXT, provenance TEXT
                );
                """
            )
            self._seed_table(db, "alarms.json", "alarm_codes")
            self._seed_table(db, "parameters.json", "parameters")
            if db.execute("SELECT COUNT(*) FROM kg_nodes").fetchone()[0] == 0:
                self._seed_graph(db)

    def attach_runtime_repositories(
        self, repositories: "RuntimeRepositories"
    ) -> None:
        self._runtime_repositories = repositories

    def _runtime(self) -> "RuntimeRepositories":
        if self._runtime_repositories is None:
            raise RuntimeError("runtime repositories are not configured")
        return self._runtime_repositories

    def _seed_table(self, db: sqlite3.Connection, filename: str, table: str) -> None:
        path = self.seed_dir / filename
        if not path.exists():
            return
        for row in json.loads(path.read_text(encoding="utf-8")):
            keys = list(row)
            placeholders = ",".join("?" for _ in keys)
            db.execute(
                f"INSERT OR REPLACE INTO {table} ({','.join(keys)}) VALUES ({placeholders})",
                [json.dumps(row[k], ensure_ascii=False) if isinstance(row[k], list) else row[k] for k in keys],
            )

    def _seed_graph(self, db: sqlite3.Connection) -> None:
        path = self.seed_dir / "knowledge_graph.json"
        if not path.exists():
            return
        graph = json.loads(path.read_text(encoding="utf-8"))
        for node in graph.get("nodes", []):
            db.execute(
                "INSERT OR REPLACE INTO kg_nodes (id,type,label,aliases) VALUES (?,?,?,?)",
                (node["id"], node["type"], node["label"], json.dumps(node.get("aliases", []), ensure_ascii=False)),
            )
        for edge in graph.get("edges", []):
            db.execute(
                "INSERT OR REPLACE INTO kg_edges (id,source,relation,target,provenance) VALUES (?,?,?,?,?)",
                (edge["id"], edge["source"], edge["relation"], edge["target"], edge.get("provenance", "")),
            )

    def lookup_alarm(self, code: str, model: str = "S7-1200") -> dict | None:
        normalized = code.upper().replace("W#", "").replace("16#", "").replace("0X", "")
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM alarm_codes WHERE REPLACE(REPLACE(UPPER(code),'16#',''),'0X','') = ? AND (model = ? OR model = '')",
                (normalized, model),
            ).fetchone()
            return dict(row) if row else None

    def lookup_parameter(self, name: str, model: str = "S7-1200") -> dict | None:
        query = f"%{name.lower()}%"
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM parameters WHERE (LOWER(name) LIKE ? OR LOWER(aliases) LIKE ?) AND (model = ? OR model = '') LIMIT 1",
                (query, query, model),
            ).fetchone()
            return dict(row) if row else None

    def find_parameter_in_text(self, text: str, model: str = "S7-1200") -> dict | None:
        lowered = text.lower()
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM parameters WHERE model = ? OR model = ''", (model,)
            ).fetchall()
        best: dict | None = None
        best_score = -1
        for row in rows:
            record = dict(row)
            aliases = json.loads(record["aliases"]) if record.get("aliases", "").startswith("[") else []
            names = [record["name"], *aliases]
            matches = [str(name) for name in names if str(name).lower() in lowered]
            score = max((len(value) for value in matches), default=-1)
            if score > best_score:
                best, best_score = record, score
        return best

    def save_session(self, session_id: str, model: str, version: str, summary: str) -> None:
        self._runtime().conversations.upsert_session(
            session_id, model, version, summary
        )

    def save_turn(
        self,
        session_id: str,
        model: str,
        version: str,
        question: str,
        answer: str,
        selected_tool: str,
        source_chunk_ids: list[str],
    ) -> None:
        self._runtime().conversations.append_turn(
            session_id,
            model,
            version,
            question,
            answer,
            selected_tool,
            source_chunk_ids,
            max_turns=20,
        )

    def recent_turns(self, session_id: str, limit: int = 2, ttl_hours: int = 24) -> list[dict]:
        return self._runtime().conversations.get_recent_turns(
            session_id, limit=limit, ttl_hours=ttl_hours
        )

    def build_followup_query(self, session_id: str, question: str) -> tuple[str, int]:
        text = question.strip()
        lowered = text.lower()
        markers = ("那", "那么", "这个", "那个", "它", "上述", "上面", "刚才", "前面", "继续", "还有")
        is_followup = len(text) <= 80 and (
            lowered.startswith(markers)
            or lowered.endswith(("呢", "呢？", "呢?"))
            or any(value in lowered for value in ("这个参数", "这个端口", "这个故障", "该参数", "该端口"))
        )
        if not is_followup:
            return text, 0
        try:
            turns = self.recent_turns(session_id, limit=2, ttl_hours=24)
        except Exception:
            # Conversation context is optional. A temporary runtime database
            # outage must not block static manual retrieval.
            return text, 0
        if not turns:
            return text, 0
        prior_questions = [turn["question"][:240] for turn in turns]
        if "写" in text:
            prior_questions = [
                value.replace("RD_MB_DATA_LEN", "WR_MB_DATA_LEN").replace("读取", "写入")
                for value in prior_questions
            ]
        elif "读" in text:
            prior_questions = [
                value.replace("WR_MB_DATA_LEN", "RD_MB_DATA_LEN").replace("写入", "读取")
                for value in prior_questions
            ]
        history = "\n".join(f"此前问题：{value}" for value in prior_questions)
        return f"{history}\n当前追问：{text}", len(turns)

    def clear_session(self, session_id: str) -> int:
        return self._runtime().conversations.clear_session(session_id)

    def save_verified_solution(self, payload: dict) -> int:
        return self._runtime().verified_solutions.save(payload)

    @staticmethod
    def _text_terms(text: str) -> set[str]:
        lowered = text.lower()
        terms = set(re.findall(r"16#[0-9a-f]+|[a-z][a-z0-9_#.-]+|\d+", lowered))
        for sequence in re.findall(r"[\u4e00-\u9fff]+", lowered):
            terms.update(sequence[i : i + 2] for i in range(max(0, len(sequence) - 1)))
        return terms

    def expand_knowledge_graph(self, text: str, limit: int = 12) -> dict:
        lowered = text.lower()
        with self.connect() as db:
            nodes = [dict(row) for row in db.execute("SELECT * FROM kg_nodes").fetchall()]
        matched: list[dict] = []
        for node in nodes:
            aliases = json.loads(node["aliases"] or "[]")
            names = [node["label"], *aliases]
            if any(str(name).lower() in lowered for name in names):
                matched.append({"id": node["id"], "type": node["type"], "label": node["label"]})
        matched = matched[:4]
        if not matched:
            return {"matched_entities": [], "relations": [], "expansion_terms": []}

        ids = [node["id"] for node in matched]
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as db:
            edges = [
                dict(row)
                for row in db.execute(
                    f"SELECT * FROM kg_edges WHERE source IN ({placeholders}) OR target IN ({placeholders}) LIMIT ?",
                    [*ids, *ids, limit],
                ).fetchall()
            ]
            node_map = {row["id"]: dict(row) for row in db.execute("SELECT * FROM kg_nodes").fetchall()}
        relations: list[dict] = []
        expansion_terms: list[str] = []
        for edge in edges:
            source = node_map.get(edge["source"], {})
            target = node_map.get(edge["target"], {})
            relation = {
                "source": source.get("label", edge["source"]),
                "relation": edge["relation"],
                "target": target.get("label", edge["target"]),
                "provenance": edge["provenance"],
            }
            relations.append(relation)
            for label in (relation["source"], relation["target"]):
                if label.lower() not in lowered and label not in expansion_terms:
                    expansion_terms.append(label)
        return {
            "matched_entities": matched,
            "relations": relations,
            "expansion_terms": expansion_terms[:8],
        }

    def find_verified_solution(self, question: str, model: str, limit: int = 50) -> dict | None:
        query_terms = self._text_terms(question)
        if not query_terms:
            return None
        try:
            rows = self._runtime().verified_solutions.list_recent(model, limit)
        except Exception:
            return None
        best: dict | None = None
        best_score = 0.0
        for row in rows:
            candidate_terms = self._text_terms(row["problem"])
            overlap = len(query_terms & candidate_terms)
            score = overlap / max(1.0, (len(query_terms) * len(candidate_terms)) ** 0.5)
            if overlap >= 2 and score > best_score:
                best, best_score = row, score
        if best is None or best_score < 0.18:
            return None
        best["similarity"] = round(best_score, 4)
        if isinstance(best.get("source_chunk_ids"), str):
            best["source_chunk_ids"] = json.loads(best["source_chunk_ids"] or "[]")
        return best

    def record_solution_reuse(self, solution_id: int, session_id: str, question: str) -> None:
        self._runtime().verified_solutions.record_reuse(
            solution_id, session_id, question
        )

    def save_feedback(self, payload: dict) -> int:
        return self._runtime().feedback.save(payload)

    def business_metrics(self) -> dict:
        return {
            **self._runtime().feedback.metrics(),
            **self._runtime().verified_solutions.metrics(),
        }

    def close(self) -> None:
        if self._owned_runtime_database is not None:
            self._owned_runtime_database.close()
            self._owned_runtime_database = None
