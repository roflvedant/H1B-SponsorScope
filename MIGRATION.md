# Migration from the prototype

Copy the refactored files into a new branch or a separate project directory first.
Do not delete the working prototype until the new pipeline completes successfully.

## Old-to-new file map

| Prototype file | Refactored file |
|---|---|
| `app/config/config.py` | `app/config/settings.py` |
| `app/config/ingestion.py` | `app/extraction/jsearch.py` |
| `app/config/transformation.py` | `app/pipeline/transformation.py` |
| New | `app/pipeline/relevance.py` |
| `app/config/classification.py` | `app/enrichment/classification.py` |
| New | `app/enrichment/sponsorship_rules.py` |
| `app/config/historical.py` | `app/enrichment/historical.py` |
| `app/config/matching.py` | `app/enrichment/matching.py` |
| `app/config/alias_candidates.py` | `app/enrichment/alias_candidates.py` |
| New | `app/pipeline/runner.py` |

## Data that should be copied

- `.env` stays local and must never be committed.
- Copy the DOL workbook to `data/raw/dol/`.
- Copy `company_aliases.csv` to `data/references/`.
- Existing raw JSearch snapshots may be copied to `data/raw/jsearch/`.

## Commands

```powershell
& "C:\msys64\ucrt64\bin\python.exe" fetch_main.py
& "C:\msys64\ucrt64\bin\python.exe" main.py
& "C:\msys64\ucrt64\bin\python.exe" -m pytest
```

Run multiple searches by repeating `--query`:

```powershell
& "C:\msys64\ucrt64\bin\python.exe" fetch_main.py `
  --query "data engineer jobs in United States" `
  --query "analytics engineer jobs in United States" `
  --pages 2
```

The final output uses `current_policy` and `historical_support` as separate facts.
