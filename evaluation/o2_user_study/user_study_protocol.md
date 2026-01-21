# User Study Protocol — CellScope (RAVL.ipynb)

## Study goal
Test whether CellScope improves notebook comprehension and navigation (without executing code) compared to baseline JupyterLab (scroll + search).

## Research questions
- **Speed:** Do participants answer provenance/dependency questions faster with CellScope than with baseline JupyterLab?
- **Accuracy:** Do they answer more correctly (or with fewer misses)?
- **Confidence & workload:** Do they feel more confident / less mentally taxed?

## Conditions
- **C0: Baseline (JupyterLab-only)** — notebook UI: scroll, search, outline, find-in-notebook.
- **C2: CellScope** — Analyze + list/filter + graph.

No ProvBook condition. In the thesis, note that ProvBook targets execution-time provenance while this study is execution-agnostic (“no-run”).

## Study design (10–15 minutes)
- **Within-subject:** each participant does both C0 and C2.
- **Counterbalanced order:**
  - Group A: C0 → C2
  - Group B: C2 → C0
- **Task sets A/B to reduce memory effects:**
  - In the second condition, use a different but equivalent target set.

## Timing per participant (target: 12–14 min)
- Consent + rules (1 min)
- Short training (C2 only) (1 min)
- Condition 1 tasks (3–4 min)
- 2 quick rating questions (30 sec)
- Condition 2 tasks (3–4 min)
- 2 quick rating questions (30 sec)
- Debrief (1–2 min)

## Materials & setup (researcher)
- **Sanitized notebook**: `evaluation/user_study/RAVL_sanitized.ipynb`.
- **Cross-notebook files**:
  - `evaluation/user_study/multi_kernel_demo.ipynb`
  - `evaluation/user_study/exhaustive_python.ipynb`
- Hard rule: participants must **not execute** any cells.
- Fresh session (incognito) to avoid saved UI state.
- For CellScope condition: click **Analyze** once before starting tasks (or make “Click Analyze” the first task step, but keep it consistent).

## Participant scripts

### Briefing (read verbatim)
“You’ll answer questions about where things are defined, what depends on what, and how files flow through the notebook. Do not run cells. We’re measuring speed and correctness of navigation/comprehension.”

### After each condition (2 questions)
- “How confident are you that your answers were correct?” (1–5)
- “How mentally demanding was this?” (1–5)

### End debrief (pick 2)
- “What felt easiest/hardest?”
- “What feature did you wish you had?”
- “Would you use this in your own work? Why/why not?”

## Tasks (core comparative tasks)

For each task, use the answer key below (cell numbers + header labels). Tasks 1 and 3 use `RAVL_sanitized.ipynb`. Tasks 2 use `multi_kernel_demo.ipynb` + `exhaustive_python.ipynb` to demonstrate cross-notebook provenance.

### Task Set A (use in Condition 1 for Group A; Condition 2 for Group B)

**Task 1 — Impact / dependency tracing (variable)**
Prompt: “Find where `conf_local_radar_db` is defined and name two downstream cells that depend on it (directly or indirectly).”

Answer key (RAVL_sanitized):
- Definition: **cell 4** (`# cell_4_do_not_containerise`, configuration)
- Downstream cells: **cell 6** (`# cell_6_initializer`) and **cell 10** (`# cell_10_pvol_vp_converter`)

**Task 2 — File handoff (producer → consumer, cross-notebook)**
Prompt: “The file `climate_readings.csv` is produced in `multi_kernel_demo.ipynb` and later read in `exhaustive_python.ipynb`. Identify the producer cell and the first consumer cell.”

Answer key:
- Producer: **multi_kernel_demo cell 2** (`# materialize outputs for hand-off`)
- First consumer: **exhaustive_python cell 2** (`pd.read_csv("examples/data_outputs/climate_readings.csv")`)
- File path: `examples/data_outputs/climate_readings.csv`

**Task 3 — “What produced this output?” (reverse provenance)**
Prompt: “You see ODIM files under `conf_local_odim`. Identify the cell that produces them and one key input it depends on.”

Answer key (RAVL_sanitized):
- Producer: **cell 9** (`# cell_9_knmi_to_odim_converter`)
- Key input: `knmi_pvol_paths` (from **cell 8**)

### Task Set B (use in Condition 1 for Group B; Condition 2 for Group A)

**Task 1 — Impact / dependency tracing (variable)**
Prompt: “Find where `secret_minio_access_key` is defined and name two downstream cells that depend on it (directly or indirectly).”

Answer key (RAVL_sanitized):
- Definition: **cell 2** (`# cell_2_do_not_containerise`, SecretsProvider)
- Downstream cells: **cell 5** (`# cell_5_do_not_containerise_v60`) and **cell 14** (`# cell_14_s3_ppi_uploader`)

**Task 2 — File read (cross-notebook, read-only)**
Prompt: “The file `examples/data_outputs/summary.json` is produced in `exhaustive_python.ipynb` and read in `multi_kernel_demo.ipynb`. Identify the cell where it is read.”

Answer key:
- Reader: **multi_kernel_demo cell 5** (`# downstream analysis using both shared data and file reads`), the `open("examples/data_outputs/summary.json", "r")` call.

**Task 3 — “What produced this output?” (reverse provenance)**
Prompt: “You see VP outputs under `conf_local_vp`. Identify the cell that produces them and one key input it depends on.”

Answer key (RAVL_sanitized):
- Producer: **cell 10** (`# cell_10_pvol_vp_converter`)
- Key input: `odim_pvol_paths` (from **cell 9**)

## Scoring for each task
- **Correct:** all required elements are correct.
- **Partial:** one element missing/wrong.
- **Incorrect:** wrong elements.

## Optional (CellScope-only) task — Export RO-Crate
Not part of the C0 vs C2 comparison.

Prompt: “Export an RO-Crate and point to where the exported package contains: (i) the graph summary and (ii) the RO-Crate metadata file.”

Answer key:
- `ro-crate-metadata.json`
- `cell_graph.graphml` or `cell_graph.html`

## Order and assignment (exact procedure)
1) Assign participant to Group A or B (alternate participants).
2) Pick Task Set A for the first condition and Task Set B for the second condition.
3) Start timer per task when you finish reading the prompt.
4) Stop timer when they give their final answer.
5) Record: duration + outcome + short note (strategy used: search, outline, CellScope filters, graph).

## Data recorded (minimal but sufficient)
- Per task: time (sec), outcome (C/P/I), strategy note.
- Per condition: confidence 1–5, mental demand 1–5.
- Overall: preferred condition and 1–2 sentence reason.

## Sample size (practical)
6–10 participants is realistic for a master’s thesis and still yields useful paired comparisons.

## Notes / required notebook changes
- Use a **sanitized** version of `RAVL.ipynb` (fake endpoints/keys).
- Keep variable names intact so answer keys remain valid.
- The user-study copy of `multi_kernel_demo.ipynb` includes literal file paths for provenance capture:
  - writes `examples/data_outputs/climate_readings.csv`
  - reads `examples/data_outputs/summary.json`
- If you change cell order or headers, update the answer keys above.
