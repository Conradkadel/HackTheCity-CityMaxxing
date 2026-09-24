# Research background

Early analysis done before the app existed. It explains *why* the app is built the way it is (stop passages,
leader/headway, the bunching definition) and holds findings used in the pitch. Nothing here is needed to run the app.

| File | What it is |
| --- | --- |
| `DATA_FINDINGS.md` | 15 findings from the first data tests (CM corridors + CARRIS × Waze), e.g. that most close arrivals are between different lines. |
| `DATASET_DESIGN.md` | Why the data is modelled as stop passages, which raw columns are dropped and why, with evidence numbers. |
| `dataset_evidence.py` | Re-runs every number quoted in `DATASET_DESIGN.md` (needs the raw TML files, DuckDB, pandas). Run from the challenge folder. |
| `03_bunching_deep_eda_and_model.ipynb` | Deep exploratory analysis and the first model experiments, with plots. |

The current, app-level method is documented one folder up: [`../FINDINGS.md`](../FINDINGS.md) and [`../BUNCHING_MODEL.md`](../BUNCHING_MODEL.md).
