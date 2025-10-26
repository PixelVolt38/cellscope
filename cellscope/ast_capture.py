import os
import ast
import nbformat
from .containerizer_adapter import analyze_r_cell
from typing import Dict, List, Set, Any, Optional

class CellInfo:
    def __init__(self, idx: int, kernel: str, source: str):
        self.idx = idx
        self.kernel = kernel or "python"
        self.source = source or ""
        self.funcs: Set[str] = set()
        self.func_calls: Set[str] = set()
        self.var_defs: Set[str] = set()
        self.var_uses: Set[str] = set()
        # SoS
        self.sos_put: Set[str] = set()
        self.sos_get: Set[str] = set()
        # Materialized I/O (simple heuristics)
        self.file_writes: Set[str] = set()
        self.file_reads: Set[str] = set()

def _kernel_for_cell(nb, cell) -> str:
    # SoS notebooks put kernel in cell.metadata.kernel
    k = (getattr(cell, 'metadata', {}) or {}).get('kernel')
    if k:
        return str(k)
    # fallback to notebook kernelspec
    ks = (nb.metadata.get('kernelspec') or {}).get('name')
    return str(ks or 'python3')

def _detect_sos_magics(lines: List[str]) -> (Set[str], Set[str]):
    # VERY simple parser for lines like: %put var1 var2   and %get var1
    puts, gets = set(), set()
    for ln in lines:
        s = ln.strip()
        if s.startswith('%put '):
            puts.update(x for x in s[5:].split() if x.isidentifier())
        elif s.startswith('%get '):
            gets.update(x for x in s[5:].split() if x.isidentifier())
    return puts, gets

def _is_string(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)

def _literal_str(arg):
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None

def _collect_file_io(tree: ast.AST) -> (Set[str], Set[str]):
    writes, reads = set(), set()
    # Heuristics: open('file','w'), to_csv('file'), to_parquet('file'), to_netcdf('file')
    for n in (ast.walk(tree) if tree is not None else []):
        if isinstance(n, ast.Call):
            # open(filename, mode)
            if isinstance(n.func, ast.Name) and n.func.id == 'open':
                if len(n.args) >= 1 and _is_string(n.args[0]):
                    fname = _literal_str(n.args[0])
                    mode = None
                    if len(n.args) >= 2 and _is_string(n.args[1]):
                        mode = _literal_str(n.args[1])
                    if fname:
                        if mode and any(m in mode for m in ('w', 'a')):
                            writes.add(fname)
                        else:
                            reads.add(fname)
            # obj.to_csv('file') / to_parquet / to_netcdf
            if isinstance(n.func, ast.Attribute) and _is_string(n.args[0]) if n.args else False:
                method = n.func.attr
                fname = _literal_str(n.args[0])
                if method in ('to_csv', 'to_parquet', 'to_netcdf', 'to_json', 'to_feather', 'to_excel') and fname:
                    writes.add(fname)
            # pandas.read_csv('file'), xarray.open_dataset('file'), etc.
            if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
                if n.func.value.id in ('pd', 'pandas', 'xr', 'xarray'):
                    method = n.func.attr
                    if n.args and _is_string(n.args[0]):
                        fname = _literal_str(n.args[0])
                        if fname and method in ('read_csv', 'read_json', 'read_parquet', 'read_excel', 'open_dataset'):
                            reads.add(fname)
    # Normalize windows paths like "C:\\..." and relative
    def norm(p): 
        try:
            return os.path.normpath(p)
        except Exception:
            return p
    return {norm(p) for p in writes}, {norm(p) for p in reads}

def parse_notebook(nb_path: str, alias_map: Optional[Dict[str, str]] = None, collect_materialized: bool = True) -> Dict[str, Any]:
    """
    Returns a capture dict:
    {
      'nb_path': str,
      'cells': List[CellInfo],
      'graph': {'defs': {var -> last_def_idx}, 'edges': [(u,v,{'type':'uses','vars':set(...)}), ...]},
    }
    """
    nb = nbformat.read(nb_path, as_version=4)
    code_cells = [c for c in nb.cells if c.cell_type == 'code']

    cells: List[CellInfo] = []
    last_def: Dict[str, int] = {}
    edges: List[tuple] = []

    for i, c in enumerate(code_cells):
        info = CellInfo(i, _kernel_for_cell(nb, c), c.source or "")
        # SoS
        puts, gets = _detect_sos_magics(info.source.splitlines())
        info.sos_put |= puts
        info.sos_get |= gets

        try:
            if str(info.kernel).lower().startswith(('ir', 'r-', 'r')):
                # Ask containerizer adapter for R cell analysis (defs, uses, writes, reads)
                defs_r, uses_r, writes_r, reads_r = analyze_r_cell(info.source)
                info.var_defs |= set(defs_r)
                info.var_uses |= set(uses_r)
                info.file_writes |= set(writes_r)
                info.file_reads  |= set(reads_r)
                tree = None
            else:
                tree = ast.parse(info.source)
        except Exception:
            # keep empty sets on parse failure
            cells.append(info)
            continue

        # function defs
        info.funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        func_calls = set()
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    func_calls.add(node.func.id)

        # variable defs: assignment targets (simple heuristic)
        defs = set()
        for n in (ast.walk(tree) if tree is not None else []):
            if isinstance(n, ast.Assign):
                for tgt in n.targets:
                    for nm in ast.walk(tgt):
                        if isinstance(nm, ast.Name):
                            defs.add(nm.id)
        # uses: Name/Load (excluding same-cell defs/functions)
        uses = {
            n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        } - (defs | info.funcs)

        # alias normalization
        if alias_map:
            defs = {alias_map.get(v, v) for v in defs}
            uses = {alias_map.get(v, v) for v in uses}
            puts = {alias_map.get(v, v) for v in puts}
            gets = {alias_map.get(v, v) for v in gets}
            info.funcs = {alias_map.get(v, v) for v in info.funcs}
            func_calls = {alias_map.get(v, v) for v in func_calls}

        func_calls -= info.funcs
        func_calls &= uses

        defs |= info.funcs
        info.var_defs = defs
        info.var_uses = uses
        info.func_calls = func_calls
        if collect_materialized:
            w, r = _collect_file_io(tree) if tree is not None else (set(), set())
            info.file_writes |= w
            info.file_reads |= r

        # add edges by last_def
        for v in uses:
            if v in last_def:
                edges.append((last_def[v], i, {'type': 'uses', 'vars': {v}}))
        # update last_def
        for v in defs:
            last_def[v] = i

        cells.append(info)

    return {'nb_path': nb_path, 'cells': cells, 'graph': {'edges': edges}}
