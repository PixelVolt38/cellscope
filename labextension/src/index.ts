import { JupyterFrontEnd, JupyterFrontEndPlugin } from "@jupyterlab/application";
import { ICommandPalette, MainAreaWidget, Dialog, showErrorMessage } from "@jupyterlab/apputils";
import { INotebookTracker, NotebookPanel } from "@jupyterlab/notebook";
import { URLExt, PageConfig } from "@jupyterlab/coreutils";
import { DocumentRegistry } from "@jupyterlab/docregistry";
import { IDocumentManager } from "@jupyterlab/docmanager";
import { ServerConnection } from "@jupyterlab/services";
import { JSONExt } from "@lumino/coreutils";
import { Widget } from "@lumino/widgets";
import "../style/index.css";

const LIST_CMD = "cellscope:open-list";
const GRAPH_CMD = "cellscope:open-graph";
const WORKFLOW_CMD = "cellscope:workflow-capture";
const WORKFLOWS_ENABLED = PageConfig.getOption("cellscopeEnableWorkflows") === "true";
const CONFIG_STORAGE_KEY = "cellscope:config";
const DEFAULT_SPARQL_ENDPOINT = "http://localhost:3030/cellscope/update";

type GraphSummary = AnalyzeResponse["graph"];

interface WorkflowCaptureInitial {
  workflow?: string;
  outDir?: string;
  defaultNotebook?: string | null;
  notebookRoots?: string[];
}

interface CellScopeConfig {
  endpoint: string;
  token: string;
  username: string;
  password: string;
  retries: number;
  backoffSeconds: number;
  outputPath: string;
  dataSource: "local" | "sparql";
}


interface AnalyzeCell {
  idx: number;
  name?: string;
  kernel: string;
  graph?: string;
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
  edgeVia: Set<string> | null;
  roles: Set<string> | null;
  fileHints: Set<string> | null;
}

interface StoredFilterState {
  search: string;
  kernels: string[] | null;
  requireFileWrites: boolean;
  requireFileReads: boolean;
  edgeVia: string[] | null;
  roles: string[] | null;
  fileHints: string[] | null;
}

interface WorkflowCaptureDialogValue {
  workflow: string;
  outDir: string;
  notebookRoots: string[];
  notebookMap: Record<string, string>;
  defaultNotebook: string | null;
  skipCrates: boolean;
}

interface WorkflowCaptureResponseNode {
  id: string;
  title: string;
  status: string;
  notebook?: string | null;
  error?: string | null;
}

interface WorkflowCaptureResponse {
  workflow_id: string;
  manifest: string;
  captured: number;
  total: number;
  nodes: WorkflowCaptureResponseNode[];
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
    this._config = this._loadConfig();

    this.node.appendChild(this._buildHeader());
    this.node.appendChild(this._statusNode);
    this.node.appendChild(this._pendingNode);
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

    this._filtersBtn = document.createElement("button");
    this._filtersBtn.textContent = "Filters";
    this._filtersBtn.className = "jp-mod-styled jp-CellScopePanel-filtersButton";
    this._filtersBtn.disabled = true;
    this._filtersBtn.addEventListener("click", () => {
      if (this._filtersBtn.disabled) {
        return;
      }
      this._toggleFilters();
    });

    this._settingsBtn = document.createElement("button");
    this._settingsBtn.textContent = "Settings";
    this._settingsBtn.className = "jp-mod-styled jp-CellScopePanel-settingsButton";
    this._settingsBtn.addEventListener("click", () => {
      void this._showSettingsDialog();
    });

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

    controls.appendChild(this._filtersBtn);
    controls.appendChild(this._settingsBtn);
    controls.appendChild(this._analyzeBtn);
    controls.appendChild(this._exportBtn);
    controls.appendChild(this._graphBtn);

    if (WORKFLOWS_ENABLED) {
      const workflowBtn = document.createElement("button");
      workflowBtn.textContent = "Workflow";
      workflowBtn.className = "jp-mod-styled jp-CellScopePanel-workflowButton";
      workflowBtn.addEventListener("click", () => {
        void this.app.commands.execute(WORKFLOW_CMD);
      });
      controls.appendChild(workflowBtn);
    }
    wrapper.appendChild(controls);

    this._filterOverlay = document.createElement("div");
    this._filterOverlay.className = "jp-CellScopePanel-filtersPopover";
    this._filterOverlay.style.display = "none";
    this._filterOverlay.appendChild(this._filterNode);
    wrapper.appendChild(this._filterOverlay);

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
            hints: review.hints,
            index: this._buildIndexConfig()
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
    if (this._config.dataSource === "sparql") {
      this._latestGraphUrl = null;
    }

    this._analyzeInFlight = true;
    this._rerunAfterCurrent = false;

    if (source === "manual") {
      this._setBusy(true, this._config.dataSource === "sparql" ? "Loading from SPARQL…" : "Analyzing notebook…");
    } else {
      this._setBusy(true, undefined, true);
    }

    try {
      let payload: AnalyzeResponse;
      if (this._config.dataSource === "sparql") {
        payload = await this._requestSparqlSummary();
        this._latestGraphUrl = await this._requestSparqlGraph();
      } else {
        const notebookPath = this._currentNotebookPath();
        if (!notebookPath) {
          if (source === "manual") {
            this._setStatus("Open a notebook to analyze.", "warn");
          }
          return;
        }
        payload = await this._requestAnalysis(notebookPath);
      }
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
    this._cellLabelMap.clear();
    data.graph.cells.forEach(cell => {
      this._cellLabelMap.set(cell.idx, this._cellLabel(cell));
    });
    this._syncFilterOptions(data.graph);
    this._renderFilterControls();
    this._graphBtn.disabled = !this._latestGraphUrl;
    this._toggleFilters(false);
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
    const allEdges = this._edgeList(graph);
    allEdges.forEach(edge => {
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
      this._filtersBtn.disabled = true;
      this._filtersBtn.textContent = "Filters";
      this._toggleFilters(false);
      return;
    }
    this._filtersBtn.disabled = false;

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
    const filteredEdges = this._edgeList(graph).filter(edge => this._matchesEdge(edge));
    const hints = this._effectiveHints();

    if (!filteredCells.length) {
      this._resultsNode.textContent = "No cells match the current filters.";
    } else {
      const groups = new Map<string, AnalyzeCell[]>();
      filteredCells.forEach(cell => {
        const label = cell.graph ?? "Notebook";
        const arr = groups.get(label) ?? [];
        arr.push(cell);
        groups.set(label, arr);
      });

      Array.from(groups.entries()).forEach(([label, cells]) => {
        const header = document.createElement("h4");
        header.textContent = `Notebook: ${label}`;
        this._resultsNode.appendChild(header);

        cells.forEach(cell => {
        const roleTokens = this._roleTokensForCell(cell, hints);
        const fileTokens = this._fileHintTokensForCell(cell, hints);
        const details = document.createElement("details");
        details.className = "jp-CellScopePanel-cell";
        details.open = filteredCells.length <= 4;
        const summary = document.createElement("summary");
        summary.textContent = this._cellSummary(cell);
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
          this._renderList("Roles", roleTokens),
          this._renderList("File metadata", fileTokens)
        );
        details.appendChild(body);
        this._resultsNode.appendChild(details);
      });
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
          const sourceLabel = this._formatCellReference(edge.source);
          const targetLabel = this._formatCellReference(edge.target);
          if (sourceLabel && targetLabel) {
            parts.push(`${sourceLabel} → ${targetLabel}`);
          }
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
    const { search, kernels, requireFileReads, requireFileWrites, roles, fileHints } = this._filterState;
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
      this._cellLabel(cell),
      `cell ${cell.idx}`,
      cell.kernel,
      ...cell.funcs,
      ...cell.var_defs,
      ...cell.var_uses,
      ...cell.file_writes,
      ...cell.file_reads,
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
      const sourceLabel = this._formatCellReference(edge.source);
      const targetLabel = this._formatCellReference(edge.target);
      if (sourceLabel) {
        parts.push(sourceLabel);
      }
      if (targetLabel) {
        parts.push(targetLabel);
      }
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

  private _cellLabel(cell: AnalyzeCell): string {
    const raw = (cell.name ?? "").trim();
    return raw || `Cell ${cell.idx}`;
  }

  private _cellSummary(cell: AnalyzeCell): string {
    return `${this._cellLabel(cell)} (cell ${cell.idx}, ${cell.kernel})`;
  }

  private _formatCellReference(value: number | string | undefined): string | null {
    if (typeof value === "number") {
      const label = this._cellLabelMap.get(value);
      return label ? `${label} (cell ${value})` : `Cell ${value}`;
    }
    if (typeof value === "string") {
      return value;
    }
    return null;
  }

  private _updateFilters(mutator: () => void): void {
    mutator();
    this._saveFilterState();
    this._renderFilteredView(true);
  }

  private _effectiveHints(): ReviewHints | null {
    return this._lastReview?.hints ?? this._storedHints;
  }

  private _edgeList(graph: GraphSummary): AnalyzeEdge[] {
    if (!graph || !Array.isArray(graph.edges)) {
      return [];
    }
    return graph.edges;
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

    const activeCount =
      (this._filterState.search.trim() ? 1 : 0) +
      (this._filterState.kernels && this._filterState.kernels.size > 0 ? 1 : 0) +
      (this._filterState.roles && this._filterState.roles.size > 0 ? 1 : 0) +
      (this._filterState.fileHints && this._filterState.fileHints.size > 0 ? 1 : 0) +
      (this._filterState.edgeVia && this._filterState.edgeVia.size > 0 ? 1 : 0) +
      (this._filterState.requireFileReads ? 1 : 0) +
      (this._filterState.requireFileWrites ? 1 : 0);
    this._filtersBtn.textContent = activeCount ? `Filters (${activeCount})` : "Filters";
    if (!activeCount) {
      this._toggleFilters(false);
    }
  }
  private _toggleFilters(force?: boolean): void {
    const next = force ?? !this._filtersVisible;
    if (!this._filtersBtn || !this._filterOverlay) {
      return;
    }
    if (next && this._filtersBtn.disabled) {
      return;
    }
    this._filtersVisible = next;
    if (next) {
      const rect = this._filtersBtn.getBoundingClientRect();
      const parentRect = this.node.getBoundingClientRect();
      const availableRight = parentRect.right - rect.left;
      const width = Math.min(420, Math.max(260, availableRight - 16));
      this._filterOverlay.style.width = `${width}px`;
      this._filterOverlay.style.left = `${Math.min(
        rect.left - parentRect.left,
        parentRect.width - width - 8
      )}px`;
      this._filterOverlay.style.top = `${rect.bottom - parentRect.top + 4}px`;
    }
    this._filterOverlay.style.display = next ? "block" : "none";
    this._filtersBtn.classList.toggle("jp-mod-active", next);
    if (next) {
      this._filterOverlay.scrollTop = 0;
    }
  }

  private _handleDocumentClick = (event: MouseEvent): void => {
    if (!this._filtersVisible) {
      return;
    }
    if (!this._filterOverlay || !this._filtersBtn) {
      return;
    }
    const target = event.target as Node;
    if (!this._filterOverlay.contains(target) && !this._filtersBtn.contains(target)) {
      this._toggleFilters(false);
    }
  };

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

  private async _requestSparqlSummary(): Promise<AnalyzeResponse> {
    const url = URLExt.join(this._settings.baseUrl, "cellscope", "sparql_summary");
    const response = await ServerConnection.makeRequest(
      url,
      {
        method: "POST",
        body: JSON.stringify(this._buildIndexConfig()),
        headers: { "Content-Type": "application/json" }
      },
      this._settings
    );
    if (!response.ok) {
      throw new ServerConnection.ResponseError(response);
    }
    return (await response.json()) as AnalyzeResponse;
  }

  private async _requestSparqlGraph(): Promise<string | null> {
    const url = URLExt.join(this._settings.baseUrl, "cellscope", "sparql_graph");
    const response = await ServerConnection.makeRequest(
      url,
      {
        method: "POST",
        body: JSON.stringify(this._buildIndexConfig()),
        headers: { "Content-Type": "application/json" }
      },
      this._settings
    );
    if (!response.ok) {
      return null;
    }
    const payload = await response.json();
    const graphUrl = payload.graph_url as string | undefined;
    return graphUrl ?? null;
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
        source: HTMLInputElement;
        version: HTMLInputElement;
        retrieved: HTMLInputElement;
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

        const varGrid = document.createElement("div");
        varGrid.className = "jp-CellScopeReview-grid";

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
          varGrid.appendChild(field);
          roleInputs.set(variable.name, input);
        });

        metadataSection.appendChild(varGrid);
      }

      if (draft.files.length) {
        const fileTitle = document.createElement("h5");
        fileTitle.textContent = `Files (${draft.files.length})`;
        metadataSection.appendChild(fileTitle);

        const fileGrid = document.createElement("div");
        fileGrid.className = "jp-CellScopeReview-grid";

        draft.files.forEach(file => {
          const block = document.createElement("div");
          block.className = "jp-CellScopeReview-fileBlock";

          const pathLabel = document.createElement("div");
          pathLabel.className = "jp-CellScopeReview-fieldLabel";
          pathLabel.textContent = file.path.replace(/\\/g, "/");
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

          const sourceInput = document.createElement("input");
          sourceInput.type = "text";
          sourceInput.className = "jp-CellScopeReview-input jp-mod-styled";
          sourceInput.placeholder = "Source URL (for remote datasets)";
          const rawSource = existingDomain ? existingDomain["accessURL"] : undefined;
          if (typeof rawSource === "string" && rawSource.length) {
            sourceInput.value = rawSource;
          } else if (/^https?:\/\//i.test(file.path)) {
            sourceInput.value = file.path.replace(/\\/g, "/");
          }
          block.appendChild(sourceInput);

          const versionInput = document.createElement("input");
          versionInput.type = "text";
          versionInput.className = "jp-CellScopeReview-input jp-mod-styled";
          versionInput.placeholder = "Version / ETag";
          const rawEtag = existingDomain ? existingDomain["etag"] : undefined;
          if (typeof rawEtag === "string" && rawEtag.length) {
            versionInput.value = rawEtag;
          }
          block.appendChild(versionInput);

          const retrievedInput = document.createElement("input");
          retrievedInput.type = "text";
          retrievedInput.className = "jp-CellScopeReview-input jp-mod-styled";
          retrievedInput.placeholder = "Retrieved at (ISO 8601)";
          const rawRetrieved = existingDomain ? existingDomain["retrievedAt"] : undefined;
          if (typeof rawRetrieved === "string" && rawRetrieved.length) {
            retrievedInput.value = rawRetrieved;
          }
          block.appendChild(retrievedInput);
          fileGrid.appendChild(block);

          fileInputs.set(file.baseName, {
            mime: mimeInput,
            tags: tagsInput,
            source: sourceInput,
            version: versionInput,
            retrieved: retrievedInput
          });
        });

        metadataSection.appendChild(fileGrid);
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
      summary.textContent = this._cellSummary(cell);
      details.appendChild(summary);
      const bodyDiv = document.createElement("div");
      bodyDiv.append(
        this._renderList("Functions", cell.funcs),
        this._renderList("Defined vars", cell.var_defs),
        this._renderList("Used vars", cell.var_uses),
        this._renderList("File writes", cell.file_writes),
        this._renderList("File reads", cell.file_reads)
      );
      details.appendChild(bodyDiv);
      cellsSection.appendChild(details);
    });
    body.appendChild(cellsSection);

    const edgesSection = document.createElement("div");
    edgesSection.className = "jp-CellScopeReview-section";
    const edgesTitle = document.createElement("h4");
    const edges = this._edgeList(graph);
    edgesTitle.textContent = `Edges (${edges.length})`;
    edgesSection.appendChild(edgesTitle);
    if (!edges.length) {
      const none = document.createElement("p");
      none.textContent = "No edges detected.";
      edgesSection.appendChild(none);
    } else {
      const list = document.createElement("ul");
      edges.forEach(edge => {
        const item = document.createElement("li");
        const parts: string[] = [];
        if (typeof edge.source !== "undefined" && typeof edge.target !== "undefined") {
          const src = this._formatCellReference(edge.source);
          const tgt = this._formatCellReference(edge.target);
          if (src && tgt) {
            parts.push(`${src} → ${tgt}`);
          }
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

    const dialog = new Dialog({
      title: "Review Notebook Metadata",
      body: new Widget({ node: body }),
      buttons: [Dialog.cancelButton({ label: "Cancel" }), Dialog.okButton({ label: "Confirm Export" })]
    });

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

      const sourceValue = inputs.source.value.trim();
      if (sourceValue) {
        domainEntries["accessURL"] = sourceValue;
      }
      const versionValue = inputs.version.value.trim();
      if (versionValue) {
        domainEntries["etag"] = versionValue;
      }
      const retrievedValue = inputs.retrieved.value.trim();
      if (retrievedValue) {
        domainEntries["retrievedAt"] = retrievedValue;
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

  private _loadConfig(): CellScopeConfig {
    const raw = window.localStorage.getItem(CONFIG_STORAGE_KEY);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as Partial<CellScopeConfig>;
        return {
          endpoint: parsed.endpoint ?? DEFAULT_SPARQL_ENDPOINT,
          token: parsed.token ?? "",
          username: parsed.username ?? "",
          password: parsed.password ?? "",
          retries: typeof parsed.retries === "number" ? parsed.retries : 2,
          backoffSeconds: typeof parsed.backoffSeconds === "number" ? parsed.backoffSeconds : 1.5,
          outputPath: parsed.outputPath ?? "",
          dataSource: parsed.dataSource === "sparql" ? "sparql" : "local"
        };
      } catch (e) {
        console.warn("Failed to parse CellScope config, resetting", e);
      }
    }
    return {
      endpoint: DEFAULT_SPARQL_ENDPOINT,
      token: "",
      username: "",
      password: "",
      retries: 2,
      backoffSeconds: 1.5,
      outputPath: "",
      dataSource: "local"
    };
  }

  private _saveConfig(cfg: CellScopeConfig): void {
    this._config = cfg;
    window.localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(cfg));
  }

  private _buildIndexConfig(): any {
    const cfg = this._config;
    const index: any = {};
    if (cfg.endpoint) {
      index.endpoint = cfg.endpoint;
    }
    if (cfg.outputPath) {
      index.output = cfg.outputPath;
    }
    if (cfg.token) {
      index.auth_token = cfg.token;
    }
    if (cfg.username && cfg.password) {
      index.username = cfg.username;
      index.password = cfg.password;
    }
    if (cfg.retries || cfg.retries === 0) {
      index.retries = cfg.retries;
    }
    if (cfg.backoffSeconds || cfg.backoffSeconds === 0) {
      index.backoff_seconds = cfg.backoffSeconds;
    }
    return index;
  }

  private _sparqlHeaders(token: string, username: string, password: string): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/x-www-form-urlencoded"
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    } else if (username && password) {
      const encoded = btoa(`${username}:${password}`);
      headers["Authorization"] = `Basic ${encoded}`;
    }
    return headers;
  }

  private async _sparqlFetch(endpoint: string, query: string, token: string, username: string, password: string): Promise<any> {
    if (!endpoint) {
      throw new Error("Endpoint required");
    }
    const headers = this._sparqlHeaders(token, username, password);
    const doQuery = async (url: string) => {
      const resp = await fetch(url, {
        method: "POST",
        headers,
        body: `query=${encodeURIComponent(query)}`
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      return resp.json();
    };
    try {
      return await doQuery(endpoint);
    } catch (err: any) {
      const str = typeof err?.message === "string" ? err.message : "";
      if (str.includes("HTTP 400") && endpoint.includes("/update")) {
        const queryEndpoint = endpoint.replace("/update", "/sparql");
        return await doQuery(queryEndpoint);
      }
      throw err;
    }
  }

  private async _fetchGraphList(endpoint: string, token: string, username: string, password: string): Promise<string[]> {
    const query = "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }";
    const data = await this._sparqlFetch(endpoint, query, token, username, password);
    const bindings = data?.results?.bindings ?? [];
    const graphs: string[] = [];
    bindings.forEach((b: any) => {
      const val = b?.g?.value;
      if (typeof val === "string") {
        graphs.push(val);
      }
    });
    return graphs;
  }

  private _latestPerNotebook(graphs: string[]): string[] {
    const byBase = new Map<string, { ver: number; full: string }>();
    graphs.forEach(g => {
      let base = g;
      let ver = -1;
      if (g.includes("?v=")) {
        const parts = g.split("?v=");
        base = parts[0];
        const parsed = parseInt(parts[1], 10);
        if (!isNaN(parsed)) {
          ver = parsed;
        }
      }
      const prev = byBase.get(base);
      if (!prev || ver > prev.ver) {
        byBase.set(base, { ver, full: g });
      }
    });
    return Array.from(byBase.values()).map(x => x.full);
  }

  private async _fetchTriples(graphs: string[], endpoint: string, token: string, username: string, password: string): Promise<Array<[string, string, string, any, any]>> {
    if (!graphs.length) {
      return [];
    }
    const values = graphs.map(g => `<${g}>`).join(" ");
    const query = `
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX schema: <http://schema.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?g ?s ?p ?o WHERE {
  VALUES ?g { ${values} }
  GRAPH ?g {
    ?s ?p ?o .
    FILTER (?p IN (prov:used, prov:wasGeneratedBy, rdf:type, schema:name))
  }
}
`;
    const data = await this._sparqlFetch(endpoint, query, token, username, password);
    const triples: Array<[string, string, string, any, any]> = [];
    const bindings = data?.results?.bindings ?? [];
    bindings.forEach((b: any) => {
      const g = b?.g?.value;
      const s = b?.s?.value;
      const p = b?.p?.value;
      const oObj = b?.o ?? {};
      if (typeof g === "string" && typeof s === "string" && typeof p === "string") {
        triples.push([g, s, p, oObj?.value, oObj?.type]);
      }
    });
    return triples;
  }

  private _buildGraphFromTriples(triples: Array<[string, string, string, any, any]>): GraphSummary {
    const activities = new Map<string, { id: string; graph: string }>();
    const dataEntities = new Map<string, { id: string; graph: string }>();
    const nameMap = new Map<string, string>();
    const graphLabels = new Map<string, string>();

    triples.forEach(([g, s, p, o]) => {
      if (!graphLabels.has(g)) {
        graphLabels.set(g, this._graphLabel(g));
      }
      if (p === "http://www.w3.org/1999/02/22-rdf-syntax-ns#type") {
        if (o === "http://www.w3.org/ns/prov#Activity" || (typeof o === "string" && o.endsWith("ontoflow#Activity"))) {
          activities.set(s, { id: s, graph: g });
        } else {
          dataEntities.set(s, { id: s, graph: g });
        }
      }
      if (p === "http://schema.org/name" && typeof o === "string") {
        nameMap.set(s, o);
      }
    });

    const producedBy = new Map<string, string>();
    const consumedBy = new Map<string, string[]>();
    const baseProducers = new Map<string, string>();

    triples.forEach(([g, s, p, o]) => {
      if (p === "http://www.w3.org/ns/prov#wasGeneratedBy" && typeof o === "string") {
        producedBy.set(s, o);
        const base = this._baseName(nameMap.get(s) || s);
        if (base) {
          if (!baseProducers.has(base)) {
            baseProducers.set(base, o);
          }
        }
      }
      if (p === "http://www.w3.org/ns/prov#used" && typeof o === "string") {
        const arr = consumedBy.get(o) || [];
        arr.push(s);
        consumedBy.set(o, arr);
      }
    });

    const cells: AnalyzeCell[] = [];
    const idxMap = new Map<string, number>();
    Array.from(activities.values()).forEach((act, idx) => {
      idxMap.set(act.id, idx);
      cells.push({
        idx,
        name: nameMap.get(act.id) || act.id,
        kernel: graphLabels.get(act.graph) ?? "sparql",
        graph: graphLabels.get(act.graph) ?? act.graph,
        funcs: [],
        var_defs: [],
        var_uses: [],
        file_writes: [],
        file_reads: []
      });
    });

    const edges: AnalyzeEdge[] = [];
    producedBy.forEach((prod, dataId) => {
      const consumers = consumedBy.get(dataId) || [];
      if (!idxMap.has(prod)) {
        return;
      }
      consumers.forEach(cons => {
        if (!idxMap.has(cons)) {
          return;
        }
        edges.push({
          source: idxMap.get(prod),
          target: idxMap.get(cons),
          type: "uses",
          via: "sparql",
          vars: [nameMap.get(dataId) || dataId]
        });
      });
    });

    consumedBy.forEach((consumers, dataId) => {
      const base = this._baseName(nameMap.get(dataId) || dataId);
      const prod = baseProducers.get(base);
      if (!prod || !idxMap.has(prod)) {
        return;
      }
      consumers.forEach(cons => {
        if (!idxMap.has(cons)) {
          return;
        }
        edges.push({
          source: idxMap.get(prod),
          target: idxMap.get(cons),
          type: "uses",
          via: "sparql",
          vars: [base]
        });
      });
    });

    return { cells, edges };
  }

  private _baseName(value: string): string {
    const parts = value.replace(/\\/g, "/").split("/");
    return parts[parts.length - 1] || value;
  }

  private _graphLabel(uri: string): string {
    if (!uri) {
      return "unknown";
    }
    const cleaned = uri.split("?")[0];
    const base = this._baseName(cleaned);
    return base || uri;
  }

  private async _showSettingsDialog(): Promise<void> {
    const cfg = this._config;
    const body = document.createElement("div");
    body.className = "jp-CellScopeSettings";

    const makeField = (labelText: string, input: HTMLElement) => {
      const row = document.createElement("label");
      row.className = "jp-CellScopeSettings-row";
      const span = document.createElement("span");
      span.textContent = labelText;
      row.appendChild(span);
      row.appendChild(input);
      return row;
    };

    const endpointInput = document.createElement("input");
    endpointInput.type = "text";
    endpointInput.className = "jp-CellScopeReview-input jp-mod-styled";
    endpointInput.placeholder = "SPARQL endpoint (query/update)";
    endpointInput.value = cfg.endpoint;

    const tokenInput = document.createElement("input");
    tokenInput.type = "text";
    tokenInput.className = "jp-CellScopeReview-input jp-mod-styled";
    tokenInput.placeholder = "Auth token (optional)";
    tokenInput.value = cfg.token;

    const userInput = document.createElement("input");
    userInput.type = "text";
    userInput.className = "jp-CellScopeReview-input jp-mod-styled";
    userInput.placeholder = "Username (optional)";
    userInput.value = cfg.username;

    const passInput = document.createElement("input");
    passInput.type = "password";
    passInput.className = "jp-CellScopeReview-input jp-mod-styled";
    passInput.placeholder = "Password (optional)";
    passInput.value = cfg.password;

    const retriesInput = document.createElement("input");
    retriesInput.type = "number";
    retriesInput.className = "jp-CellScopeReview-input jp-mod-styled";
    retriesInput.min = "0";
    retriesInput.step = "1";
    retriesInput.value = String(cfg.retries ?? 2);

    const backoffInput = document.createElement("input");
    backoffInput.type = "number";
    backoffInput.className = "jp-CellScopeReview-input jp-mod-styled";
    backoffInput.min = "0";
    backoffInput.step = "0.5";
    backoffInput.value = String(cfg.backoffSeconds ?? 1.5);

    const outputInput = document.createElement("input");
    outputInput.type = "text";
    outputInput.className = "jp-CellScopeReview-input jp-mod-styled";
    outputInput.placeholder = "Index output file (optional)";
    outputInput.value = cfg.outputPath;

    const dataSourceSelect = document.createElement("select");
    dataSourceSelect.className = "jp-CellScopeReview-input jp-mod-styled";
    const optLocal = document.createElement("option");
    optLocal.value = "local";
    optLocal.textContent = "Local (capture JSON)";
    const optSparql = document.createElement("option");
    optSparql.value = "sparql";
    optSparql.textContent = "SPARQL (triplestore)";
    dataSourceSelect.append(optLocal, optSparql);
    dataSourceSelect.value = cfg.dataSource === "sparql" ? "sparql" : "local";

    const dataSourceRow = document.createElement("div");
    dataSourceRow.className = "jp-CellScopeSettings-row";
    const dsLabel = document.createElement("span");
    dsLabel.textContent = "Data source";
    dataSourceRow.appendChild(dsLabel);
    dataSourceRow.appendChild(dataSourceSelect);

    const testButton = document.createElement("button");
    testButton.className = "jp-mod-styled";
    testButton.textContent = "Test SPARQL (list graphs)";
    const testStatus = document.createElement("div");
    testStatus.className = "jp-CellScopeSettings-status";
    testButton.addEventListener("click", async () => {
      testStatus.textContent = "Querying…";
      try {
        const graphs = await this._fetchGraphList(
          endpointInput.value.trim() || DEFAULT_SPARQL_ENDPOINT,
          tokenInput.value.trim(),
          userInput.value.trim(),
          passInput.value
        );
        if (!graphs.length) {
          testStatus.textContent = "No graphs returned.";
        } else {
          testStatus.textContent = `Graphs (${graphs.length}): ${graphs.slice(0, 5).join(", ")}${graphs.length > 5 ? " …" : ""}`;
        }
      } catch (err) {
        testStatus.textContent = `Error: ${this._stringifyError(err)}`;
      }
    });

    body.appendChild(makeField("SPARQL endpoint", endpointInput));
    body.appendChild(makeField("Auth token", tokenInput));
    body.appendChild(makeField("Username", userInput));
    body.appendChild(makeField("Password", passInput));
    body.appendChild(makeField("Retries", retriesInput));
    body.appendChild(makeField("Backoff (s)", backoffInput));
    body.appendChild(makeField("Index output file", outputInput));
    body.appendChild(dataSourceRow);
    body.appendChild(testButton);
    body.appendChild(testStatus);

    const dialog = new Dialog({
      title: "CellScope Settings",
      body: new Widget({ node: body }),
      buttons: [Dialog.cancelButton({ label: "Cancel" }), Dialog.okButton({ label: "Save" })]
    });

    const result = await dialog.launch();
    if (!result.button.accept) {
      return;
    }
    const nextCfg: CellScopeConfig = {
      endpoint: endpointInput.value.trim(),
      token: tokenInput.value.trim(),
      username: userInput.value.trim(),
      password: passInput.value,
      retries: Number(retriesInput.value) || 0,
      backoffSeconds: Number(backoffInput.value) || 0,
      outputPath: outputInput.value.trim(),
      dataSource: dataSourceSelect.value === "sparql" ? "sparql" : "local"
    };

    if (nextCfg.dataSource === "sparql") {
      if (!nextCfg.endpoint) {
        nextCfg.endpoint = DEFAULT_SPARQL_ENDPOINT;
      }
      try {
        await this._fetchGraphList(
          nextCfg.endpoint,
          nextCfg.token,
          nextCfg.username,
          nextCfg.password
        );
      } catch (err) {
        this._setStatus(
          `SPARQL check failed (${this._stringifyError(err)}); falling back to local.`,
          "warn"
        );
        nextCfg.dataSource = "local";
      }
    }

    this._saveConfig(nextCfg);
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
  private _filtersBtn!: HTMLButtonElement;
  private _filterOverlay!: HTMLElement;
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
  private _cellLabelMap: Map<number, string> = new Map();
  private _pendingTimeout: number | null = null;
  private _pendingChanges = false;
  private _notebookListeners: Array<() => void> = [];
  private _observedPanel: NotebookPanel | null = null;
  private _kernelWasBusySinceLastIdle = false;
  private _analyzeInFlight = false;
  private _rerunAfterCurrent = false;
  private _filtersVisible = false;
  private _lastFilterSignature = "";
  private _config: CellScopeConfig;
  private _settingsBtn!: HTMLButtonElement;
}
class WorkflowCaptureForm extends Widget {
  private _workflow: HTMLInputElement;
  private _outDir: HTMLInputElement;
  private _defaultNotebook: HTMLInputElement;
  private _notebookMap: HTMLTextAreaElement;
  private _skipCrates: HTMLInputElement;
  private _rootsList!: HTMLUListElement;
  private _manualRootInput!: HTMLInputElement;
  private _notebookRoots: string[] = [];

  constructor(initial: WorkflowCaptureInitial = {}, defaultOutDir = "out-lab/workflows") {
    super({ node: document.createElement("div") });
    this.addClass("jp-CellScopeWorkflowDialog");

    const description = document.createElement("p");
    description.textContent = "Capture a workflow (.naavrewf) and store per-node captures/manifests.";
    this.node.appendChild(description);

    this._workflow = this._createInputRow("Workflow file", "text", "Path to .naavrewf file");
    this._outDir = this._createInputRow("Output directory", "text", defaultOutDir);
    this._buildNotebookRootsRow();
    this._defaultNotebook = this._createInputRow("Default notebook", "text", "Fallback notebook path");
    this._notebookMap = this._createTextAreaRow(
      "Notebook map (optional)",
      "JSON object mapping node ids/titles to notebook paths"
    );
    this._skipCrates = document.createElement("input");
    this._skipCrates.type = "checkbox";
    const skipLabel = document.createElement("label");
    skipLabel.textContent = " Skip crate build (capture metadata only)";
    const skipWrapper = document.createElement("div");
    skipWrapper.className = "jp-CellScopeWorkflowDialog-row";
    skipWrapper.appendChild(this._skipCrates);
    skipWrapper.appendChild(skipLabel);
    this.node.appendChild(skipWrapper);

    this._applyInitial(initial, defaultOutDir);
  }

  getValue(): WorkflowCaptureDialogValue {
    const workflow = this._workflow.value.trim();
    if (!workflow) {
      throw new Error("Workflow path is required.");
    }
    const outDir = this._outDir.value.trim() || "out-lab/workflows";
    const notebookRoots = this._notebookRoots.length ? [...this._notebookRoots] : [];
    const defaultNotebook = this._defaultNotebook.value.trim() || null;
    const mapText = this._notebookMap.value.trim();
    let notebookMap: Record<string, string> = {};
    if (mapText) {
      try {
        const parsed = JSON.parse(mapText);
        if (!parsed || Array.isArray(parsed)) {
          throw new Error();
        }
        for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
          if (value === null || value === undefined) {
            continue;
          }
          notebookMap[String(key)] = String(value);
        }
      } catch (error) {
        throw new Error('Notebook map must be valid JSON object (e.g. {"node-id": "/path/notebook.ipynb"})');
      }
    }

    return {
      workflow,
      outDir,
      notebookRoots,
      notebookMap,
      defaultNotebook,
      skipCrates: this._skipCrates.checked,
    };
  }

  private _createInputRow(labelText: string, type: string, placeholder = ""): HTMLInputElement {
    const wrapper = document.createElement("div");
    wrapper.className = "jp-CellScopeWorkflowDialog-row";
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.type = type;
    input.placeholder = placeholder;
    wrapper.appendChild(label);
    wrapper.appendChild(input);
    this.node.appendChild(wrapper);
    return input;
  }

  private _applyInitial(initial: WorkflowCaptureInitial, defaultOutDir: string): void {
    if (initial.workflow) {
      this._workflow.value = initial.workflow;
    }
    this._outDir.value = initial.outDir ?? defaultOutDir;
    if (typeof initial.defaultNotebook === "string") {
      this._defaultNotebook.value = initial.defaultNotebook;
    }
    if (initial.notebookRoots && initial.notebookRoots.length) {
      initial.notebookRoots.forEach(root => this._addNotebookRoot(root));
    }
  }

  private _createTextAreaRow(labelText: string, placeholder = ""): HTMLTextAreaElement {
    const wrapper = document.createElement("div");
    wrapper.className = "jp-CellScopeWorkflowDialog-row";
    const label = document.createElement("label");
    label.textContent = labelText;
    const textarea = document.createElement("textarea");
    textarea.placeholder = placeholder;
    wrapper.appendChild(label);
    wrapper.appendChild(textarea);
    this.node.appendChild(wrapper);
    return textarea;
  }


  private _buildNotebookRootsRow(): void {
    const wrapper = document.createElement("div");
    wrapper.className = "jp-CellScopeWorkflowDialog-row jp-CellScopeWorkflowDialog-rootsRow";
    const label = document.createElement("label");
    label.textContent = "Notebook roots";
    wrapper.appendChild(label);

    this._rootsList = document.createElement("ul");
    this._rootsList.className = "jp-CellScopeWorkflowDialog-rootsList";
    wrapper.appendChild(this._rootsList);

    const controls = document.createElement("div");
    controls.className = "jp-CellScopeWorkflowDialog-rootsControls";
    this._manualRootInput = document.createElement("input");
    this._manualRootInput.type = "text";
    this._manualRootInput.placeholder = "Or paste a directory path";
    this._manualRootInput.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        this._addNotebookRoot(this._manualRootInput.value);
      }
    });
    controls.appendChild(this._manualRootInput);
    const manualAddBtn = document.createElement("button");
    manualAddBtn.type = "button";
    manualAddBtn.className = "jp-mod-styled";
    manualAddBtn.textContent = "Add path";
    manualAddBtn.addEventListener("click", () => this._addNotebookRoot(this._manualRootInput.value));
    controls.appendChild(manualAddBtn);
    wrapper.appendChild(controls);

    const hint = document.createElement("p");
    hint.className = "jp-CellScopeWorkflowDialog-helpText";
    hint.textContent = "Roots are searched in order; add multiple directories if your workflow spans repositories.";
    wrapper.appendChild(hint);

    this.node.appendChild(wrapper);
    this._renderNotebookRoots();
  }

  private _renderNotebookRoots(): void {
    this._rootsList.innerHTML = "";
    if (!this._notebookRoots.length) {
      const item = document.createElement("li");
      item.textContent = "No notebook roots selected.";
      item.className = "jp-CellScopeWorkflowDialog-rootsEmpty";
      this._rootsList.appendChild(item);
      return;
    }
    this._notebookRoots.forEach((root, index) => {
      const item = document.createElement("li");
      const code = document.createElement("code");
      code.textContent = root;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "jp-mod-styled";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => {
        this._notebookRoots.splice(index, 1);
        this._renderNotebookRoots();
      });
      item.appendChild(code);
      item.appendChild(remove);
      this._rootsList.appendChild(item);
    });
  }

  private _addNotebookRoot(value: string): void {
    const path = value.trim();
    if (!path) {
      return;
    }
    if (!this._notebookRoots.includes(path)) {
      this._notebookRoots.push(path);
    }
    if (this._manualRootInput) {
      this._manualRootInput.value = "";
    }
    this._renderNotebookRoots();
  }
}

class WorkflowCaptureResultWidget extends Widget {
  constructor(result: WorkflowCaptureResponse) {
    super({ node: document.createElement("div") });
    this.addClass("jp-CellScopeWorkflowResult");
    const summary = document.createElement("p");
    summary.textContent = `Captured ${result.captured}/${result.total} nodes. Manifest: ${result.manifest}`;
    this.node.appendChild(summary);
    const list = document.createElement("ul");
    result.nodes.forEach(node => {
      const item = document.createElement("li");
      item.textContent = `${node.title ?? node.id}: ${node.status}${node.error ? ` (${node.error})` : ""}`;
      list.appendChild(item);
    });
    this.node.appendChild(list);
  }
}

async function requestWorkflowCapture(
  settings: ServerConnection.ISettings,
  payload: Record<string, unknown>
): Promise<WorkflowCaptureResponse> {
  const url = URLExt.join(settings.baseUrl, "cellscope", "workflow", "capture");
  const response = await ServerConnection.makeRequest(
    url,
    {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" }
    },
    settings
  );

  if (!response.ok) {
    const bodyText = await response.text();
    let message = bodyText || `${response.status} ${response.statusText}`;
    try {
      const parsed = JSON.parse(bodyText);
      if (parsed && parsed.error) {
        message = parsed.error;
      }
    } catch {
      /* ignore JSON parse failures */
    }
    throw new Error(message);
  }

  const data = (await response.json()) as WorkflowCaptureResponse;
  return data;
}


function collectWorkflowInitial(
  app: JupyterFrontEnd,
  docManager: IDocumentManager | null,
  tracker: INotebookTracker | null
): WorkflowCaptureInitial {
  const initial: WorkflowCaptureInitial = {};
  const widget = app.shell.currentWidget;
  const context = docManager && widget ? docManager.contextForWidget(widget) : null;
  if (context && context.path) {
    const path = context.path;
    if (path.endsWith(".naavrewf")) {
      initial.workflow = path;
      const workflowsIdx = path.lastIndexOf("/workflows/");
      if (workflowsIdx !== -1) {
        const prefix = path.slice(0, workflowsIdx);
        initial.notebookRoots = [`${prefix}/codebase`];
      }
    }
  }
  const notebook = tracker?.currentWidget;
  const notebookPath = notebook?.context?.path;
  if (notebookPath && notebookPath.endsWith(".ipynb")) {
    initial.defaultNotebook = notebookPath;
  }
  return initial;
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: "cellscope-lab:plugin",
  autoStart: true,
  optional: [ICommandPalette, INotebookTracker, IDocumentManager],
  activate: (
    app: JupyterFrontEnd,
    palette: ICommandPalette | null,
    tracker: INotebookTracker | null,
    docManager: IDocumentManager | null
  ) => {
    const serverSettings = app.serviceManager.serverSettings;
    const documentManager = docManager ?? null;
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

    if (WORKFLOWS_ENABLED) {
      app.commands.addCommand(WORKFLOW_CMD, {
        label: "CellScope: Capture Workflow",
        execute: async () => {
          const initial = collectWorkflowInitial(app, documentManager, tracker ?? null);
          const form = new WorkflowCaptureForm(initial);
          const dialog = new Dialog({
            title: "CellScope Workflow Capture",
            body: form,
            buttons: [Dialog.cancelButton(), Dialog.okButton({ label: "Capture" })]
          });
          const result = await dialog.launch();
          if (!result.button.accept) {
            return;
          }
          let value: WorkflowCaptureDialogValue;
          try {
            value = form.getValue();
          } catch (error) {
            await showErrorMessage(
              "CellScope Workflow Capture",
              error instanceof Error ? error.message : String(error)
            );
            return;
          }
          const payload: Record<string, unknown> = {
            workflow: value.workflow,
            out_dir: value.outDir,
            notebook_roots: value.notebookRoots,
            notebook_map: value.notebookMap,
            default_notebook: value.defaultNotebook || undefined,
            skip_crates: value.skipCrates
          };
          try {
            const captureResult = await requestWorkflowCapture(serverSettings, payload);
            await new Dialog({
              title: "Workflow Captured",
              body: new WorkflowCaptureResultWidget(captureResult),
              buttons: [Dialog.okButton({ label: "Close" })]
            }).launch();
          } catch (error) {
            await showErrorMessage(
              "CellScope Workflow Capture",
              error instanceof Error ? error.message : String(error)
            );
          }
        }
      });
    }

    if (palette) {
      palette.addItem({ command: LIST_CMD, category: "CellScope" });
      palette.addItem({ command: GRAPH_CMD, category: "CellScope" });
      if (WORKFLOWS_ENABLED) {
        palette.addItem({ command: WORKFLOW_CMD, category: "CellScope" });
      }
    }
  }
};

export default plugin;
