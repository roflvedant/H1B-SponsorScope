# SponsorScope

Evidence-backed job intelligence for international candidates searching for
U.S. roles with clearer sponsorship signals.

SponsorScope combines language from current job postings with historical
certified H-1B filing activity. Instead of presenting historical activity as a
promise of future sponsorship, it keeps current policy, historical evidence,
and uncertain results visibly separate.

## Why this project exists

Job boards rarely expose sponsorship eligibility as structured data. Important
details are buried inside descriptions, expressed inconsistently, or omitted
entirely. Historical H-1B records can provide useful context, but employer
history alone does not prove that a particular role is eligible today.

SponsorScope addresses this by producing explainable categories:

- **Confirmed sponsorship** — the current posting explicitly offers support.
- **Historically supported** — no current restriction was found, and the
  employer and occupation match certified historical H-1B activity.
- **Sponsorship unavailable** — the posting contains an explicit restriction.
- **Needs review** — evidence is conflicting or matching is uncertain.
- **No clear signal** — the available evidence does not justify a conclusion.

## V1 features

- Live U.S. job search through the JSearch API.
- Timestamped raw snapshots for reproducible processing.
- Stable job normalization and deterministic deduplication.
- Explainable rules-based sponsorship classification.
- Employer normalization, verified aliases, and conservative fuzzy matching.
- Occupation resolution using normalized titles and DOL SOC evidence.
- Versioned classification and historical-matching results.
- PostgreSQL persistence with Alembic migrations.
- Search-result caching to reduce external API usage and response time.
- FastAPI endpoints for search, jobs, dashboard summaries, and health checks.
- Responsive Next.js interface with category filters, evidence, and job links.
- Automated regression tests and an offline classifier evaluation workflow.

## Architecture

```text
JSearch API
    |
    v
Raw timestamped JSON
    |
    v
Normalization -> relevance -> deduplication
    |
    +---------------------------+
    |                           |
    v                           v
Current-policy classifier   Historical DOL matcher
                                |
                                +-- employer resolution
                                +-- occupation/SOC resolution
    |                           |
    +-------------+-------------+
                  |
                  v
              PostgreSQL
                  |
                  v
          FastAPI REST service
                  |
                  v
          Next.js web interface
```

## Technology stack

### Backend and data pipeline

- Python 3.12
- FastAPI and Uvicorn
- Pandas and OpenPyXL
- SQLAlchemy 2
- PostgreSQL and Psycopg
- Alembic
- Pytest

### Frontend

- Next.js 16
- React 19
- TypeScript
- CSS

### Data sources

- JSearch for current job postings.
- U.S. Department of Labor LCA disclosure data for certified historical H-1B
  activity.

## Classification evaluation

The rules-v3 classifier was evaluated against 281 reviewed examples.

| Metric | Result |
| --- | ---: |
| Overall accuracy | 97.9% |
| Definite-decision coverage | 24.9% |
| AVAILABLE F1 | 100.0% |
| UNAVAILABLE F1 | 95.4% |
| UNKNOWN F1 | 98.6% |

Accuracy and coverage answer different questions. The classifier deliberately
returns `UNKNOWN` when it cannot find explicit evidence, favoring precision and
explainability over aggressive guessing. The evaluation set is class-imbalanced
and should not be interpreted as a guarantee on every job source or occupation.

Run the evaluation locally with:

```powershell
& ".\.venv\Scripts\python.exe" -m scripts.evaluate_accuracy evaluate
```

## Local setup

### 1. Clone and configure Python

```powershell
git clone <your-repository-url>
Set-Location h1b_project_refactor

python -m venv .venv
& ".\.venv\Scripts\Activate.ps1"
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and replace the JSearch placeholder:

```powershell
Copy-Item ".env.example" ".env"
```

### 2. Start PostgreSQL

Docker Desktop must be running.

```powershell
docker compose up -d postgres
docker compose ps
```

Apply the database migrations:

```powershell
& ".\.venv\Scripts\python.exe" -m alembic upgrade head
```

### 3. Prepare data

Place the DOL LCA disclosure workbook in:

```text
data/raw/dol/
```

Its filename must match:

```text
LCA_Disclosure_Data_*.xlsx
```

Fetch current jobs, process them, and load the result:

```powershell
& ".\.venv\Scripts\python.exe" fetch_main.py --pages 1
& ".\.venv\Scripts\python.exe" main.py
& ".\.venv\Scripts\python.exe" load_database.py
```

Generated raw, processed, and enriched datasets are intentionally excluded from
Git because they are reproducible and may be large.

### 4. Start FastAPI

```powershell
& ".\.venv\Scripts\python.exe" -m uvicorn app.api.main:app --reload
```

The service will be available at:

- API: `http://127.0.0.1:8000`
- Interactive documentation: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

### 5. Start the frontend

Create `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Then run:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Main commands

| Command | Purpose |
| --- | --- |
| `python fetch_main.py --pages 1` | Fetch and preserve raw jobs |
| `python main.py` | Normalize, classify, and historically match jobs |
| `python load_database.py` | Upsert the newest enriched snapshot |
| `pytest -q` | Run regression tests |
| `uvicorn app.api.main:app --reload` | Start the API |
| `npm run dev` | Start the frontend |
| `npm run build` | Verify the production frontend build |

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health check |
| `GET` | `/jobs` | List and filter stored jobs |
| `GET` | `/dashboard` | Return category counts and percentages |
| `POST` | `/search` | Search, enrich, cache, and return jobs |

Example search request:

```json
{
  "query": "data engineer in USA",
  "max_pages": 1,
  "force_refresh": false
}
```

## Testing

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q
```

The V1 test suite covers:

- positive, negative, conflicting, and unknown sponsorship language;
- citizenship, work-authorization, H-1B transfer, and clearance wording;
- title relevance and false-positive rejection;
- SOC inference and occupation matching;
- prevention of employer-only historical false positives.

## Evidence and product boundaries

- Historical certification activity is evidence of past behavior, not a promise
  that an employer will sponsor a specific candidate or current position.
- An explicit current-posting restriction always overrides historical evidence.
- `UNKNOWN` means no conclusive language was found; it does not mean sponsorship
  is available.
- Results are informational and are not immigration or legal advice.

## Planned improvements

- Public deployment of the API, database, and frontend.
- Scheduled ingestion and monitoring.
- Broader reviewed evaluation data across occupations.
- Optional LLM review for uncertain cases, without overriding explicit rules.
- Authentication, saved searches, and alerts.
- Observability for provider latency, failures, and classifier drift.

## License

This project is currently provided for portfolio and educational use. Add a
formal open-source license before permitting redistribution.
