
"""
Lightweight static analysis for R cells.

CellScope previously delegated R parsing to the external Component
Containerizer I/O Detector. To keep the project portable across any
JupyterLab environment we now implement a small, best-effort analyzer
that mirrors the Python AST heuristics: collect assignment targets,
approximate variable uses, and detect common file read/write calls.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

IDENT_RE = re.compile(r"\b[.A-Za-z][\w.]*\b")
LEFT_ASSIGN_RE = re.compile(r"\b([.A-Za-z][\w.]*)\s*(?:<-|(?<![<>=!])=)")
RIGHT_ASSIGN_RE = re.compile(r"([.A-Za-z][\w.]*)\s*->\s*([.A-Za-z][\w.]*)")
FUNC_CALL_RE = re.compile(r"([A-Za-z.][\w.]*)\s*\(")

KEYWORDS = {
    "if",
    "else",
    "repeat",
    "while",
    "function",
    "for",
    "in",
    "next",
    "break",
    "TRUE",
    "FALSE",
    "NULL",
    "Inf",
    "NaN",
    "NA",
    "NA_integer_",
    "NA_real_",
    "NA_complex_",
    "NA_character_",
    "...",
    "c",
    "read.csv",
    "read.csv2",
    "read.table",
    "read.delim",
    "readRDS",
    "readLines",
    "read_feather",
    "write.csv",
    "write.csv2",
    "write.table",
    "write.delim",
    "writeLines",
    "write_feather",
    "saveRDS",
    "save",
    "load",
}

# Common read/write functions and which positional argument typically holds the path.
READ_CALLS = {
    "read.csv": {"fallback_index": 0},
    "read.csv2": {"fallback_index": 0},
    "read.table": {"fallback_index": 0},
    "read.delim": {"fallback_index": 0},
    "read_tsv": {"fallback_index": 0},
    "read_csv": {"fallback_index": 0},
    "read_tsv2": {"fallback_index": 0},
    "readRDS": {"fallback_index": 0},
    "load": {"fallback_index": 0},
    "readLines": {"fallback_index": 0},
    "read_feather": {"fallback_index": 0},
    "download.file": {"fallback_index": 0},
}

WRITE_CALLS = {
    "write.csv": {"fallback_index": 1},
    "write.csv2": {"fallback_index": 1},
    "write.table": {"fallback_index": 1},
    "write.delim": {"fallback_index": 1},
    "write_csv": {"fallback_index": 1},
    "write_tsv": {"fallback_index": 1},
    "writeLines": {"fallback_index": 1},
    "saveRDS": {"fallback_index": 1},
    "save": {"fallback_index": 1},
    "write_feather": {"fallback_index": 1},
    "download.file": {"fallback_index": 1},
}

FILE_ARG_NAMES = ("file", "path", "con", "destfile")


def analyze_r_cell(code: str, timeout: int = 10) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """Return (defs, uses, writes, reads) for a block of R code."""
    scrubbed = _strip_comments(code or "")
    defs = _extract_definitions(scrubbed)
    uses = _extract_uses(scrubbed, defs)
    writes = _extract_file_operations(scrubbed, WRITE_CALLS)
    reads = _extract_file_operations(scrubbed, READ_CALLS)
    return defs, uses, writes, reads


def _strip_comments(code: str) -> str:
    lines = []
    for line in code.splitlines():
        idx = line.find("#")
        if idx >= 0:
            lines.append(line[:idx])
        else:
            lines.append(line)
    return "\n".join(lines)


def _extract_definitions(code: str) -> Set[str]:
    defs: Set[str] = set()
    for match in LEFT_ASSIGN_RE.finditer(code):
        if _is_named_argument(code, match.start()):
            continue
        defs.add(match.group(1))
    defs.update(match.group(2) for match in RIGHT_ASSIGN_RE.finditer(code))
    return {d for d in defs if d and d not in KEYWORDS}


def _extract_uses(code: str, defs: Set[str]) -> Set[str]:
    sanitized = _remove_string_literals(code)
    tokens: Set[str] = set()
    for match in IDENT_RE.finditer(sanitized):
        token = match.group(0)
        if not token or token[0].isdigit():
            continue
        if _is_named_argument(sanitized, match.start()):
            continue
        tokens.add(token)
    return {tok for tok in tokens if tok not in defs and tok not in KEYWORDS}


def _extract_file_operations(code: str, call_specs: Optional[dict]) -> Set[str]:
    if not call_specs:
        return set()
    paths: Set[str] = set()
    func_names = set(call_specs.keys())
    for name, arg_string in _iter_calls(code, func_names):
        spec = call_specs.get(name) or {}
        args = _split_args(arg_string)
        literal = _resolve_path_from_args(args, preferred=FILE_ARG_NAMES, fallback_index=spec.get("fallback_index"))
        if literal:
            if literal.startswith("http://") or literal.startswith("https://"):
                paths.add(literal)
            else:
                paths.add(os.path.normpath(literal))
    return paths


def _iter_calls(code: str, func_names: Set[str]) -> Iterable[Tuple[str, str]]:
    idx = 0
    length = len(code)
    while idx < length:
        match = FUNC_CALL_RE.search(code, idx)
        if not match:
            break
        name = match.group(1)
        idx = match.end() - 1  # points to '('
        if name not in func_names:
            continue
        arg_string, end = _collect_parenthesized(code, idx)
        if arg_string is not None:
            yield name, arg_string
            idx = end
        else:
            idx = match.end()


def _collect_parenthesized(text: str, open_index: int) -> Tuple[Optional[str], int]:
    depth = 0
    start = open_index + 1
    i = open_index
    length = len(text)
    while i < length:
        ch = text[i]
        if ch in ("'", '"'):
            i = _skip_string(text, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return None, length


def _skip_string(text: str, start: int) -> int:
    quote = text[start]
    i = start + 1
    length = len(text)
    while i < length:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == quote:
            return i + 1
        i += 1
    return length


def _split_args(arg_string: str) -> List[str]:
    args: List[str] = []
    current: List[str] = []
    depth = 0
    i = 0
    length = len(arg_string)
    while i < length:
        ch = arg_string[i]
        if ch in ("'", '"'):
            next_i = _skip_string(arg_string, i)
            current.append(arg_string[i:next_i])
            i = next_i
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            arg = "".join(current).strip()
            if arg:
                args.append(arg)
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def _resolve_path_from_args(args: Sequence[str], preferred: Sequence[str], fallback_index: Optional[int]) -> Optional[str]:
    named = {}
    positional: List[str] = []
    for arg in args:
        if "=" in arg:
            name, value = arg.split("=", 1)
            named[name.strip()] = value.strip()
        else:
            positional.append(arg.strip())

    for key in preferred:
        literal = _string_literal(named.get(key))
        if literal:
            return literal

    if fallback_index is None:
        return None
    if fallback_index < len(positional):
        literal = _string_literal(positional[fallback_index])
        if literal:
            return literal
    return None


def _string_literal(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        inner = value[1:-1]
        try:
            return bytes(inner, "utf-8").decode("unicode_escape") or inner
        except Exception:
            return inner
    return None


def _remove_string_literals(text: str) -> str:
    if not text:
        return text
    result: List[str] = []
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if ch in ("'", '"'):
            end = _skip_string(text, i)
            result.append(" ")
            i = end
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def _is_named_argument(code: str, index: int) -> bool:
    i = index - 1
    while i >= 0 and code[i].isspace():
        i -= 1
    if i < 0:
        return False
    # Treat assignments that immediately follow "(" or "," as named arguments in a call.
    return code[i] in {"(", ","}
