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
    if tree is None:
        return writes, reads

    # simple environment of name -> literal path value discovered in the cell
    env: Dict[str, str] = {}

    def _resolve_path(node: Optional[ast.AST]) -> Optional[str]:
        if node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = _resolve_path(node.left)
            right = _resolve_path(node.right)
            if left is not None and right is not None:
                return left + right
            return None
        if isinstance(node, ast.Call):
            # os.path.join(...)
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'join':
                parts = []
                for arg in node.args:
                    resolved = _resolve_path(arg)
                    if resolved is None:
                        return None
                    parts.append(resolved)
                if parts:
                    return os.path.join(*parts)
            # pathlib.Path('...')
            if isinstance(node.func, ast.Name) and node.func.id in {'Path', 'PurePath'}:
                if node.args:
                    return _resolve_path(node.args[0])
        return None

    if isinstance(tree, ast.Module):
        for stmt in tree.body:
            targets: List[ast.expr] = []
            value: Optional[ast.AST] = None
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and stmt.target is not None:
                targets = [stmt.target]
                value = stmt.value
            if not targets or value is None:
                continue
            resolved = _resolve_path(value)
            if resolved is None:
                continue
            for tgt in targets:
                if isinstance(tgt, ast.Name):
                    env[tgt.id] = resolved

    write_methods = {'to_csv', 'to_parquet', 'to_netcdf', 'to_json', 'to_feather', 'to_excel'}
    read_methods = {'read_csv', 'read_json', 'read_parquet', 'read_excel', 'open_dataset'}
    path_write_methods = {'write_text', 'write_bytes', 'write'}
    path_read_methods = {'read_text', 'read_bytes'}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # open(...)
        if isinstance(node.func, ast.Name) and node.func.id == 'open':
            fname = _resolve_path(node.args[0]) if node.args else None
            mode = _resolve_path(node.args[1]) if len(node.args) >= 2 else None
            if fname:
                if mode and any(m in str(mode) for m in ('w', 'a', '+')):
                    writes.add(fname)
                else:
                    reads.add(fname)
            continue

        if isinstance(node.func, ast.Attribute):
            method = node.func.attr
            target_obj = node.func.value

            if method in write_methods and node.args:
                fname = _resolve_path(node.args[0])
                if fname:
                    writes.add(fname)
                continue

            if method in read_methods and node.args:
                fname = _resolve_path(node.args[0])
                if fname:
                    reads.add(fname)
                continue

            if method in path_write_methods:
                fname = _resolve_path(target_obj)
                if fname:
                    writes.add(fname)
                continue

            if method in path_read_methods:
                fname = _resolve_path(target_obj)
                if fname:
                    reads.add(fname)
                continue

            # pandas / xarray read_*
            if isinstance(node.func.value, ast.Name) and node.func.value.id in {'pd', 'pandas', 'xr', 'xarray'}:
                if node.args:
                    fname = _resolve_path(node.args[0])
                    if fname and method in read_methods:
                        reads.add(fname)

    def norm(p: str) -> str:
        try:
            return os.path.normpath(p)
        except Exception:
            return p

    return {norm(p) for p in writes}, {norm(p) for p in reads}

def _sanitize_source(source: str) -> str:
    cleaned_lines = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('%') or stripped.startswith('!') or stripped.startswith('?'):
            cleaned_lines.append('')
        else:
            cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)


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
                tree = ast.parse(_sanitize_source(info.source))
        except Exception:
            # keep empty sets on parse failure
            cells.append(info)
            continue

        # function defs (skip when tree is unavailable e.g. R cells)
        if tree is not None:
            info.funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            func_calls = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    func_calls.add(node.func.id)
        else:
            info.funcs = set()
            func_calls = set()

        # variable defs: assignment targets (simple heuristic)
        defs = set()
        for n in (ast.walk(tree) if tree is not None else []):
            if isinstance(n, ast.Assign):
                for tgt in n.targets:
                    for nm in ast.walk(tgt):
                        if isinstance(nm, ast.Name):
                            defs.add(nm.id)
        # uses: Name/Load (excluding same-cell defs/functions)
        if tree is not None:
            uses = {
                n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
            } - (defs | info.funcs)
        else:
            uses = set()

        # alias normalization
        if alias_map:
            defs = {alias_map.get(v, v) for v in defs}
            uses = {alias_map.get(v, v) for v in uses}
            puts = {alias_map.get(v, v) for v in puts}
            gets = {alias_map.get(v, v) for v in gets}
            info.funcs = {alias_map.get(v, v) for v in info.funcs}
            func_calls = {alias_map.get(v, v) for v in func_calls}
            info.sos_put = {alias_map.get(v, v) for v in info.sos_put}
            info.sos_get = {alias_map.get(v, v) for v in info.sos_get}

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
