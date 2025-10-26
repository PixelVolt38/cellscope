import os
from typing import Dict, Any, List, Tuple

def infer_cross_kernel_edges(capture: Dict[str, Any]) -> List[Tuple[int, int, Dict[str, Any]]]:
    """
    Infer edges due to SoS %put/%get across different kernels and
    file hand-offs (cell writes file; later cell reads same file).
    Returns list of edges: (u, v, {'type': 'uses', 'vars': set([...]), 'via': 'sos'|'file'})
    """
    cells = capture['cells']
    edges: List[Tuple[int, int, Dict[str, Any]]] = []

    # SoS (%put -> %get) across DIFFERENT kernels
    # naive strategy: if cell i has %put X and a later cell j (j>i) has %get X and kernel differs
    for i, ci in enumerate(cells):
        if not ci.sos_put:
            continue
        for j in range(i + 1, len(cells)):
            cj = cells[j]
            overlap = ci.sos_put & cj.sos_get
            if overlap and (ci.kernel != cj.kernel):
                edges.append((i, j, {'type': 'uses', 'vars': set(overlap), 'via': 'sos'}))

    # File hand-offs: if a cell writes file F and a later cell reads the same F
    write_map: Dict[str, int] = {}
    for i, ci in enumerate(cells):
        for f in ci.file_writes:
            write_map[f] = i
        for f in ci.file_reads:
            if f in write_map:
                u = write_map[f]
                if u < i:
                    edges.append((u, i, {'type': 'uses', 'vars': {os.path.basename(f)}, 'via': 'file', 'file': f}))
    return edges
