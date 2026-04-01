"""ProjectMapper — scan workspace for TS/JS exports and imports; emit .project_map.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


SCAN_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
EXCLUDE_DIR_NAMES = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".next",
    "coverage",
    "__pycache__",
    ".venv",
    "venv",
}

# --- export patterns (line-oriented heuristics) ---
_RE_EXPORT_FN = re.compile(r"^\s*export\s+(?:async\s+)?function\s+(\w+)", re.MULTILINE)
_RE_EXPORT_CLASS = re.compile(r"^\s*export\s+class\s+(\w+)", re.MULTILINE)
_RE_EXPORT_IFACE = re.compile(r"^\s*export\s+interface\s+(\w+)", re.MULTILINE)
_RE_EXPORT_TYPE = re.compile(r"^\s*export\s+type\s+(\w+)", re.MULTILINE)
_RE_EXPORT_ENUM = re.compile(r"^\s*export\s+enum\s+(\w+)", re.MULTILINE)
_RE_EXPORT_CONST = re.compile(r"^\s*export\s+const\s+(\w+)", re.MULTILINE)
_RE_EXPORT_NAMED = re.compile(r"^\s*export\s*\{([^}]+)\}", re.MULTILINE)
_RE_EXPORT_DEFAULT = re.compile(r"^\s*export\s+default\b", re.MULTILINE)

_RE_IMPORT_NAMED = re.compile(
    r"""import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]"""
)
_RE_IMPORT_DEFAULT = re.compile(
    r"""import\s+type\s+(\w+)\s+from\s+['"]([^'"]+)['"]"""
)
_RE_IMPORT_DEFAULT_VALUE = re.compile(
    r"""import\s+(?!type\s)(?!\{)(?:(\w+)|\*\s+as\s+(\w+))\s+from\s+['"]([^'"]+)['"]"""
)
_RE_IMPORT_SIDE = re.compile(r"""import\s+['"]([^'"]+)['"]""")


def _norm_rel(path: Path, workspace: Path) -> str:
    return str(path.resolve().relative_to(workspace.resolve())).replace("\\", "/")


def _try_resolve_module_path(spec: str, from_dir: Path, workspace: Path) -> Optional[Path]:
    """Map import specifier to an existing file under workspace (relative/dot imports and @/)."""
    spec = spec.strip()
    if spec.startswith("node:"):
        return None
    if not spec.startswith(".") and not spec.startswith("@/") and not spec.startswith("/"):
        # bare package name (e.g. react) — not workspace-local
        return None

    candidates: list[Path] = []
    if spec.startswith("@/"):
        rel = spec[2:].lstrip("/")
        base = workspace / rel
    elif spec.startswith("/"):
        base = workspace / spec.lstrip("/")
    else:
        base = (from_dir / spec).resolve()

    for ext in ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        p = Path(str(base) + ext) if ext else base
        if p.is_file():
            return p
    # directory index
    for name in ("index.ts", "index.tsx", "index.js", "index.jsx"):
        idx = base / name if base.suffix == "" else base.parent / name
        if idx.is_file():
            return idx
    return None


def _split_named_exports(inner: str) -> list[str]:
    names: list[str] = []
    for part in inner.split(","):
        part = part.strip()
        if not part:
            continue
        # `foo as bar` -> foo
        m = re.match(r"^(?:type\s+)?(\w+)(?:\s+as\s+\w+)?", part)
        if m:
            names.append(m.group(1))
    return names


def _parse_exports(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for name in _RE_EXPORT_FN.findall(text):
        out.append({"name": name, "kind": "function"})
    for name in _RE_EXPORT_CLASS.findall(text):
        out.append({"name": name, "kind": "class"})
    for name in _RE_EXPORT_IFACE.findall(text):
        out.append({"name": name, "kind": "interface"})
    for name in _RE_EXPORT_TYPE.findall(text):
        out.append({"name": name, "kind": "type"})
    for name in _RE_EXPORT_ENUM.findall(text):
        out.append({"name": name, "kind": "enum"})
    for name in _RE_EXPORT_CONST.findall(text):
        out.append({"name": name, "kind": "const"})
    for block in _RE_EXPORT_NAMED.findall(text):
        for n in _split_named_exports(block):
            out.append({"name": n, "kind": "named"})
    if _RE_EXPORT_DEFAULT.search(text):
        out.append({"name": "default", "kind": "default"})
    # Dedupe by name+kind
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for e in out:
        k = (e["name"], e["kind"])
        if k not in seen:
            seen.add(k)
            deduped.append(e)
    return deduped


def _parse_imports(text: str, from_file: Path, workspace: Path) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []
    from_dir = from_file.parent

    def _add(spec: str, names: list[str]) -> None:
        resolved = _try_resolve_module_path(spec, from_dir, workspace)
        imports.append(
            {
                "spec": spec,
                "resolved": _norm_rel(resolved, workspace) if resolved else None,
                "names": names,
            }
        )

    for m in _RE_IMPORT_NAMED.finditer(text):
        names_raw, spec = m.group(1), m.group(2)
        _add(spec, _split_named_exports(names_raw))

    for m in _RE_IMPORT_DEFAULT.finditer(text):
        spec = m.group(2)
        _add(spec, [m.group(1)])

    for m in _RE_IMPORT_DEFAULT_VALUE.finditer(text):
        default_name, star_as, spec = m.group(1), m.group(2), m.group(3)
        nm = default_name or star_as
        if nm:
            _add(spec, [nm])

    for m in _RE_IMPORT_SIDE.finditer(text):
        spec = m.group(1)
        if spec.startswith(".") or spec.startswith("@/"):
            _add(spec, [])

    return imports


@dataclass
class ProjectMap:
    """In-memory project graph."""

    workspace: Path
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    reverse_deps: dict[str, list[str]] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "workspace_root": str(self.workspace.resolve()),
            "files": self.files,
            "reverse_deps": self.reverse_deps,
        }


class ProjectMapper:
    """Scan workspace for TS/JS sources and build an export/import dependency graph."""

    OUTPUT_NAME = ".project_map.json"

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir.resolve()

    def scan(self) -> ProjectMap:
        """Parse all source files and compute reverse dependency index."""
        pm = ProjectMap(workspace=self.workspace_dir)
        for path in self._iter_source_files():
            rel = _norm_rel(path, self.workspace_dir)
            text = path.read_text(encoding="utf-8", errors="replace")
            exports = _parse_exports(text)
            imports = _parse_imports(text, path, self.workspace_dir)
            pm.files[rel] = {"exports": exports, "imports": imports}

        # reverse: target -> [files that import target]
        rev: dict[str, set[str]] = {}
        for rel, info in pm.files.items():
            for imp in info.get("imports", []):
                target = imp.get("resolved")
                if not target:
                    continue
                rev.setdefault(target, set()).add(rel)

        pm.reverse_deps = {k: sorted(v) for k, v in sorted(rev.items())}
        return pm

    def scan_and_write(self) -> ProjectMap:
        """Scan and write ``workspace/.project_map.json``."""
        pm = self.scan()
        out_path = self.workspace_dir / self.OUTPUT_NAME
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(pm.to_json_dict(), indent=2), encoding="utf-8")
        return pm

    def _iter_source_files(self):
        for p in self.workspace_dir.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in SCAN_EXTENSIONS:
                continue
            if any(part in EXCLUDE_DIR_NAMES for part in p.parts):
                continue
            yield p


# --- Impact analysis (task text → direct files → dependents) ---

_TASK_PATH_RE = re.compile(
    r"\b((?:[\w@.-]+/)*[\w@.-]+\.(?:ts|tsx|js|jsx|mjs|cjs))\b"
)


def direct_files_from_task(description: str, workspace: Path) -> list[str]:
    """Heuristic: paths in task text that exist under workspace."""
    ws = workspace.resolve()
    found: set[str] = set()
    for m in _TASK_PATH_RE.finditer(description):
        raw = m.group(1).strip()
        if raw.startswith("./"):
            raw = raw[2:]
        candidate = ws / raw
        if candidate.is_file():
            found.add(str(candidate.relative_to(ws)).replace("\\", "/"))
    return sorted(found)


def impacted_files(direct: list[str], project_map: ProjectMap) -> list[str]:
    """One-hop dependents: files that import from any direct file."""
    impacted: set[str] = set()
    for d in direct:
        for dep in project_map.reverse_deps.get(d, []):
            if dep not in direct:
                impacted.add(dep)
    return sorted(impacted)


# --- Dependency pruning (large project_map.json → task-local neighborhood) ---

PROJECT_MAP_LINE_THRESHOLD = 500

_PLAN_TASK_LINE_RE = re.compile(r"^- \[([ x])\] (TASK_\d+): (.+)$")


def count_project_map_lines(project_map_path: Path) -> int:
    """Line count of ``.project_map.json`` (used for prompt size threshold)."""
    if not project_map_path.is_file():
        return 0
    return len(project_map_path.read_text(encoding="utf-8").splitlines())


def task_description_for_task_id(plan_file: Path, task_id: str) -> Optional[str]:
    """Return the description segment for ``task_id`` from PLAN.md, if present."""
    if not plan_file.is_file():
        return None
    for line in plan_file.read_text(encoding="utf-8").splitlines():
        m = _PLAN_TASK_LINE_RE.match(line.strip())
        if m and m.group(2) == task_id:
            return m.group(3).strip()
    return None


def _neighborhood_for_seeds(
    seed_files: list[str],
    files: dict[str, Any],
    reverse_deps: dict[str, list[str]],
) -> list[str]:
    """1-hop neighborhood: seeds + their import targets + their dependents (sorted, deterministic)."""
    known = set(files.keys())
    seeds = sorted({s for s in seed_files if s in known})
    neighborhood: set[str] = set(seeds)

    for f in seeds:
        for imp in files.get(f, {}).get("imports", []):
            r = imp.get("resolved")
            if r and r in known:
                neighborhood.add(r)
        for dep in reverse_deps.get(f, []):
            if dep in known:
                neighborhood.add(dep)

    return sorted(neighborhood)


def dependency_pruning(
    task_id: str,
    *,
    plan_file: Path,
    workspace: Path,
    project_map: dict[str, Any],
    fallback_description: Optional[str] = None,
) -> dict[str, Any]:
    """Extract a deterministic 1-hop sub-graph for the task (AIRE: same inputs → same output).

    Seeds come from file paths in the PLAN line for ``task_id``. If that line is missing,
    ``fallback_description`` (e.g. current task description from the orchestrator) is used.
    """
    desc = task_description_for_task_id(plan_file, task_id)
    if not desc and fallback_description:
        desc = fallback_description
    if not desc:
        desc = ""

    seed_files = direct_files_from_task(desc, workspace.resolve())
    files = project_map.get("files") or {}
    if not isinstance(files, dict):
        files = {}
    reverse_deps = project_map.get("reverse_deps") or {}
    if not isinstance(reverse_deps, dict):
        reverse_deps = {}

    neighborhood = _neighborhood_for_seeds(seed_files, files, reverse_deps)

    pruned_files: dict[str, Any] = {k: files[k] for k in neighborhood if k in files}
    pruned_reverse: dict[str, list[str]] = {}
    for k in neighborhood:
        if k not in reverse_deps:
            continue
        vals = sorted({v for v in reverse_deps[k] if v in neighborhood})
        if vals:
            pruned_reverse[k] = vals

    return {
        "pruned": True,
        "task_id": task_id,
        "seed_files": sorted(seed_files),
        "neighborhood_files": sorted(neighborhood),
        "version": project_map.get("version"),
        "workspace_root": project_map.get("workspace_root"),
        "files": pruned_files,
        "reverse_deps": pruned_reverse,
    }


def dumps_project_map_deterministic(data: dict[str, Any]) -> str:
    """Stable JSON text for prompts (sorted keys, stable ordering)."""
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)


@dataclass
class SituationalContext:
    """Level-4 situational awareness for prompt injection."""

    direct_files: list[str]
    impacted_files: list[str]

    @property
    def primary_file(self) -> str:
        if self.direct_files:
            return self.direct_files[0]
        return "(no file paths detected in task text)"
