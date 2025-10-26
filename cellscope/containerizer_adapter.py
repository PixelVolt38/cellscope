
"""
Adapter for NaaVRE Component Containerizer I/O Detector.

This module defines a thin client that can send a code snippet to the I/O Detector
service and receive inferred read/write sets and simple defs/uses for R code.
The actual endpoint URL and payload are configurable; by default we look for
the CELLSCOPE_CONTAINERIZER_URL environment variable.

The expected response schema is intentionally simple:

{
  "reads": ["path1", "path2", ...],
  "writes": ["path3", ...],
  "defs": ["var1", "var2"],
  "uses": ["varA", "varB"]
}

If the service is unavailable the adapter fails soft and returns empty sets.
"""
from __future__ import annotations
import os
import json
from typing import Dict, Any, Tuple, Set
try:
    import requests
except Exception:  # pragma: no cover
    requests = None

DEFAULT_URL = os.environ.get("CELLSCOPE_CONTAINERIZER_URL", "").rstrip("/")

def analyze_r_cell(code: str, timeout: int = 10) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """Return (defs, uses, writes, reads) for the given R code using the I/O detector.
    If the detector is not configured or fails, returns empty sets.
    """
    if not DEFAULT_URL or requests is None:
        return set(), set(), set(), set()
    try:
        payload = { "language": "R", "code": code }
        resp = requests.post(f"{DEFAULT_URL}/analyze", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json() or {}
        reads = set(map(str, data.get("reads", []) or []))
        writes = set(map(str, data.get("writes", []) or []))
        defs = set(map(str, data.get("defs", []) or []))
        uses = set(map(str, data.get("uses", []) or []))
        return defs, uses, writes, reads
    except Exception:
        return set(), set(), set(), set()
