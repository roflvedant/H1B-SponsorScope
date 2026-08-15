"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const DEFAULT_QUERY = "tech jobs in USA";

type Category = "CONFIRMED_AVAILABLE" | "HISTORICALLY_SUPPORTED" | "CONFIRMED_UNAVAILABLE" | "UNKNOWN" | "REVIEW";
type Evidence = { rule_id?: string; sentence?: string; matched_text?: string };
type Job = {
  id: string; title: string; company: string; city?: string | null; state?: string | null;
  employment_type?: string | null; posted_at?: string | null; apply_url: string;
  current_policy: string; category: Category; current_policy_evidence: Evidence[];
  historical_support: boolean; historical_evidence?: {
    matched_dol_employer?: string; matched_dol_job_title?: string; certified_lca_cases?: number;
  } | null;
};
type SearchResponse = { query: string; source: string; count: number; jobs: Job[] };

const categoryMeta: Record<Category, { label: string; short: string; color: string }> = {
  CONFIRMED_AVAILABLE: { label: "Confirmed sponsorship", short: "Confirmed", color: "#17a673" },
  HISTORICALLY_SUPPORTED: { label: "Historically supported", short: "Historical", color: "#f0b429" },
  CONFIRMED_UNAVAILABLE: { label: "Sponsorship unavailable", short: "Unavailable", color: "#ef5b5b" },
  UNKNOWN: { label: "No clear signal", short: "Unknown", color: "#cbd2da" },
  REVIEW: { label: "Needs review", short: "Review", color: "#8b7cf6" },
};

function locationOf(job: Job) {
  return [job.city, job.state].filter(Boolean).join(", ") || "United States";
}

function Donut({ jobs }: { jobs: Job[] }) {
  const counts = useMemo(() => {
    const initial = Object.fromEntries(Object.keys(categoryMeta).map((key) => [key, 0])) as Record<Category, number>;
    jobs.forEach((job) => initial[job.category]++);
    return initial;
  }, [jobs]);
  const total = jobs.length || 1;
  let angle = 0;
  const stops = (Object.keys(categoryMeta) as Category[]).map((key) => {
    const start = angle;
    angle += (counts[key] / total) * 360;
    return `${categoryMeta[key].color} ${start}deg ${angle}deg`;
  });
  return (
    <div className="insight-card">
      <div className="donut-wrap">
        <div className="donut" style={{ background: `conic-gradient(${stops.join(",")})` }}>
          <div className="donut-center"><strong>{jobs.length}</strong><span>open roles</span></div>
        </div>
      </div>
      <div className="legend">
        {(Object.keys(categoryMeta) as Category[]).filter((key) => counts[key] > 0).map((key) => (
          <div className="legend-row" key={key}>
            <span className="legend-dot" style={{ background: categoryMeta[key].color }} />
            <span>{categoryMeta[key].label}</span>
            <strong>{Math.round((counts[key] / total) * 100)}%</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Home() {
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [activeQuery, setActiveQuery] = useState(DEFAULT_QUERY);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [filter, setFilter] = useState<Category | "ALL">("ALL");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [source, setSource] = useState("");

  async function search(searchQuery: string) {
    setLoading(true); setError(""); setFilter("ALL");
    try {
      const response = await fetch(`${API_URL}/search`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: searchQuery, max_pages: 3, force_refresh: false }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "Search could not be completed.");
      }
      const data: SearchResponse = await response.json();
      setJobs(data.jobs ?? []); setSource(data.source); setActiveQuery(searchQuery);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The search service is unavailable.");
    } finally { setLoading(false); }
  }

  useEffect(() => { search(DEFAULT_QUERY); }, []);
  function submit(event: FormEvent) {
    event.preventDefault();
    const clean = query.trim();
    if (clean.length >= 2) search(clean);
  }
  const filtered = filter === "ALL" ? jobs : jobs.filter((job) => job.category === filter);

  return (
    <main>
      <nav className="nav shell">
        <a className="brand" href="#top"><span className="brand-mark">S</span>SponsorScope</a>
        <div className="nav-note"><span className="live-dot" /> Evidence-backed job intelligence</div>
      </nav>
      <section id="top" className="hero shell">
        <div className="eyebrow">Built for international talent</div>
        <h1>Find roles with a clearer path to <em>sponsorship.</em></h1>
        <p>We combine current job-posting language with verified historical H-1B activity—so you can search smarter, with the evidence in view.</p>
        <form className="search" onSubmit={submit}>
          <span aria-hidden="true">⌕</span>
          <input aria-label="Search jobs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Try ‘mechanical engineer in Chicago’" />
          <button disabled={loading}>{loading ? "Searching…" : "Search jobs"}</button>
        </form>
        <div className="suggestions"><span>Try:</span>{["Data engineer in USA", "Mechanical engineer in Indianapolis", "Software engineer in Austin"].map((item) => <button key={item} onClick={() => { setQuery(item); search(item); }}>{item}</button>)}</div>
      </section>
      <section className="results shell">
        <div className="section-heading">
          <div><span className="kicker">Market snapshot</span><h2>{activeQuery}</h2><p>{source === "CACHE" ? "Loaded from our recent search cache" : "Freshly retrieved and analyzed"}</p></div>
          {!loading && !error && <div className="result-total"><strong>{jobs.length}</strong><span>roles analyzed</span></div>}
        </div>
        {error && <div className="error-state"><strong>We couldn’t load the jobs.</strong><span>{error}</span><button onClick={() => search(activeQuery)}>Try again</button></div>}
        {loading && <div className="loading-state"><div className="spinner" /><strong>Analyzing sponsorship signals…</strong><span>Checking current policies and historical evidence.</span></div>}
        {!loading && !error && <>
          <Donut jobs={jobs} />
          <div className="filter-bar" aria-label="Filter jobs by sponsorship status">
            <button className={filter === "ALL" ? "active" : ""} onClick={() => setFilter("ALL")}>All <span>{jobs.length}</span></button>
            {(Object.keys(categoryMeta) as Category[]).map((key) => {
              const count = jobs.filter((job) => job.category === key).length;
              return count ? <button key={key} className={filter === key ? "active" : ""} onClick={() => setFilter(key)}>{categoryMeta[key].short} <span>{count}</span></button> : null;
            })}
          </div>
          <div className="job-grid">
            {filtered.map((job) => {
              const meta = categoryMeta[job.category];
              const evidence = job.current_policy_evidence?.[0]?.sentence;
              return <article className="job-card" key={job.id}>
                <div className="card-top">
                  <div className="company-logo">{job.company.slice(0, 1).toUpperCase()}</div>
                  <div className="job-title"><h3>{job.title}</h3><p>{job.company}</p></div>
                  <span className="status" style={{ color: meta.color, background: `${meta.color}14`, borderColor: `${meta.color}35` }}><i style={{ background: meta.color }} />{meta.short}</span>
                </div>
                <div className="meta"><span>⌖ {locationOf(job)}</span>{job.employment_type && <span>◷ {job.employment_type.replaceAll("_", " ")}</span>}</div>
                <div className="evidence"><span>Why this label</span><p>{evidence ?? (job.historical_support ? `${job.historical_evidence?.matched_dol_employer ?? job.company} has relevant certified H-1B filings on record.` : "No explicit sponsorship policy was found in this posting.")}</p></div>
                <div className="card-bottom"><small>Historical activity never overrides a current restriction.</small><a href={job.apply_url} target="_blank" rel="noreferrer">Apply now <span>↗</span></a></div>
              </article>;
            })}
          </div>
          {!filtered.length && <div className="empty-state">No roles match this filter.</div>}
        </>}
      </section>
      <footer><div className="shell"><a className="brand" href="#top"><span className="brand-mark">S</span>SponsorScope</a><p>Policy labels are evidence-based estimates, not immigration or legal advice.</p></div></footer>
    </main>
  );
}
