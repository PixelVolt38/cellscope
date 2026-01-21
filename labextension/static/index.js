// lib/index.js
import { JupyterFrontEnd } from "@jupyterlab/application";
import { ICommandPalette, MainAreaWidget } from "@jupyterlab/apputils";
import { Widget } from "@lumino/widgets";
var GRAPH_CMD = "cellscope:open-graph";
var LIST_CMD = "cellscope:open-list";
var PlaceholderPanel = class extends Widget {
  constructor(title) {
    super();
    this.addClass("jp-CellScopePanel");
    this.title.label = title;
    this.node.innerHTML = `
      <div style="padding:12px;font-family:var(--jp-content-font-family)">
        <h3>${title}</h3>
        <p>
          CellScope UI stub. Replace this panel with the production graph/list components.
          Backend endpoints <code>/cellscope/analyze</code> and <code>/cellscope/export</code> are ready.
        </p>
      </div>
    `;
  }
};
function registerCommands(app, palette) {
  const { commands, shell } = app;
  commands.addCommand(GRAPH_CMD, {
    label: "CellScope: Open Graph Panel",
    execute: () => {
      const content = new PlaceholderPanel("CellScope Graph");
      const widget = new MainAreaWidget({ content });
      widget.title.label = "CellScope Graph";
      shell.add(widget, "main");
    }
  });
  commands.addCommand(LIST_CMD, {
    label: "CellScope: Open List/Filter Panel",
    execute: () => {
      const content = new PlaceholderPanel("CellScope List/Filter");
      const widget = new MainAreaWidget({ content });
      widget.title.label = "CellScope List/Filter";
      shell.add(widget, "main");
    }
  });
  if (palette) {
    palette.addItem({ command: GRAPH_CMD, category: "CellScope" });
    palette.addItem({ command: LIST_CMD, category: "CellScope" });
  }
}
var extension = {
  id: "cellscope-lab:plugin",
  autoStart: true,
  optional: [ICommandPalette],
  activate: (
    /** @param {JupyterFrontEnd} app */
    (app, palette) => {
      registerCommands(app, palette ?? null);
    }
  )
};
var index_default = extension;
export {
  index_default as default
};
//# sourceMappingURL=index.js.map
