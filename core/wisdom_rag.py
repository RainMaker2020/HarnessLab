"""WisdomRAG — semantic memory of task failures and successful fixes (Level 5 Experience Engine).

Indexes ``docs/history.json`` and ``docs/trajectories.jsonl`` into a local ChromaDB store.
Each vector represents: task description + failure/error + successful fix.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

# Prompt sections we parse from archived prompts
_PREVIOUS_FAILURE_START = re.compile(
    r"##\s*⚠️\s*PREVIOUS FAILURE[^#]*?(?=##|\Z)", re.DOTALL | re.IGNORECASE
)
_DESC_LINE = re.compile(r"\*\*Description:\*\*\s*(.+)", re.MULTILINE)
_PLAN_TASK = re.compile(r"^- \[[ x]\]\s*(TASK_\d+):\s*(.+)\s*$", re.MULTILINE)


def _truncate(text: str, max_len: int = 4000) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def parse_plan_descriptions(plan_file: Path) -> dict[str, str]:
    """Map TASK_XX -> description from PLAN.md."""
    if not plan_file.is_file():
        return {}
    text = plan_file.read_text(encoding="utf-8")
    return {m.group(1): m.group(2).strip() for m in _PLAN_TASK.finditer(text)}


def extract_description_from_prompt(prompt_text: str) -> str:
    m = _DESC_LINE.search(prompt_text)
    return m.group(1).strip() if m else ""


def extract_previous_failure_block(prompt_text: str) -> str:
    m = _PREVIOUS_FAILURE_START.search(prompt_text)
    if not m:
        return ""
    return _truncate(m.group(0), 2500)


def stable_id(parts: str) -> str:
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:32]


class WisdomRAG:
    """Local ChromaDB-backed wisdom store with embedding search."""

    def __init__(
        self,
        persist_directory: Path,
        collection_name: str = "harness_wisdom",
    ) -> None:
        self._persist = Path(persist_directory)
        self._collection_name = collection_name
        self._collection = None
        self._chromadb = None
        self._embed_fn = None

    def _ensure_client(self) -> Any:
        if self._chromadb is None:
            try:
                import chromadb
            except ImportError as exc:  # pragma: no cover - env dependent
                raise RuntimeError(
                    "chromadb is required for Wisdom RAG. Install with: pip install chromadb"
                ) from exc
            self._chromadb = chromadb
        if self._collection is None:
            from chromadb.utils import embedding_functions

            self._embed_fn = embedding_functions.DefaultEmbeddingFunction()
            client = self._chromadb.PersistentClient(path=str(self._persist))
            self._collection = client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=self._embed_fn,
                metadata={"harness": "wisdom_v1"},
            )
        return self._collection

    def retrieve_lessons(self, task_description: str, top_k: int = 3) -> list[dict[str, str]]:
        """Semantic search; returns dicts with keys task_id, task_description, error, fix."""
        if not task_description.strip():
            return []
        col = self._ensure_client()
        n = max(top_k, 1)
        res = col.query(query_texts=[task_description], n_results=n)
        if not res or not res.get("ids") or not res["ids"][0]:
            return []
        out: list[dict[str, str]] = []
        metas = res.get("metadatas") or [[]]
        for meta in metas[0]:
            if not meta:
                continue
            out.append(
                {
                    "task_id": str(meta.get("task_id", "")),
                    "task_description": str(meta.get("task_description", "")),
                    "error": str(meta.get("error", "")),
                    "fix": str(meta.get("fix", "")),
                }
            )
        return out[:top_k]

    def upsert_lesson(
        self,
        *,
        lesson_id: str,
        document_text: str,
        task_id: str,
        task_description: str,
        error: str,
        fix: str,
    ) -> None:
        """Add or update one lesson in the vector store."""
        col = self._ensure_client()
        col.upsert(
            ids=[lesson_id],
            documents=[document_text],
            metadatas=[
                {
                    "task_id": task_id,
                    "task_description": _truncate(task_description, 2000),
                    "error": _truncate(error, 4000),
                    "fix": _truncate(fix, 4000),
                }
            ],
        )

    def build_document_text(
        self,
        task_description: str,
        error: str,
        fix: str,
    ) -> str:
        """Single string used for embedding (task + failure + fix)."""
        return (
            f"Task description:\n{_truncate(task_description, 3000)}\n\n"
            f"Failure or error:\n{_truncate(error, 3000)}\n\n"
            f"Successful fix:\n{_truncate(fix, 3000)}"
        )

    def ingest_success_trajectory(
        self,
        task_id: str,
        task_description: str,
        prompt_text: str,
        git_diff: str,
    ) -> None:
        """Call after a successful merge: embed trajectory as a new lesson."""
        err = extract_previous_failure_block(prompt_text)
        if not err.strip():
            err = "(No prior failure in this sprint — first-pass success.)"
        fix = _truncate(git_diff, 6000) if git_diff.strip() else "(empty diff)"
        doc = self.build_document_text(task_description, err, fix)
        lid = stable_id(f"traj|{task_id}|{task_description}|{fix[:500]}")
        self.upsert_lesson(
            lesson_id=lid,
            document_text=doc,
            task_id=task_id,
            task_description=task_description,
            error=err,
            fix=fix,
        )

    def index_from_files(
        self,
        history_file: Path,
        trajectories_file: Optional[Path],
        plan_file: Path,
    ) -> int:
        """Bulk-index ``history.json`` and ``trajectories.jsonl``. Returns number of records upserted."""
        plan_map = parse_plan_descriptions(plan_file)
        count = 0

        trajectories: list[dict[str, Any]] = []
        if trajectories_file is not None and trajectories_file.is_file():
            raw = trajectories_file.read_text(encoding="utf-8")
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    trajectories.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        trajectories.sort(key=lambda r: str(r.get("timestamp") or ""))

        history: list[dict[str, Any]] = []
        if history_file.is_file():
            try:
                history = json.loads(history_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                history = []

        def fix_for_failure(entry: dict[str, Any]) -> str:
            tid = str(entry.get("task_id") or "")
            ts = str(entry.get("timestamp") or "")
            for tr in trajectories:
                if str(tr.get("task_id")) != tid:
                    continue
                if str(tr.get("timestamp") or "") > ts:
                    return _truncate(str(tr.get("output_git_diff") or ""), 6000)
            return "(Fix not yet captured in trajectories — pair when available.)"

        for entry in history:
            tid = str(entry.get("task_id") or "UNKNOWN")
            desc = plan_map.get(tid, "")
            err_parts = [
                str(entry.get("evaluator_output") or ""),
                str(entry.get("claude_stderr") or ""),
            ]
            err = _truncate("\n".join(p for p in err_parts if p), 4000)
            if not err:
                err = "(failure logged without evaluator/stderr text)"
            fix = fix_for_failure(entry)
            doc = self.build_document_text(desc, err, fix)
            lid = stable_id(f"hist|{tid}|{entry.get('attempt')}|{entry.get('timestamp')}")
            self.upsert_lesson(
                lesson_id=lid,
                document_text=doc,
                task_id=tid,
                task_description=desc or tid,
                error=err,
                fix=fix,
            )
            count += 1

        for tr in trajectories:
            tid = str(tr.get("task_id") or "UNKNOWN")
            prompt = str(tr.get("input") or "")
            desc = extract_description_from_prompt(prompt) or plan_map.get(tid, "")
            err = extract_previous_failure_block(prompt)
            if not err.strip():
                err = "(No PREVIOUS FAILURE block — likely first-attempt success.)"
            fix = _truncate(str(tr.get("output_git_diff") or ""), 6000)
            doc = self.build_document_text(desc, err, fix)
            ts = str(tr.get("timestamp") or "")
            lid = stable_id(f"jsonl|{tid}|{ts}|{prompt[:800]}")
            self.upsert_lesson(
                lesson_id=lid,
                document_text=doc,
                task_id=tid,
                task_description=desc or tid,
                error=err,
                fix=fix,
            )
            count += 1

        return count


def format_wisdom_block(lessons: list[dict[str, str]]) -> list[str]:
    """Markdown lines for PromptGenerator (Lessons from Experience)."""
    if not lessons:
        return []
    lines = [
        "",
        "---",
        "",
        "## Lessons from Experience (Level 5)",
        "",
        "Semantic recall from similar past tasks. Apply these patterns; do not repeat known mistakes.",
        "",
    ]
    for i, les in enumerate(lessons, start=1):
        err = les.get("error") or "(unknown error)"
        fix = les.get("fix") or "(unknown fix)"
        lines.append(
            f"{i}. In the past, when performing similar tasks, we encountered **{_truncate(err, 500)}**. "
            f"We solved it by **{_truncate(fix, 500)}**. "
            f"Do not repeat the mistake of {_truncate(err, 280)}."
        )
        lines.append("")
    return lines


def maybe_wisdom_rag(
    enabled: bool,
    store_path: Path,
    factory: Callable[[Path], WisdomRAG] = WisdomRAG,
) -> Optional[WisdomRAG]:
    """Construct WisdomRAG or return None if disabled."""
    if not enabled:
        return None
    store_path = Path(store_path)
    store_path.mkdir(parents=True, exist_ok=True)
    return factory(store_path)
