from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class MemoryStore:
    def __init__(self, db_path: Path, seed_dir: Path) -> None:
        self.db_path = db_path
        self.seed_dir = seed_dir
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

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
                CREATE TABLE IF NOT EXISTS conversation_memory (
                    session_id TEXT PRIMARY KEY, model TEXT, version TEXT,
                    summary TEXT, updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                    model TEXT, version TEXT, question TEXT, answer TEXT,
                    selected_tool TEXT, source_chunk_ids TEXT, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS verified_solutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT, version TEXT,
                    problem TEXT, solution TEXT, source_chunk_ids TEXT,
                    confirmed_by TEXT, verified INTEGER, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS answer_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                    question TEXT, answer TEXT, helpful INTEGER, reason TEXT,
                    selected_tool TEXT, source_chunk_ids TEXT, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS solution_reuse_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, solution_id INTEGER,
                    session_id TEXT, question TEXT, created_at TEXT
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
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversation_memory VALUES (?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET model=excluded.model, version=excluded.version, summary=excluded.summary, updated_at=excluded.updated_at",
                (session_id, model, version, summary[-2000:], now),
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
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversation_turns "
                "(session_id,model,version,question,answer,selected_tool,source_chunk_ids,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    model,
                    version,
                    question,
                    answer,
                    selected_tool,
                    json.dumps(source_chunk_ids, ensure_ascii=False),
                    now,
                ),
            )
            db.execute(
                "DELETE FROM conversation_turns WHERE session_id=? AND id NOT IN "
                "(SELECT id FROM conversation_turns WHERE session_id=? ORDER BY id DESC LIMIT 20)",
                (session_id, session_id),
            )

    def recent_turns(self, session_id: str, limit: int = 2, ttl_hours: int = 24) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM conversation_turns "
                "WHERE session_id=? AND created_at>=? ORDER BY id DESC LIMIT ?",
                (session_id, cutoff, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

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
        turns = self.recent_turns(session_id, limit=2, ttl_hours=24)
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
        with self.connect() as db:
            removed = db.execute(
                "DELETE FROM conversation_turns WHERE session_id=?", (session_id,)
            ).rowcount
            db.execute("DELETE FROM conversation_memory WHERE session_id=?", (session_id,))
        return int(removed)

    def save_verified_solution(self, payload: dict) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO verified_solutions (model,version,problem,solution,source_chunk_ids,confirmed_by,verified,created_at) VALUES (?,?,?,?,?,?,1,?)",
                (
                    payload["model"], payload.get("version", ""), payload["problem"], payload["solution"],
                    json.dumps(payload["source_chunk_ids"], ensure_ascii=False), payload.get("confirmed_by", "user"), now,
                ),
            )
            return int(cursor.lastrowid)

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
        with self.connect() as db:
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM verified_solutions WHERE verified=1 AND (model=? OR model='') ORDER BY id DESC LIMIT ?",
                    (model, limit),
                ).fetchall()
            ]
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
        best["source_chunk_ids"] = json.loads(best["source_chunk_ids"] or "[]")
        return best

    def record_solution_reuse(self, solution_id: int, session_id: str, question: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO solution_reuse_events (solution_id,session_id,question,created_at) VALUES (?,?,?,?)",
                (solution_id, session_id, question, now),
            )

    def save_feedback(self, payload: dict) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO answer_feedback (session_id,question,answer,helpful,reason,selected_tool,source_chunk_ids,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    payload.get("session_id", "demo"), payload["question"], payload["answer"],
                    int(payload["helpful"]), payload.get("reason", ""), payload.get("selected_tool", ""),
                    json.dumps(payload.get("source_chunk_ids", []), ensure_ascii=False), now,
                ),
            )
            return int(cursor.lastrowid)

    def business_metrics(self) -> dict:
        with self.connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM answer_feedback").fetchone()[0])
            helpful = int(db.execute("SELECT COUNT(*) FROM answer_feedback WHERE helpful=1").fetchone()[0])
            verified = int(db.execute("SELECT COUNT(*) FROM verified_solutions WHERE verified=1").fetchone()[0])
            reuse = int(db.execute("SELECT COUNT(*) FROM solution_reuse_events").fetchone()[0])
        return {
            "feedback_total": total,
            "helpful": helpful,
            "unhelpful": total - helpful,
            "helpful_rate": round(helpful / total, 4) if total else None,
            "verified_solutions": verified,
            "verified_solution_reuse": reuse,
        }
