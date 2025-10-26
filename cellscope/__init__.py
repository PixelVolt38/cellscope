"""CellScope core library.

Key entry points:
- parse_notebook (capture)
- build_rocrate (packaging)
- visualize_rocrate (viewer)
- validate_crate (validation)

This package wraps the original `roshow` modules under a `cellscope` namespace.
"""
from .ast_capture import parse_notebook
from .cross_kernel import infer_cross_kernel_edges
from .rocrate_io import build_rocrate
from .visualize import visualize_rocrate
from .validate_crate import validate_crate
from .indexer import index_crate
