import { JupyterFrontEnd, JupyterFrontEndPlugin } from "@jupyterlab/application";
import { ICommandPalette, MainAreaWidget, Dialog } from "@jupyterlab/apputils";
import { INotebookTracker } from "@jupyterlab/notebook";
import { URLExt } from "@jupyterlab/coreutils";
import { ServerConnection } from "@jupyterlab/services";
import { JSONExt } from "@lumino/coreutils";
import { Widget } from "@lumino/widgets";

const LIST_CMD = "cellscope:open-list";
const GRAPH_CMD = "cellscope:open-graph";

type GraphSummary = AnalyzeResponse["graph"];

interface AnalyzeCell {
  idx: number;
  kernel: string;
  funcs: string[];
  var_defs: string[];
  var_uses: string[];
  file_writes: string[];
  file_reads: string[];
}

interface AnalyzeEdge {
  type: string;
  vars?: string[];
  via?: string;
  source?: number | string;
  target?: number | string;
  [key: string]: unknown;
}

interface AnalyzeResponse {
  graph: {
    cells: AnalyzeCell[];
    edges: AnalyzeEdge[];
  };
}

class AnalysisPanel extends Widget {
  constructor(private readonly app: JupyterFrontEnd, private readonly tracker: INotebookTracker | null) {
    super();
    this.id = "cellscope-analysis-panel";
    this.title.label = "CellScope";
    this.title.closable = true;
    this.addClass("jp-CellScopePanel");

    this._settings = this.app.serviceManager.serverSettings;

    this.node.appendChild(this._buildHeader());
    this.node.appendChild(this._statusNode);
    this.node.appendChild(this._resultsNode);
    this.node.appendChild(this._edgesNode);
    this.node.appendChild(this._exportNode);
    this.node.appendChild(this._helpNode);

    if (this.tracker) {
      this.tracker.currentChanged.connect(this._syncNotebook, this);
      this.tracker.widgetAdded.connect(this._syncNotebook, this);
    }
    this._syncNotebook();
  }

  dispose(): void {
    if (this.tracker) {
      this.tracker.currentChanged.disconnect(this._syncNotebook, this);
      this.tracker.widgetAdded.disconnect(this._syncNotebook, this);
    }
    super.dispose();
  }

  openGraphView(): boolean {
    if (!this._latestGraphUrl) {
      this._setStatus("Run an export before opening the graph viewer.", "warn");
      return false;
    }
    const iframe = document.createElement("iframe");
    iframe.src = this._latestGraphUrl;
    iframe.style.width = "100%";
    iframe.style.height = "100%";
    iframe.style.border = "none";

    const container = new Widget({ node: document.createElement("div") });
    container.node.style.height = "100%";
    container.node.appendChild(iframe);

    const widget = new MainAreaWidget({ content: container });
    widget.title.label = "CellScope Graph";
    widget.title.closable = true;
    this.app.shell.add(widget, "main");
    this.app.shell.activateById(widget.id);
    return true;
  }

  private _buildHeader(): HTMLElement {
    const wrapper = document.createElement("div");
    wrapper.className = "jp-CellScopePanel-header";

    const title = document.createElement("h3");
    title.textContent = "CellScope Analyzer";
    wrapper.appendChild(title);

    const pathRow = document.createElement("div");
    pathRow.className = "jp-CellScopePanel-row";
    const label = document.createElement("span");
    label.textContent = "Notebook: ";
    pathRow.appendChild(label);
    this._pathNode = document.createElement("code");
    this._pathNode.textContent = "(no notebook)";
    pathRow.appendChild(this._pathNode);
    wrapper.appendChild(pathRow);

    const controls = document.createElement("div");
    controls.className = "jp-CellScopePanel-controls";

    this._analyzeBtn = document.createElement("button");
    this._analyzeBtn.textContent = "Analyze";
    this._analyzeBtn.className = "jp-mod-styled";
    this._analyzeBtn.addEventListener("click", () => {
      void this._analyze();
    });

    this._exportBtn = document.createElement("button");
    this._exportBtn.textContent = "Export Crate";
    this._exportBtn.className = "jp-mod-styled";
    this._exportBtn.addEventListener("click", () => {
      void this._export();
    });

    controls.appendChild(this._analyzeBtn);
    controls.appendChild(this._exportBtn);
    wrapper.appendChild(controls);

    return wrapper;
  }

  private async _analyze(): Promise<void> {
    const notebookPath = this._currentNotebookPath();
    if (!notebookPath) {
      this._setStatus("Open a notebook to analyze.", "warn");
      return;
    }

    this._setBusy(true, "Analyzing notebook…");
    try {
      const payload = await this._requestAnalysis(notebookPath);
      this._renderAnalysis(payload);
      this._setStatus("Analysis complete.", "info");
    } catch (error) {
      console.error(error);
      this._setStatus(`Failed to analyze notebook: ${this._stringifyError(error)}`, "error");
    } finally {
      this._setBusy(false);
    }
  }

  private async _export(): Promise<void> {
    const notebookPath = this._currentNotebookPath();
    if (!notebookPath) {
      this._setStatus("Open a notebook to export.", "warn");
      return;
    }

    this._setBusy(true, "Preparing review…");
    try {
      const analysis = await this._requestAnalysis(notebookPath);
      this._setBusy(false);
      const confirmed = await this._showReviewDialog(analysis.graph);
      if (!confirmed) {
        this._setStatus("Export cancelled.", "warn");
        return;
      }

      this._setBusy(true, "Exporting RO-Crate…");
      const outDir = `out-lab/${Date.now()}`;
      const url = URLExt.join(this._settings.baseUrl, "cellscope", "export");
      const response = await ServerConnection.makeRequest(
        url,
        {
          method: "POST",
          body: JSON.stringify({ notebook: notebookPath, out_dir: outDir }),
          headers: { "Content-Type": "application/json" }
        },
        this._settings
      );

      if (!response.ok) {
        throw new ServerConnection.ResponseError(response);
      }

      const payload = await response.json();
      const crateDir = payload.crate as string;
      this._latestGraphUrl = this._buildGraphUrl(crateDir);
      this._exportNode.textContent = `Crate written to ${crateDir}`;
      this._setStatus("Export complete.", "info");
    } catch (error) {
      console.error(error);
      this._setStatus(`Failed to export crate: ${this._stringifyError(error)}`, "error");
    } finally {
      this._setBusy(false);
    }
  }

  private _renderAnalysis(data: AnalyzeResponse): void {
    const { cells, edges } = data.graph;
    this._lastAnalysis = data.graph;

    this._resultsNode.innerHTML = "";
    if (!cells.length) {
      this._resultsNode.textContent = "No cells detected.";
    } else {
      cells.forEach(cell => {
        const details = document.createElement("details");
        details.className = "jp-CellScopePanel-cell";
        const summary = document.createElement("summary");
        summary.textContent = `Cell ${cell.idx} (${cell.kernel})`;
        details.appendChild(summary);

        const list = document.createElement("div");
        list.className = "jp-CellScopePanel-cellBody";
        list.appendChild(this._renderList("Functions", cell.funcs));
        list.appendChild(this._renderList("Defined Vars", cell.var_defs));
        list.appendChild(this._renderList("Used Vars", cell.var_uses));
        list.appendChild(this._renderList("File Writes", cell.file_writes));
        list.appendChild(this._renderList("File Reads", cell.file_reads));
        details.appendChild(list);
        this._resultsNode.appendChild(details);
      });
    }

    this._edgesNode.innerHTML = "";
    const edgesHeader = document.createElement("h4");
    edgesHeader.textContent = "Edges";
    this._edgesNode.appendChild(edgesHeader);
    if (!edges.length) {
      const none = document.createElement("p");
      none.textContent = "No edges detected.";
      this._edgesNode.appendChild(none);
    } else {
      const ul = document.createElement("ul");
      edges.forEach(edge => {
        const parts: string[] = [];
        if (typeof edge.source !== "undefined" && typeof edge.target !== "undefined") {
          parts.push(`${edge.source} → ${edge.target}`);
        }
        if (edge.type) {
          parts.push(`type: ${edge.type}`);
        }
        if (edge.vars?.length) {
          parts.push(`vars: ${edge.vars.join(", ")}`);
        }
        if (edge.via) {
          parts.push(`via ${edge.via}`);
        }
        const li = document.createElement("li");
        li.textContent = parts.join(" | ") || JSON.stringify(edge);
        ul.appendChild(li);
      });
      this._edgesNode.appendChild(ul);
    }
  }

  private _renderList(label: string, items: string[]): HTMLElement {
    const container = document.createElement("div");
    container.className = "jp-CellScopePanel-section";
    const title = document.createElement("strong");
    title.textContent = `${label}: `;
    container.appendChild(title);
    container.appendChild(document.createTextNode(items.length ? items.join(", ") : "—"));
    return container;
  }

  private _buildGraphUrl(crateDir: string): string | null {
    if (!crateDir) {
      return null;
    }
    const normalized = crateDir.replace(/\\/g, "/");
    const relative = normalized.startsWith("/") ? normalized.slice(1) : normalized;
    const graphPath = `${relative}/cell_graph.html`;
    return URLExt.join(this._settings.baseUrl, "files", graphPath);
  }

  private _currentNotebookPath(): string | null {
    const current = this.tracker?.currentWidget;
    return current?.context.path ?? null;
  }

  private _syncNotebook(): void {
    const path = this._currentNotebookPath();
    this._pathNode.textContent = path ?? "(no notebook)";
    this._latestGraphUrl = null;
    this._exportNode.textContent = "";
  }

  private _setBusy(busy: boolean, message?: string): void {
    this._analyzeBtn.disabled = busy;
    this._exportBtn.disabled = busy;
    if (message) {
      this._setStatus(message, "info");
    } else if (!busy) {
      this._statusNode.textContent = "";
    }
  }

  private _setStatus(message: string, level: "info" | "warn" | "error"): void {
    this._statusNode.textContent = message;
    this._statusNode.className = `jp-CellScopePanel-status jp-mod-${level}`;
  }

  private async _requestAnalysis(notebookPath: string): Promise<AnalyzeResponse> {
    const url = URLExt.join(this._settings.baseUrl, "cellscope", "analyze");
    const response = await ServerConnection.makeRequest(
      url,
      {
        method: "POST",
        body: JSON.stringify({ notebook: notebookPath }),
        headers: { "Content-Type": "application/json" }
      },
      this._settings
    );

    if (!response.ok) {
      throw new ServerConnection.ResponseError(response);
    }

    return (await response.json()) as AnalyzeResponse;
  }

  private async _showReviewDialog(graph: GraphSummary): Promise<boolean> {
    const body = document.createElement("div");
    body.className = "jp-CellScopeReview";

    const intro = document.createElement("p");
    intro.textContent = "Review the captured metadata below. Confirm to generate the RO-Crate.";
    body.appendChild(intro);

    const cellsSection = document.createElement("div");
    cellsSection.className = "jp-CellScopeReview-section";
    const cellsTitle = document.createElement("h4");
    cellsTitle.textContent = `Cells (${graph.cells.length})`;
    cellsSection.appendChild(cellsTitle);
    graph.cells.forEach(cell => {
      const details = document.createElement("details");
      details.open = graph.cells.length <= 3;
      const summary = document.createElement("summary");
      summary.textContent = `Cell ${cell.idx} (${cell.kernel})`;
      details.appendChild(summary);
      const bodyDiv = document.createElement("div");
      bodyDiv.append(
        this._renderList("Functions", cell.funcs),
        this._renderList("Defined vars", cell.var_defs),
        this._renderList("Used vars", cell.var_uses),
        this._renderList("File writes", cell.file_writes),
        this->_renderList("File reads", cell.file_reads)
      );
      details.appendChild(bodyDiv);
      cellsSection.appendChild(details);
    });
    body.appendChild(cellsSection);

    const edgesSection = document.createElement("div");
    edgesSection.className = "jp-CellScopeReview-section";
    const edgesTitle = document.createElement("h4");
    edgesTitle.textContent = `Edges (${graph.edges.length})`;
    edgesSection.appendChild(edgesTitle);
    if (!graph.edges.length) {
      const none = document.createElement("p");
      none.textContent = "No edges detected.";
      edgesSection.appendChild(none);
    } else {
      const list = document.createElement("ul");
      graph.edges.forEach(edge => {
        const item = document.createElement("li");
        const parts: string[] = [];
        if (typeof edge.source !== "undefined" && typeof edge.target !== "undefined") {
          parts.push(`${edge.source} → ${edge.target}`);
        }
        if (edge.type) {
          parts.push(edge.type);
        }
        if (edge.vars?.length) {
          parts.push(`vars: ${edge.vars.join(", ")}`);
        }
        if (edge.via) {
          parts.push(`via ${edge.via}`);
        }
        item.textContent = parts.join(" | ") || JSON.stringify(edge);
        list.appendChild(item);
      });
      edgesSection.appendChild(list);
    }
    body.appendChild(edgesSection);

    const consentWrapper = document.createElement("div");
    consentWrapper.className = "jp-CellScopeReview-consent";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = "cellscope-review-consent";
    const consentLabel = document.createElement("label");
    consentLabel.htmlFor = checkbox.id;
    consentLabel.textContent = "I have reviewed the metadata and want to export the crate.";
    consentWrapper.append(checkbox, consentLabel);
    body.appendChild(consentWrapper);

    const dialog = new Dialog({
      title: "Review Notebook Metadata",
      body: new Widget({ node: body }),
      buttons: [Dialog.cancelButton({ label: "Cancel" }), Dialog.okButton({ label: "Confirm Export" })]
    });

    const accept = dialog.node.querySelector("button.jp-mod-accept") as HTMLButtonButton | null;    if (accept) {
      accept.disabled = true;
      checkbox.addEventListener("change", () => {
        accept.disabled = !checkbox.checked;
      });
    }

    const result = await dialog.launch();
    return result.button.accept === true;
  }

  private _stringifyError(error: unknown): string {
    if (error instanceof Error) {
      return error.message;
    }
    if (JSONExt.isPrimitive(error as any)) {
      return String(error);
    }
    try {
      return JSON.stringify(error);
    } catch {
      return "Unknown error";
    }
  }

  private readonly _statusNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-status";
    return div;
  })();
  private readonly _resultsNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-results";
    return div;
  })();
  private readonly _edgesNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-edges";
    return div;
  })();
  private readonly _exportNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-export";
    return div;
  })();
  private readonly _helpNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-help";
    div.innerHTML = "Need the graph? Export a crate, then run <code>CellScope: Open Graph Panel</code>.";
    return div;
  })();
  private readonly _settings: ServerConnection.ISettings;
  private _pathNode!: HTMLElement;
  private _analyzeBtn!: HTMLButtonElement;
  private _exportBtn!: HTMLButtonElement;
  private _latestGraphUrl: string | null = null;
  private _lastAnalysis: GraphSummary | null = null;
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: "cellscope-lab:plugin",
  autoStart: true,
  optional: [ICommandPalette, INotebookTracker],
  activate: (
    app: JupyterFrontEnd,
    palette: ICommandPalette | null,
    tracker: INotebookTracker | null
  ) => {
    const panel = new AnalysisPanel(app, tracker ?? null);
    app.shell.add(panel, "left", { rank: 950 });

    app.commands.addCommand(LIST_CMD, {
      label: "CellScope: Show Analyzer",
      execute: () => {
        app.shell.activateById(panel.id);
      }
    });

    app.commands.addCommand(GRAPH_CMD, {
      label: "CellScope: Open Graph Panel",
      execute: () => {
        if (!panel.openGraphView()) {
          app.commands.execute("apputils:notify", {
            title: "CellScope",
            message: "Export a crate before opening the graph viewer.",
            options: { autoClose: true }
          });
        }
      }
    });

    if (palette) {
      palette.addItem({ command: LIST_CMD, category: "CellScope" });
      palette.addItem({ command: GRAPH_CMD, category: "CellScope" });
    }
  }
};

export default plugin;
