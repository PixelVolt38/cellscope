import os
import html
import json
import networkx as nx
from rocrate.rocrate import ROCrate

try:
    from pyvis.network import Network
    PYVIS_AVAILABLE = True
except ImportError:
    PYVIS_AVAILABLE = False

def _inject_roshow_panel(html_path: str) -> None:
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            src = f.read()
        css = """
<style>
.roshow-panel{position:absolute;background:#fff;border:1px solid #ccc;box-shadow:0 6px 18px rgba(0,0,0,.18);padding:10px;max-width:560px;z-index:9999;border-radius:6px;font-family:sans-serif;font-size:13px;line-height:1.35}
.roshow-panel .hdr{font-weight:600;margin:0 0 6px}
.roshow-panel .sec{margin:6px 0}
.roshow-panel .roshow-code{margin:4px 0;background:#f6f8fa;border:1px solid #ddd;padding:8px;max-height:240px;overflow:auto;white-space:pre-wrap}
</style>
"""
        js = """
<script>
(function(){
  if (typeof network === 'undefined' || typeof nodes === 'undefined') { return; }
  var panel = document.createElement('div');
  panel.className = 'roshow-panel';
  panel.style.display = 'none';
  var container = document.getElementById('mynetwork') || document.querySelector('div[id$=mynetwork]') || document.body;
  container.appendChild(panel);
  var pinned = null;

  function renderNode(n){
    panel.innerHTML = "<div class='hdr'>" + (n.label || 'Cell') + "</div>"
                      + "<div class='sec'><b>Code:</b>" + (n.snippet || '') + "</div>"
                      + "<div class='sec'><b>Metadata:</b>" + (n.meta || "<div><i>(none)</i></div>") + "</div>";
  }

  function renderEdge(edge){
    var fromLabel = edge.from;
    var toLabel = edge.to;
    try { var fromNode = nodes.get(edge.from); if (fromNode && fromNode.label) { fromLabel = fromNode.label; } } catch (e) {}
    try { var toNode = nodes.get(edge.to); if (toNode && toNode.label) { toLabel = toNode.label; } } catch (e) {}
    var rows = [];
    if (edge.dep_label) { rows.push("<div><b>Relation:</b> " + edge.dep_label + "</div>"); }
    if (edge.via) { rows.push("<div><b>Via:</b> " + edge.via + "</div>"); }
    if (edge.title && !rows.length) { rows.push("<div><b>Label:</b> " + edge.title + "</div>"); }
    var meta = rows.join('') || "<div><i>(none)</i></div>";
    panel.innerHTML = "<div class='hdr'>Dependency</div>"
                      + "<div class='sec'><b>From:</b> " + fromLabel + "</div>"
                      + "<div class='sec'><b>To:</b> " + toLabel + "</div>"
                      + "<div class='sec'><b>Metadata:</b>" + meta + "</div>";
  }

  function position(pointer){
    if (!pointer || !pointer.DOM) { return; }
    panel.style.left = (pointer.DOM.x + 12) + 'px';
    panel.style.top  = (pointer.DOM.y + 12) + 'px';
  }

  function showNode(n, pointer, pin){
    if (!n) { return; }
    pinned = pin ? { type: 'node', id: n.id } : null;
    renderNode(n);
    position(pointer);
    panel.style.display = 'block';
  }

  function showEdge(edge, pointer, pin){
    if (!edge) { return; }
    pinned = pin ? { type: 'edge', id: edge.id } : null;
    renderEdge(edge);
    position(pointer);
    panel.style.display = 'block';
  }

  function isPinned(){
    return pinned !== null;
  }

  function hide(force){
    if (!force && isPinned()) { return; }
    pinned = null;
    panel.style.display = 'none';
  }

  network.on('hoverNode', function(params){
    if (isPinned()) { return; }
    var n = null;
    try { n = nodes.get(params.node); } catch (e) { n = null; }
    if (!n) { return; }
    showNode(n, params.pointer, false);
  });

  network.on('blurNode', function(){
    hide(false);
  });

  network.on('hoverEdge', function(params){
    if (isPinned()) { return; }
    var edge = null;
    try { edge = edges.get(params.edge); } catch (e) { edge = null; }
    if (!edge) { return; }
    showEdge(edge, params.pointer, false);
  });

  network.on('blurEdge', function(){
    hide(false);
  });

  network.on('click', function(params){
    if (params.nodes && params.nodes.length) {
      var n = null;
      try { n = nodes.get(params.nodes[0]); } catch (e) { n = null; }
      if (!n) { return; }
      showNode(n, params.pointer, true);
      return;
    }
    if (params.edges && params.edges.length) {
      var edge = null;
      try { edge = edges.get(params.edges[0]); } catch (e) { edge = null; }
      if (!edge) { return; }
      showEdge(edge, params.pointer, true);
      return;
    }
    hide(true);
  });
})();
</script>
"""

        out = src.replace('</body>', css + js + '</body>')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(out)
    except Exception:
        pass

def visualize_rocrate(crate_dir: str, snippet_lines: int = 25, html_tooltips: bool = False, panel: bool = True) -> None:
    if not PYVIS_AVAILABLE:
        print("Install pyvis to generate interactive graph (pip install pyvis)")
        return

    crate = ROCrate(crate_dir)
    net = Network(height='600px', width='100%', directed=True)

    # Activities (cells)
    for entity in crate.get_entities():
        props = entity.properties().copy()
        t = props.get('@type')
        is_oflow = (isinstance(t, str) and t == 'https://example.org/ontology/ontoflow#Activity') or \
                   (isinstance(t, list) and 'https://example.org/ontology/ontoflow#Activity' in t)
        if not is_oflow:
            continue

        cid = None
        fid = getattr(entity, 'id', '')
        if isinstance(fid, str):
            try:
                base = os.path.basename(fid)
                if base.startswith('cell_') and '_' in base:
                    cid = int(base.split('_')[1].split('.')[0])
            except Exception:
                cid = None
        if cid is None:
            name_val = props.get('name', 'cell_0')
            try:
                cid = int(str(name_val).rsplit('_', 1)[-1])
            except Exception:
                cid = 0

        # read code from file
        code = ''
        fid = getattr(entity, 'id', '')
        if isinstance(fid, str) and not fid.startswith('#'):
            fpath = os.path.join(crate_dir, fid)
            if os.path.exists(fpath):
                with open(fpath, 'r', encoding='utf-8') as f:
                    code = f.read()

        code_lines = code.rstrip().splitlines()
        truncated = len(code_lines) > snippet_lines
        shown = code_lines[:snippet_lines] if truncated else code_lines

        esc_code = html.escape("\n".join(shown))
        snippet_html = (
            "<pre class='roshow-code'>" + esc_code + ("\\n…" if truncated else "") + "</pre>"
        )

        # metadata (except id/type/name)
        meta_rows = []
        for k, v in props.items():
            if k in ('@id','@type','name'):
                continue
            if isinstance(v, (list, tuple)):
                v = ', '.join(map(str, v))
            elif isinstance(v, dict):
                v = ', '.join(f"{kk}:{vv}" for kk, vv in v.items())
            meta_rows.append(f"<div><b>{html.escape(str(k))}:</b> {html.escape(str(v))}</div>")
        meta_html = ''.join(meta_rows) or '<div><i>(none)</i></div>'

        label_value = props.get('name') or f'cell_{cid}'

        if html_tooltips:
            tooltip = (
                f"<div style='font-family:sans-serif;max-width:520px'>"
                f"<b>{html.escape(str(label_value))}</b><br>"
                f"<b>Code{' (truncated)' if truncated else ''}:</b>"
                f"{snippet_html}"
                f"<b>Metadata:</b>{meta_html}"
                f"</div>"
            )
            node_kwargs = dict(label=label_value, title=tooltip, snippet=snippet_html, meta=meta_html)
        else:
            node_kwargs = dict(label=label_value, snippet=snippet_html, meta=meta_html)

        net.add_node(cid, **node_kwargs)

    # Edges (GraphML)
    gpath = os.path.join(crate_dir, 'cell_graph.graphml')
    if os.path.exists(gpath):
        G = nx.read_graphml(gpath)
        for u, v, data in G.edges(data=True):
            lbl = data.get('label', '')
            via = data.get('via', '')
            title = (lbl + (" | via: " + via if via else "")).strip()
            edge_kwargs = dict(title=title)
            if lbl:
                edge_kwargs['dep_label'] = lbl
            if via:
                edge_kwargs['via'] = via
            net.add_edge(int(u), int(v), **edge_kwargs)

    html_path = os.path.join(crate_dir, 'cell_graph.html')
    net.write_html(html_path)
    if panel:
        _inject_roshow_panel(html_path)
    print(f"Interactive graph written to {html_path}")
