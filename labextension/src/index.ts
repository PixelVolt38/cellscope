import { JupyterFrontEnd, JupyterFrontEndPlugin } from "@jupyterlab/application";
import { ICommandPalette, MainAreaWidget, Dialog } from "@jupyterlab/apputils";
import { INotebookTracker, NotebookPanel } from "@jupyterlab/notebook";
import { URLExt } from "@jupyterlab/coreutils";
import { DocumentRegistry } from "@jupyterlab/docregistry";
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
  sos_put: string[];
  sos_get: string[];
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

type ReviewRoleMap = Record<string, string>;
type ReviewDomainMap = Record<string, Record<string, string | string[]>>;

interface ReviewHints {
  roles: ReviewRoleMap;
  domains: ReviewDomainMap;
}

interface ReviewResult {
  hints: ReviewHints;
}

interface ReviewDraftVariable {
  name: string;
  kind: "data" | "function";
}

interface ReviewDraftFile {
  path: string;
  baseName: string;
}

interface ReviewDraft {
  variables: ReviewDraftVariable[];
  files: ReviewDraftFile[];
}

interface FilterState {
  search: string;
  kernels: Set<string> | null;
  requireFileWrites: boolean;
  requireFileReads: boolean;
  requireSos: boolean;
  edgeVia: Set<string> | null;
  roles: Set<string> | null;
  fileHints: Set<string> | null;
}

interface StoredFilterState {
  search: string;
  kernels: string[] | null;
  requireFileWrites: boolean;
  requireFileReads: boolean;
  requireSos: boolean;
  edgeVia: string[] | null;
  roles: string[] | null;
  fileHints: string[] | null;
}

type NotebookChangeReason = "save" | "execution" | "content";

const createEmptyReviewResult = (): ReviewResult => ({
  hints: {
    roles: {},
    domains: {}
  }
});

const basename = (value: string): string => {
  const normalised = value.replace(/\\/g, "/");
  const parts = normalised.split("/");
  return parts[parts.length - 1] || value;
};

class AnalysisPanel extends Widget {
  constructor(private readonly app: JupyterFrontEnd, private readonly tracker: INotebookTracker | null) {
    super();
    this.id = "cellscope-analysis-panel";
    this.title.label = "CellScope";
    this.title.closable = true;
    this.addClass("jp-CellScopePanel");
    this.node.style.display = "flex";
    this.node.style.flexDirection = "column";
    this.node.style.height = "100%";

    this._settings = this.app.serviceManager.serverSettings;

    this.node.appendChild(this._buildHeader());
    this.node.appendChild(this._statusNode);
    this.node.appendChild(this._pendingNode);
    this.node.appendChild(this._filterNode);
    this.node.appendChild(this._contentNode);
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
    this._disposeNotebookListeners();
    this._cancelPendingTimer();
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

    this._graphBtn = document.createElement("button");
    this._graphBtn.textContent = "Open Graph";
    this._graphBtn.className = "jp-mod-styled";
    this._graphBtn.disabled = true;
    this._graphBtn.addEventListener("click", () => {
      if (!this.openGraphView()) {
        this._setStatus("Export a crate before opening the graph viewer.", "warn");
      }
    });

    controls.appendChild(this._analyzeBtn);
    controls.appendChild(this._exportBtn);
    controls.appendChild(this._graphBtn);
    wrapper.appendChild(controls);

    return wrapper;
  }

  private async _analyze(): Promise<void> {
    await this._runAnalysis("manual");
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
      this._renderAnalysis(analysis);
      this._setBusy(false);
      const review = await this._showReviewDialog(analysis.graph);
      if (!review) {
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
          body: JSON.stringify({
            notebook: notebookPath,
            out_dir: outDir,
            hints: review.hints
          }),
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
      this._renderExportSummary(crateDir, payload.index ?? null);
      this._lastReview = review;
      this._graphBtn.disabled = !this._latestGraphUrl;
      if (this._lastAnalysis) {
        this._syncFilterOptions(this._lastAnalysis);
        this._renderFilterControls();
        this._saveFilterState();
        this._renderFilteredView(true);
      } else {
        this._renderFilteredView(true);
      }
      this._setStatus("Export complete.", "info");
    } catch (error) {
      console.error(error);
      this._setStatus(`Failed to export crate: ${this._stringifyError(error)}`, "error");
    } finally {
      this._setBusy(false);
    }
  }

  private _renderExportSummary(crateDir: string, indexInfo: any): void {
    const lines: string[] = [];
    lines.push(`Crate written to ${this._normalisePath(crateDir)}`);
    if (indexInfo) {
      const endpoint = typeof indexInfo.endpoint === "string" ? indexInfo.endpoint : null;
      const outputPath = typeof indexInfo.output === "string" ? indexInfo.output : null;
      const triples = typeof indexInfo.triples === "number" ? indexInfo.triples : null;
      const attempts = typeof indexInfo.attempts === "number" ? indexInfo.attempts : null;
      const duration = typeof indexInfo.duration_seconds === "number" ? indexInfo.duration_seconds : null;
      const status = typeof indexInfo.status === "number" ? indexInfo.status : null;

      if (endpoint) {
        const attemptText = attempts ? `attempts ${attempts}` : "attempts n/a";
        const durationText = duration !== null ? `in ${duration.toFixed(1)}s` : "";
        const statusText = status !== null ? `status ${status}` : "status n/a";
        const triplesText = triples !== null ? `${triples} triples` : "triples n/a";
        lines.push(`SPARQL push → ${endpoint} (${triplesText}, ${statusText}, ${attemptText} ${durationText}).`);
      } else {
        const dest = outputPath ?? "index/last_update.sparql";
        const triplesText = triples !== null ? `${triples} triples` : "triples n/a";
        lines.push(`SPARQL delta saved to ${this._normalisePath(dest)} (${triplesText}, endpoint not configured).`);
      }
    }
    this._exportNode.textContent = lines.join(" • ");
  }
  private _normalisePath(pathValue: string): string {
    if (!pathValue) {
      return pathValue;
    }
    return pathValue.replace(/\\/g, "/");
  }

  private async _runAnalysis(source: "manual" | "auto"): Promise<void> {
    const notebookPath = this._currentNotebookPath();
    if (!notebookPath) {
      if (source === "manual") {
        this._setStatus("Open a notebook to analyze.", "warn");
      }
      return;
    }

    if (this._analyzeInFlight) {
      if (source === "auto") {
        this._rerunAfterCurrent = true;
        this._cancelPendingTimer();
      }
      return;
    }

    if (this._pendingTimeout !== null) {
      window.clearTimeout(this._pendingTimeout);
      this._pendingTimeout = null;
    }

    this._analyzeInFlight = true;
    this._rerunAfterCurrent = false;

    if (source === "manual") {
      this._setBusy(true, "Analyzing notebook…");
    } else {
      this._setBusy(true, undefined, true);
    }

    try {
      const payload = await this._requestAnalysis(notebookPath);
      this._renderAnalysis(payload);
      if (source === "manual") {
        this._setStatus("Analysis complete.", "info");
      } else if (!(this._statusNode.textContent ?? "").trim()) {
        this._setStatus("Analysis refreshed.", "info");
      }
    } catch (error) {
      console.error(error);
      this._setStatus(`Failed to analyze notebook: ${this._stringifyError(error)}`, "error");
    } finally {
      this._analyzeInFlight = false;
      this._setBusy(false, undefined, source === "auto");
      if (this._rerunAfterCurrent) {
        this._setPending(true, "Additional notebook changes detected. Refreshing analysis…");
        this._scheduleAutoAnalyze("content");
        this._rerunAfterCurrent = false;
      } else {
        this._setPending(false);
      }
    }
  }

  private _renderAnalysis(data: AnalyzeResponse): void {
    this._lastAnalysis = data.graph;
    this._syncFilterOptions(data.graph);
    this._renderFilterControls();
    this._saveFilterState();
    this._renderFilteredView(true);
  }

  private _handleNotebookChange(reason: NotebookChangeReason): void {
    if (!this._lastAnalysis || !this._activeNotebookPath) {
      return;
    }
    let message: string;
    switch (reason) {
      case "save":
        message = "Notebook saved. Refreshing analysis…";
        break;
      case "execution":
        message = "Execution finished. Refreshing analysis…";
        break;
      default:
        message = "Notebook changed. Refreshing analysis…";
    }
    this._setPending(true, message);
    this._scheduleAutoAnalyze(reason);
  }

  private _scheduleAutoAnalyze(reason: NotebookChangeReason): void {
    if (!this._lastAnalysis || !this._activeNotebookPath) {
      return;
    }
    if (this._pendingTimeout !== null) {
      window.clearTimeout(this._pendingTimeout);
    }
    const delay = reason === "save" ? 400 : reason === "execution" ? 800 : 1000;
    const targetPath = this._activeNotebookPath;
    this._pendingTimeout = window.setTimeout(() => {
      this._pendingTimeout = null;
      if (targetPath !== this._activeNotebookPath) {
        return;
      }
      void this._runAnalysis("auto");
    }, delay);
  }

  private _setPending(active: boolean, message?: string, force = false): void {
    if (active) {
      this._pendingChanges = true;
      this._pendingNode.style.display = "";
      this._pendingNode.classList.toggle("jp-mod-warn", true);
      this._pendingNode.textContent =
        message ?? "Notebook changes detected. Analysis will refresh shortly…";
      return;
    }
    if (!force) {
      if (this._pendingTimeout !== null || this._rerunAfterCurrent) {
        return;
      }
    }
    this._pendingChanges = false;
    this._pendingNode.style.display = "none";
    this._pendingNode.classList.remove("jp-mod-warn");
    this._pendingNode.textContent = "";
  }

  private _cancelPendingTimer(): void {
    if (this._pendingTimeout !== null) {
      window.clearTimeout(this._pendingTimeout);
      this._pendingTimeout = null;
    }
  }

  private _setupNotebookListeners(panel: NotebookPanel | null): void {
    this._disposeNotebookListeners();
    this._observedPanel = panel;
    this._kernelWasBusySinceLastIdle = false;
    this._cancelPendingTimer();
    if (!panel) {
      this._setPending(false, undefined, true);
      return;
    }
    const { context } = panel;
    if (!context) {
      return;
    }
    const onSaveState = (_: DocumentRegistry.Context, state: DocumentRegistry.SaveState) => {
      if (state === "completed") {
        this._handleNotebookChange("save");
      }
    };
    context.saveState.connect(onSaveState, this);
    this._notebookListeners.push(() => context.saveState.disconnect(onSaveState, this));

    const session = context.sessionContext;
    if (session) {
      const onStatus = (_: unknown, status: string) => {
        this._onKernelStatusChanged(status);
      };
      session.statusChanged.connect(onStatus, this);
      this._notebookListeners.push(() => session.statusChanged.disconnect(onStatus, this));
    }
  }

  private _disposeNotebookListeners(): void {
    while (this._notebookListeners.length) {
      const dispose = this._notebookListeners.pop();
      try {
        dispose?.();
      } catch (error) {
        console.debug("[cellscope] Failed to detach notebook listener", error);
      }
    }
    this._observedPanel = null;
    this._kernelWasBusySinceLastIdle = false;
  }

  private _onKernelStatusChanged(status: string): void {
    if (!this._lastAnalysis || !this._activeNotebookPath) {
      return;
    }
    if (status === "busy") {
      this._kernelWasBusySinceLastIdle = true;
      return;
    }
    if (status === "idle" && this._kernelWasBusySinceLastIdle) {
      this._kernelWasBusySinceLastIdle = false;
      this._handleNotebookChange("execution");
      return;
    }
    if (status === "restarting" || status === "dead" || status === "terminating") {
      this._kernelWasBusySinceLastIdle = false;
    }
  }

  private _syncFilterOptions(graph: GraphSummary): void {
    this._kernelOptions = Array.from(new Set(graph.cells.map(cell => cell.kernel))).sort((a, b) =>
      a.localeCompare(b)
    );
    this._filterState.kernels = this._sanitizeFacet(this._filterState.kernels, this._kernelOptions);

    const viaSet = new Set<string>();
    graph.edges.forEach(edge => {
      if (edge.via) {
        viaSet.add(String(edge.via));
      }
    });
    if (viaSet.size === 0) {
      viaSet.add("ast");
    }
    this._edgeViaOptions = Array.from(viaSet).sort((a, b) => a.localeCompare(b));
    this._filterState.edgeVia = this._sanitizeFacet(this._filterState.edgeVia, this._edgeViaOptions);

    const hints = this._effectiveHints();
    const roleSet = new Set<string>();
    if (hints?.roles) {
      Object.values(hints.roles).forEach(role => {
        if (role) {
          roleSet.add(String(role));
        }
      });
    }
    this._roleOptions = Array.from(roleSet).sort((a, b) => a.localeCompare(b));
    this._filterState.roles = this._sanitizeFacet(this._filterState.roles, this._roleOptions);

    const hintSet = new Set<string>();
    if (hints?.domains) {
      Object.entries(hints.domains).forEach(([_, info]) => {
        if (!info) {
          return;
        }
        Object.entries(info).forEach(([key, value]) => {
          if (Array.isArray(value)) {
            value.forEach(v => hintSet.add(`${key}: ${v}`));
          } else if (typeof value !== "undefined" && value !== null) {
            hintSet.add(`${key}: ${value}`);
          }
        });
      });
    }
    this._fileHintOptions = Array.from(hintSet).sort((a, b) => a.localeCompare(b));
    this._filterState.fileHints = this._sanitizeFacet(this._filterState.fileHints, this._fileHintOptions);
  }
  private _renderFilterControls(): void {
    const graph = this._lastAnalysis;
    this._filterNode.innerHTML = "";
    if (!graph) {
      this._filterNode.style.display = "none";
      return;
    }
    this._filterNode.style.display = "";

    const searchWrapper = document.createElement("div");
    searchWrapper.className = "jp-CellScopeFilters-search";
    const searchLabel = document.createElement("label");
    searchLabel.textContent = "Search";
    const searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.placeholder = "Search cells, files, variables…";
    searchInput.value = this._filterState.search;
    searchInput.addEventListener("input", () => {
      this._updateFilters(() => {
        this._filterState.search = searchInput.value;
      });
    });
    searchWrapper.append(searchLabel, searchInput);
    this._filterNode.appendChild(searchWrapper);

    if (this._kernelOptions.length > 1) {
      const kernelWrapper = document.createElement("fieldset");
      kernelWrapper.className = "jp-CellScopeFilters-group";
      const legend = document.createElement("legend");
      legend.textContent = "Kernel";
      kernelWrapper.appendChild(legend);
      this._kernelOptions.forEach(kernel => {
        const optionLabel = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        const facet = this._filterState.kernels;
        const allSelected = this._facetIsAll(facet, this._kernelOptions);
        const isChecked = allSelected || (!!facet && facet.has(kernel));
        checkbox.checked = isChecked;
        checkbox.addEventListener("change", () => {
          this._updateFilters(() => {
            this._filterState.kernels = this._toggleFacet(
              this._filterState.kernels,
              kernel,
              checkbox.checked,
              this._kernelOptions
            );
          });
        });
        optionLabel.append(checkbox, document.createTextNode(kernel));
        kernelWrapper.appendChild(optionLabel);
      });
      this._filterNode.appendChild(kernelWrapper);
    }

    const togglesWrapper = document.createElement("div");
    togglesWrapper.className = "jp-CellScopeFilters-toggleGroup";
    togglesWrapper.appendChild(
      this._createToggle("Only cells that write files", this._filterState.requireFileWrites, value =>
        this._updateFilters(() => {
          this._filterState.requireFileWrites = value;
        })
      )
    );
    togglesWrapper.appendChild(
      this._createToggle("Only cells that read files", this._filterState.requireFileReads, value =>
        this._updateFilters(() => {
          this._filterState.requireFileReads = value;
        })
      )
    );
    togglesWrapper.appendChild(
      this._createToggle("Only SoS exchanges", this._filterState.requireSos, value =>
        this._updateFilters(() => {
          this._filterState.requireSos = value;
        })
      )
    );
    this._filterNode.appendChild(togglesWrapper);

    if (this._roleOptions.length) {
      const roleWrapper = document.createElement("fieldset");
      roleWrapper.className = "jp-CellScopeFilters-group";
      const legend = document.createElement("legend");
      legend.textContent = "Roles";
      roleWrapper.appendChild(legend);
      this._roleOptions.forEach(role => {
        const optionLabel = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        const facet = this._filterState.roles;
        const allSelected = this._facetIsAll(facet, this._roleOptions);
        const isChecked = allSelected || (!!facet && facet.has(role));
        checkbox.checked = isChecked;
        checkbox.addEventListener("change", () => {
          this._updateFilters(() => {
            this._filterState.roles = this._toggleFacet(
              this._filterState.roles,
              role,
              checkbox.checked,
              this._roleOptions
            );
          });
        });
        optionLabel.append(checkbox, document.createTextNode(role));
        roleWrapper.appendChild(optionLabel);
      });
      this._filterNode.appendChild(roleWrapper);
    }

    if (this._fileHintOptions.length) {
      const hintWrapper = document.createElement("fieldset");
      hintWrapper.className = "jp-CellScopeFilters-group";
      const legend = document.createElement("legend");
      legend.textContent = "File metadata";
      hintWrapper.appendChild(legend);
      this._fileHintOptions.forEach(hint => {
        const optionLabel = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        const facet = this._filterState.fileHints;
        const allSelected = this._facetIsAll(facet, this._fileHintOptions);
        const isChecked = allSelected || (!!facet && facet.has(hint));
        checkbox.checked = isChecked;
        checkbox.addEventListener("change", () => {
          this._updateFilters(() => {
            this._filterState.fileHints = this._toggleFacet(
              this._filterState.fileHints,
              hint,
              checkbox.checked,
              this._fileHintOptions
            );
          });
        });
        optionLabel.append(checkbox, document.createTextNode(hint));
        hintWrapper.appendChild(optionLabel);
      });
      this._filterNode.appendChild(hintWrapper);
    }

    if (this._edgeViaOptions.length > 1) {
      const viaWrapper = document.createElement("fieldset");
      viaWrapper.className = "jp-CellScopeFilters-group";
      const legend = document.createElement("legend");
      legend.textContent = "Edge via";
      viaWrapper.appendChild(legend);
      this._edgeViaOptions.forEach(via => {
        const optionLabel = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        const facet = this._filterState.edgeVia;
        const allSelected = this._facetIsAll(facet, this._edgeViaOptions);
        const isChecked = allSelected || (!!facet && facet.has(via));
        checkbox.checked = isChecked;
        checkbox.addEventListener("change", () => {
          this._updateFilters(() => {
            this._filterState.edgeVia = this._toggleFacet(
              this._filterState.edgeVia,
              via,
              checkbox.checked,
              this._edgeViaOptions
            );
          });
        });
        optionLabel.append(checkbox, document.createTextNode(via));
        viaWrapper.appendChild(optionLabel);
      });
      this._filterNode.appendChild(viaWrapper);
    }
  }
  private _renderFilteredView(emitEvent = false): void {
    const graph = this._lastAnalysis;
    this._resultsNode.innerHTML = "";
    this._edgesNode.innerHTML = "";
    if (!graph) {
      this._resultsNode.textContent = "Run Analyze to see notebook metadata.";
      return;
    }

    const filteredCells = graph.cells.filter(cell => this._matchesCell(cell));
    const filteredEdges = graph.edges.filter(edge => this._matchesEdge(edge));
    const hints = this._effectiveHints();

    if (!filteredCells.length) {
      this._resultsNode.textContent = "No cells match the current filters.";
    } else {
      filteredCells.forEach(cell => {
        const sosPut = cell.sos_put ?? [];
        const sosGet = cell.sos_get ?? [];
        const roleTokens = this._roleTokensForCell(cell, hints);
        const fileTokens = this._fileHintTokensForCell(cell, hints);
        const details = document.createElement("details");
        details.className = "jp-CellScopePanel-cell";
        details.open = filteredCells.length <= 4;
        const summary = document.createElement("summary");
        summary.textContent = `Cell ${cell.idx} (${cell.kernel})`;
        details.appendChild(summary);

        const quickActions = document.createElement("div");
        quickActions.className = "jp-CellScopePanel-quickActions";
        const activateBtn = document.createElement("button");
        activateBtn.textContent = "Activate cell";
        activateBtn.className = "jp-mod-styled";
        activateBtn.disabled = !this.tracker || !this.tracker.currentWidget;
        activateBtn.addEventListener("click", () => {
          this._activateCell(cell.idx);
        });
        quickActions.appendChild(activateBtn);
        details.appendChild(quickActions);

        const body = document.createElement("div");
        body.className = "jp-CellScopePanel-cellBody";
        body.append(
          this._renderList("Functions", cell.funcs),
          this._renderList("Defined Vars", cell.var_defs),
          this._renderList("Used Vars", cell.var_uses),
          this._renderList("File Writes", cell.file_writes),
          this._renderList("File Reads", cell.file_reads),
          this._renderList("SoS put", sosPut),
          this._renderList("SoS get", sosGet),
          this._renderList("Roles", roleTokens),
          this._renderList("File metadata", fileTokens)
        );
        details.appendChild(body);
        this._resultsNode.appendChild(details);
      });
    }

    const edgesHeader = document.createElement("h4");
    edgesHeader.textContent = "Edges";
    this._edgesNode.appendChild(edgesHeader);

    if (!filteredEdges.length) {
      const none = document.createElement("p");
      none.textContent = "No edges match the current filters.";
      this._edgesNode.appendChild(none);
    } else {
      const ul = document.createElement("ul");
      filteredEdges.forEach(edge => {
        const parts: string[] = [];
        if (typeof edge.source !== "undefined" && typeof edge.target !== "undefined") {
          parts.push(`Cell ${edge.source} → Cell ${edge.target}`);
        }
        if (edge.type) {
          parts.push(`type: ${edge.type}`);
        }
        if (edge.vars?.length) {
          parts.push(`vars: ${edge.vars.join(", ")}`);
        }
        const via = edge.via ?? "ast";
        parts.push(`via ${via}`);
        const li = document.createElement("li");
        li.textContent = parts.join(" | ");
        ul.appendChild(li);
      });
      this._edgesNode.appendChild(ul);
    }

    if (emitEvent) {
      this._emitFilterChange(filteredCells.length, filteredEdges.length);
    }
  }
  private _matchesCell(cell: AnalyzeCell): boolean {
    const { search, kernels, requireFileReads, requireFileWrites, requireSos, roles, fileHints } = this._filterState;
    const sosPut = cell.sos_put ?? [];
    const sosGet = cell.sos_get ?? [];
    const hints = this._effectiveHints();
    const roleTokens = this._roleTokensForCell(cell, hints);
    const fileHintTokens = this._fileHintTokensForCell(cell, hints);

    if (kernels && kernels.size > 0 && !kernels.has(cell.kernel)) {
      return false;
    }

    if (requireFileWrites && cell.file_writes.length === 0) {
      return false;
    }
    if (requireFileReads && cell.file_reads.length === 0) {
      return false;
    }
    if (requireSos && sosPut.length === 0 && sosGet.length === 0) {
      return false;
    }

    if (roles && roles.size > 0 && !roleTokens.some(role => roles.has(role))) {
      return false;
    }

    if (fileHints && fileHints.size > 0 && !fileHintTokens.some(token => fileHints.has(token))) {
      return false;
    }

    const term = search.trim().toLowerCase();
    if (!term) {
      return true;
    }
    const hintTokens = this._hintTokensForCell(cell, hints);
    const haystack = [
      `cell ${cell.idx}`,
      cell.kernel,
      ...cell.funcs,
      ...cell.var_defs,
      ...cell.var_uses,
      ...cell.file_writes,
      ...cell.file_reads,
      ...sosPut,
      ...sosGet,
      ...hintTokens
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(term);
  }
  private _matchesEdge(edge: AnalyzeEdge): boolean {
    const { edgeVia, search } = this._filterState;
    const via = (edge.via ?? "ast").toString();
    if (edgeVia && edgeVia.size > 0 && !edgeVia.has(via)) {
      return false;
    }
    const term = search.trim().toLowerCase();
    if (!term) {
      return true;
    }
    const parts: string[] = [];
    if (typeof edge.source !== "undefined" && typeof edge.target !== "undefined") {
      parts.push(`cell ${edge.source}`);
      parts.push(`cell ${edge.target}`);
    }
    if (edge.type) {
      parts.push(edge.type);
    }
    parts.push(via);
    if (edge.vars?.length) {
      parts.push(...edge.vars);
    }
    const haystack = parts.join(" ").toLowerCase();
    return haystack.includes(term);
  }

  private _toggleFacet(current: Set<string> | null, value: string, checked: boolean, allValues: readonly string[]): Set<string> | null {
    if (!allValues.length) {
      return null;
    }
    const universe = new Set(allValues);
    const working = current === null ? new Set(universe) : new Set(current);
    if (checked) {
      working.add(value);
    } else {
      working.delete(value);
    }
    if (working.size === 0) {
      return null;
    }
    if (working.size === universe.size) {
      return universe.size === 1 ? working : null;
    }
    return working;
  }

  private _facetIsAll(facet: Set<string> | null, options: readonly string[]): boolean {
    if (!options.length) {
      return true;
    }
    if (facet === null) {
      return true;
    }
    return facet.size === options.length;
  }

  private _sanitizeFacet(current: Set<string> | null, options: readonly string[]): Set<string> | null {
    if (!options.length) {
      return null;
    }
    if (current === null) {
      return null;
    }
    const filtered = new Set<string>();
    options.forEach(option => {
      if (current.has(option)) {
        filtered.add(option);
      }
    });
    if (filtered.size === 0) {
      return null;
    }
    if (filtered.size === options.length) {
      return options.length === 1 ? filtered : null;
    }
    return filtered;
  }

  private _createToggle(labelText: string, checked: boolean, onChange: (value: boolean) => void): HTMLElement {
    const wrapper = document.createElement("label");
    wrapper.className = "jp-CellScopeFilters-toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = checked;
    input.addEventListener("change", () => {
      onChange(input.checked);
    });
    wrapper.append(input, document.createTextNode(labelText));
    return wrapper;
  }

  private _activateCell(idx: number): void {
    const panel = this.tracker?.currentWidget;
    if (!panel) {
      this._setStatus("Open a notebook to activate cells.", "warn");
      return;
    }
    const { content } = panel;
    if (!content) {
      return;
    }
    let codeIndex = -1;
    let targetIndex = -1;
    const total = content.widgets.length;
    for (let i = 0; i < total; i++) {
      const cell = content.widgets[i];
      if (cell?.model?.type === "code") {
        codeIndex += 1;
        if (codeIndex === idx) {
          targetIndex = i;
          break;
        }
      }
    }
    if (targetIndex === -1) {
      this._setStatus(`Could not locate code cell ${idx}.`, "warn");
      return;
    }
    content.activeCellIndex = targetIndex;
    content.deselectAll();
    content.scrollToItem(targetIndex);
    this.app.shell.activateById(panel.id);
  }

  private _updateFilters(mutator: () => void): void {
    mutator();
    this._saveFilterState();
    this._renderFilteredView(true);
  }

  private _effectiveHints(): ReviewHints | null {
    return this._lastReview?.hints ?? this._storedHints;
  }

  private _roleTokensForCell(cell: AnalyzeCell, hints: ReviewHints | null): string[] {
    if (!hints?.roles) {
      return [];
    }
    const seen = new Set<string>();
    const tokens: string[] = [];
    [...cell.var_defs, ...cell.var_uses].forEach(varName => {
      const role = hints.roles?.[varName];
      if (role && !seen.has(role)) {
        seen.add(role);
        tokens.push(role);
      }
    });
    return tokens;
  }

  private _fileHintTokensForCell(cell: AnalyzeCell, hints: ReviewHints | null): string[] {
    if (!hints?.domains) {
      return [];
    }
    const tokens = new Set<string>();
    const domains = hints.domains ?? {};
    const fileNames = new Set<string>();
    [...cell.file_writes, ...cell.file_reads].forEach(path => fileNames.add(basename(path)));
    fileNames.forEach(name => {
      const info = domains[name];
      if (!info) {
        return;
      }
      Object.entries(info).forEach(([key, value]) => {
        if (Array.isArray(value)) {
          value.forEach(v => tokens.add(`${key}: ${v}`));
        } else if (typeof value !== "undefined" && value !== null) {
          tokens.add(`${key}: ${value}`);
        }
      });
    });
    return Array.from(tokens);
  }

  private _hintTokensForCell(cell: AnalyzeCell, hints?: ReviewHints | null): string[] {
    const effective = hints ?? this._effectiveHints();
    if (!effective) {
      return [];
    }
    const tokens = new Set<string>();
    this._roleTokensForCell(cell, effective).forEach(token => tokens.add(token));
    this._fileHintTokensForCell(cell, effective).forEach(token => tokens.add(token));
    return Array.from(tokens);
  }

  private _createDefaultFilterState(): FilterState {
    return {
      search: "",
      kernels: null,
      requireFileWrites: false,
      requireFileReads: false,
      requireSos: false,
      edgeVia: null,
      roles: null,
      fileHints: null
    };
  }

  private _serializeFilterState(): StoredFilterState {
    const toSortedArray = (value: Set<string> | null) => {
      if (!value || value.size === 0) {
        return null;
      }
      return Array.from(value).sort((a, b) => a.localeCompare(b));
    };
    return {
      search: this._filterState.search,
      kernels: toSortedArray(this._filterState.kernels),
      requireFileWrites: this._filterState.requireFileWrites,
      requireFileReads: this._filterState.requireFileReads,
      requireSos: this._filterState.requireSos,
      edgeVia: toSortedArray(this._filterState.edgeVia),
      roles: toSortedArray(this._filterState.roles),
      fileHints: toSortedArray(this._filterState.fileHints)
    };
  }

  private _saveFilterState(): void {
    const key = this._filterStorageKey();
    if (!key) {
      return;
    }
    try {
      window.localStorage.setItem(key, JSON.stringify(this._serializeFilterState()));
    } catch (error) {
      console.debug("[cellscope] Failed to save filter state", error);
    }
  }

  private _loadFilterState(): void {
    this._filterState = this._createDefaultFilterState();
    const key = this._filterStorageKey();
    if (!key) {
      return;
    }
    try {
      const raw = window.localStorage.getItem(key);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw) as Partial<StoredFilterState>;
      if (typeof parsed.search === "string") {
        this._filterState.search = parsed.search;
      }
      if (parsed.kernels === null) {
        this._filterState.kernels = null;
      } else if (Array.isArray(parsed.kernels)) {
        this._filterState.kernels = new Set(parsed.kernels);
      }
      if (typeof parsed.requireFileWrites === "boolean") {
        this._filterState.requireFileWrites = parsed.requireFileWrites;
      }
      if (typeof parsed.requireFileReads === "boolean") {
        this._filterState.requireFileReads = parsed.requireFileReads;
      }
      if (typeof parsed.requireSos === "boolean") {
        this._filterState.requireSos = parsed.requireSos;
      }
      if (parsed.edgeVia === null) {
        this._filterState.edgeVia = null;
      } else if (Array.isArray(parsed.edgeVia)) {
        this._filterState.edgeVia = new Set(parsed.edgeVia);
      }
      if (parsed.roles === null) {
        this._filterState.roles = null;
      } else if (Array.isArray(parsed.roles)) {
        this._filterState.roles = new Set(parsed.roles);
      }
      if (parsed.fileHints === null) {
        this._filterState.fileHints = null;
      } else if (Array.isArray(parsed.fileHints)) {
        this._filterState.fileHints = new Set(parsed.fileHints);
      }
    } catch (error) {
      console.debug("[cellscope] Failed to load filter state", error);
      this._filterState = this._createDefaultFilterState();
    }
  }

  private _filterStorageKey(): string | null {
    if (!this._activeNotebookPath) {
      return null;
    }
    return `cellscope:filters:${encodeURIComponent(this._activeNotebookPath)}`;
  }

  private _hintsStorageKey(): string | null {
    if (!this._activeNotebookPath) {
      return null;
    }
    return `cellscope:hints:${encodeURIComponent(this._activeNotebookPath)}`;
  }

  private _persistHints(hints: ReviewHints): void {
    const key = this._hintsStorageKey();
    if (!key) {
      return;
    }
    try {
      window.localStorage.setItem(key, JSON.stringify(hints));
      this._storedHints = hints;
    } catch (error) {
      console.debug("[cellscope] Failed to persist hints", error);
    }
  }

  private _loadStoredHints(): void {
    const key = this._hintsStorageKey();
    this._storedHints = null;
    if (!key) {
      return;
    }
    try {
      const raw = window.localStorage.getItem(key);
      if (!raw) {
        return;
      }
      this._storedHints = JSON.parse(raw) as ReviewHints;
    } catch (error) {
      console.debug("[cellscope] Failed to load stored hints", error);
      this._storedHints = null;
    }
  }

  private _emitFilterChange(filteredCells: number, filteredEdges: number): void {
    const detail = {
      ...this._serializeFilterState(),
      filteredCells,
      filteredEdges
    };
    const signature = JSON.stringify(detail);
    if (signature === this._lastFilterSignature) {
      return;
    }
    this._lastFilterSignature = signature;
    document.dispatchEvent(new CustomEvent("cellscope:filters-changed", { detail }));
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
    const panel = this.tracker?.currentWidget ?? null;
    this._setupNotebookListeners(panel ?? null);
    const pathVal = panel?.context.path ?? this._currentNotebookPath();
    this._pathNode.textContent = pathVal ?? "(no notebook)";
    this._latestGraphUrl = null;
    if (this._graphBtn) {
      this._graphBtn.disabled = true;
    }
    this._exportNode.textContent = "";
    this._lastReview = null;
    this._activeNotebookPath = pathVal;
    this._storedHints = null;
    this._lastFilterSignature = "";
    this._cancelPendingTimer();
    this._setPending(false, undefined, true);
    if (pathVal) {
      this._loadStoredHints();
      this._loadFilterState();
    } else {
      this._filterState = this._createDefaultFilterState();
    }
  }
  private _setBusy(busy: boolean, message?: string, preserveStatus = false): void {
    this._analyzeBtn.disabled = busy;
    this._exportBtn.disabled = busy;
    if (message) {
      this._setStatus(message, "info");
    } else if (!busy && !preserveStatus) {
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

  private async _showReviewDialog(graph: GraphSummary): Promise<ReviewResult | null> {
    const body = document.createElement("div");
    body.className = "jp-CellScopeReview";

    const intro = document.createElement("p");
    intro.textContent = "Review the captured metadata, adjust roles or file metadata, and confirm to generate the RO-Crate.";
    body.appendChild(intro);

    const draft = this._buildReviewDraft(graph);
    const hints = this._lastReview?.hints ?? createEmptyReviewResult().hints;

    const roleInputs = new Map<string, HTMLInputElement>();
    const fileInputs = new Map<
      string,
      {
        mime: HTMLInputElement;
        tags: HTMLInputElement;
      }
    >();

    const metadataSection = document.createElement("div");
    metadataSection.className = "jp-CellScopeReview-section";
    const metadataTitle = document.createElement("h4");
    metadataTitle.textContent = "Metadata adjustments";
    metadataSection.appendChild(metadataTitle);

    if (!draft.variables.length && !draft.files.length) {
      const noEditable = document.createElement("p");
      noEditable.textContent = "No editable metadata detected for this notebook.";
      metadataSection.appendChild(noEditable);
    } else {
      if (draft.variables.length) {
        const varTitle = document.createElement("h5");
        varTitle.textContent = `Variables (${draft.variables.length})`;
        metadataSection.appendChild(varTitle);

        draft.variables.forEach(variable => {
          const field = document.createElement("label");
          field.className = "jp-CellScopeReview-field";

          const nameSpan = document.createElement("span");
          nameSpan.className = "jp-CellScopeReview-fieldLabel";
          nameSpan.textContent =
            variable.kind === "function" ? `${variable.name} (function)` : variable.name;
          field.appendChild(nameSpan);

          const input = document.createElement("input");
          input.type = "text";
          input.className = "jp-CellScopeReview-input jp-mod-styled";
          input.placeholder =
            variable.kind === "function"
              ? "Role (e.g., algorithm, helper)"
              : "Role (e.g., dataset, parameter)";
          const existing = hints.roles?.[variable.name];
          if (existing) {
            input.value = existing;
          }
          field.appendChild(input);
          metadataSection.appendChild(field);
          roleInputs.set(variable.name, input);
        });
      }

      if (draft.files.length) {
        const fileTitle = document.createElement("h5");
        fileTitle.textContent = `Files (${draft.files.length})`;
        metadataSection.appendChild(fileTitle);

        draft.files.forEach(file => {
          const block = document.createElement("div");
          block.className = "jp-CellScopeReview-fileBlock";

          const pathLabel = document.createElement("div");
          pathLabel.className = "jp-CellScopeReview-fieldLabel";
          pathLabel.textContent = file.path;
          block.appendChild(pathLabel);

          const mimeInput = document.createElement("input");
          mimeInput.type = "text";
          mimeInput.className = "jp-CellScopeReview-input jp-mod-styled";
          mimeInput.placeholder = "MIME type (e.g., text/csv)";
          const existingDomain = hints.domains?.[file.baseName];
          const rawMime = existingDomain ? existingDomain["encodingFormat"] : undefined;
          const presetMime = Array.isArray(rawMime) ? rawMime[0] ?? "" : rawMime ?? "";
          if (presetMime) {
            mimeInput.value = presetMime;
          }
          block.appendChild(mimeInput);

          const tagsInput = document.createElement("input");
          tagsInput.type = "text";
          tagsInput.className = "jp-CellScopeReview-input jp-mod-styled";
          tagsInput.placeholder = "Tags (comma separated)";
          const rawTags = existingDomain ? existingDomain["keywords"] : undefined;
          const tagsPreset = Array.isArray(rawTags)
            ? rawTags
            : typeof rawTags === "string"
            ? [rawTags]
            : [];
          if (tagsPreset.length) {
            tagsInput.value = tagsPreset.join(", ");
          }
          block.appendChild(tagsInput);
          metadataSection.appendChild(block);

          fileInputs.set(file.baseName, { mime: mimeInput, tags: tagsInput });
        });
      }
    }

    body.appendChild(metadataSection);

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
        this._renderList("File reads", cell.file_reads),
        this._renderList("SoS put", cell.sos_put ?? []),
        this._renderList("SoS get", cell.sos_get ?? [])
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

    const accept = dialog.node.querySelector("button.jp-mod-accept") as HTMLButtonElement | null;
    if (accept) {
      accept.disabled = true;
      checkbox.addEventListener("change", () => {
        accept.disabled = !checkbox.checked;
      });
    }

    const result = await dialog.launch();
    if (!result.button.accept) {
      return null;
    }

    const roles: ReviewRoleMap = {};
    roleInputs.forEach((input, variable) => {
      const value = input.value.trim();
      if (value) {
        roles[variable] = value;
      }
    });

    const domains: ReviewDomainMap = {};
    fileInputs.forEach((inputs, baseNameKey) => {
      const domainEntries: Record<string, string | string[]> = {};
      const mimeValue = inputs.mime.value.trim();
      if (mimeValue) {
        domainEntries["encodingFormat"] = mimeValue;
      }
      const tagsValue = inputs.tags.value
        .split(",")
        .map(tag => tag.trim())
        .filter(tag => tag.length > 0);
      if (tagsValue.length === 1) {
        domainEntries["keywords"] = tagsValue[0];
      } else if (tagsValue.length > 1) {
        domainEntries["keywords"] = tagsValue;
      }

      if (Object.keys(domainEntries).length > 0) {
        domains[baseNameKey] = domainEntries;
      }
    });

    const review: ReviewResult = {
      hints: {
        roles,
        domains
      }
    };
    this._lastReview = review;
    return review;
  }

  private _buildReviewDraft(graph: GraphSummary): ReviewDraft {
    const functionNames = new Set<string>();
    graph.cells.forEach(cell => {
      cell.funcs.forEach(fn => functionNames.add(fn));
    });

    const varMap = new Map<string, ReviewDraftVariable>();
    graph.cells.forEach(cell => {
      cell.var_defs.forEach(variable => {
        if (!varMap.has(variable)) {
          varMap.set(variable, {
            name: variable,
            kind: functionNames.has(variable) ? "function" : "data"
          });
        }
      });
    });

    const fileMap = new Map<string, ReviewDraftFile>();
    graph.cells.forEach(cell => {
      [...cell.file_writes, ...cell.file_reads].forEach(filePath => {
        const baseName = basename(filePath);
        if (!fileMap.has(baseName)) {
          fileMap.set(baseName, { path: filePath, baseName });
        }
      });
    });

    return {
      variables: Array.from(varMap.values()).sort((a, b) => a.name.localeCompare(b.name)),
      files: Array.from(fileMap.values()).sort((a, b) => a.baseName.localeCompare(b.baseName))
    };
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
  private readonly _pendingNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-pending";
    div.style.display = "none";
    return div;
  })();
  private readonly _filterNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-filters";
    div.style.display = "none";
    return div;
  })();
  private readonly _resultsNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-results";
    div.style.paddingBottom = "8px";
    return div;
  })();
  private readonly _edgesNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-edges";
    div.style.marginTop = "12px";
    return div;
  })();
  private readonly _contentNode = (() => {
    const div = document.createElement("div");
    div.className = "jp-CellScopePanel-content";
    div.style.flex = "1 1 auto";
    div.style.overflowY = "auto";
    div.style.paddingRight = "4px";
    div.appendChild(this._resultsNode);
    div.appendChild(this._edgesNode);
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
  private _graphBtn!: HTMLButtonElement;
  private _latestGraphUrl: string | null = null;
  private _lastAnalysis: GraphSummary | null = null;
  private _lastReview: ReviewResult | null = null;
  private _storedHints: ReviewHints | null = null;
  private _activeNotebookPath: string | null = null;
  private _filterState: FilterState = this._createDefaultFilterState();
  private _kernelOptions: string[] = [];
  private _edgeViaOptions: string[] = [];
  private _roleOptions: string[] = [];
  private _fileHintOptions: string[] = [];
  private _pendingTimeout: number | null = null;
  private _pendingChanges = false;
  private _notebookListeners: Array<() => void> = [];
  private _observedPanel: NotebookPanel | null = null;
  private _kernelWasBusySinceLastIdle = false;
  private _analyzeInFlight = false;
  private _rerunAfterCurrent = false;
  private _lastFilterSignature = "";
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
