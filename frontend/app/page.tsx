"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const DEFAULT_QUERY = "tech jobs in USA";
const PAGE_SIZE = 12;

type Category = "CONFIRMED_AVAILABLE" | "HISTORICALLY_SUPPORTED" | "CONFIRMED_UNAVAILABLE" | "UNKNOWN" | "REVIEW";
type View = "ALL" | "POTENTIAL" | "UNAVAILABLE";
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
  UNKNOWN: { label: "No clear signal", short: "Unknown", color: "#8794a6" },
  REVIEW: { label: "Needs review", short: "Review", color: "#8b7cf6" },
};

const categoryRank: Record<Category, number> = {
  CONFIRMED_AVAILABLE: 0, HISTORICALLY_SUPPORTED: 1, UNKNOWN: 2, REVIEW: 3, CONFIRMED_UNAVAILABLE: 4,
};

function locationOf(job: Job) {
  return [job.city, job.state].filter(Boolean).join(", ") || "United States";
}

function postedLabel(value?: string | null) {
  if (!value) return "Date not listed";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date not listed";
  return `Posted ${date.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
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
    const start = angle; angle += (counts[key] / total) * 360;
    return `${categoryMeta[key].color} ${start}deg ${angle}deg`;
  });
  return <div className="insight-card">
    <div className="donut-wrap"><div className="donut" style={{ background: `conic-gradient(${stops.join(",")})` }}>
      <div className="donut-center"><strong>{jobs.length}</strong><span>roles analyzed</span></div>
    </div></div>
    <div className="legend">
      {(Object.keys(categoryMeta) as Category[]).filter((key) => counts[key] > 0).map((key) => <div className="legend-row" key={key}>
        <span className="legend-dot" style={{ background: categoryMeta[key].color }} /><span>{categoryMeta[key].label}</span>
        <strong>{counts[key]} · {Math.round((counts[key] / total) * 100)}%</strong>
      </div>)}
    </div>
  </div>;
}

export default function Home() {
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [activeQuery, setActiveQuery] = useState(DEFAULT_QUERY);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [category, setCategory] = useState<Category | "ALL">("ALL");
  const [view, setView] = useState<View>("ALL");
  const [withinResults, setWithinResults] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [loadingSeconds, setLoadingSeconds] = useState(0);
  const [error, setError] = useState("");
  const [source, setSource] = useState("");
  const started = useRef(false);

  async function search(searchQuery: string) {
    setLoading(true); setLoadingSeconds(0); setError(""); setCategory("ALL"); setView("ALL");
    setWithinResults(""); setVisibleCount(PAGE_SIZE);
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

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    search(DEFAULT_QUERY);
  }, []);

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => setLoadingSeconds((seconds) => seconds + 1), 1000);
    return () => window.clearInterval(timer);
  }, [loading]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const clean = query.trim();
    if (clean.length >= 2) search(clean);
  }

  const potentialCount = jobs.filter((job) => job.category !== "CONFIRMED_UNAVAILABLE").length;
  const filtered = useMemo(() => jobs
    .filter((job) => view === "ALL" || (view === "POTENTIAL" ? job.category !== "CONFIRMED_UNAVAILABLE" : job.category === "CONFIRMED_UNAVAILABLE"))
    .filter((job) => category === "ALL" || job.category === category)
    .filter((job) => `${job.title} ${job.company} ${locationOf(job)}`.toLowerCase().includes(withinResults.toLowerCase()))
    .sort((a, b) => categoryRank[a.category] - categoryRank[b.category] || (Date.parse(b.posted_at ?? "") || 0) - (Date.parse(a.posted_at ?? "") || 0)),
  [jobs, view, category, withinResults]);

  const loadingMessage = loadingSeconds < 5
    ? "Finding current job postings…"
    : loadingSeconds < 20
      ? "Analyzing sponsorship language and H-1B history…"
      : "A fresh search can take a little longer. We’re still working—no need to search again.";

  return <main>
    <nav className="nav shell"><a className="brand" href="#top"><span className="brand-mark">S</span>SponsorScope</a>
      <div className="nav-note"><span className="live-dot" /> Live evidence-backed job intelligence</div></nav>
    <section id="top" className="hero shell">
      <div className="eyebrow">Built for international talent</div>
      <h1>Search jobs with the <em>sponsorship evidence</em> in view.</h1>
      <p>Compare current posting language with verified historical H-1B activity—without treating past sponsorship as a promise.</p>
      <form className="search" onSubmit={submit}><span aria-hidden="true">⌕</span>
        <input aria-label="Search jobs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Role and location, e.g. data engineer in Chicago" />
        <button disabled={loading}>{loading ? "Analyzing…" : "Search jobs"}</button>
      </form>
      <div className="suggestions"><span>Popular searches:</span>{["Tech jobs in USA", "Data engineer in USA", "Software engineer in Austin"].map((item) =>
        <button key={item} disabled={loading} onClick={() => { setQuery(item); search(item); }}>{item}</button>)}</div>
    </section>
    <section className="results shell">
      <div className="section-heading"><div><span className="kicker">Live market snapshot</span><h2>{activeQuery}</h2>
        <p>{source === "CACHE" ? "Loaded instantly from our 24-hour search cache" : "Freshly retrieved, deduplicated, and analyzed"}</p></div>
        {!loading && !error && <div className="result-total"><strong>{jobs.length}</strong><span>unique roles</span></div>}
      </div>
      {error && <div className="error-state"><strong>We couldn’t complete this search.</strong><span>{error}</span><button onClick={() => search(activeQuery)}>Try again</button></div>}
      {loading && <div className="loading-state"><div className="spinner" /><strong>{loadingMessage}</strong><span>{loadingSeconds}s elapsed</span></div>}
      {!loading && !error && <>
        {jobs.length ? <Donut jobs={jobs} /> : <div className="empty-state">No current roles were returned. Try a more specific title or location.</div>}
        {!!jobs.length && <>
          <div className="results-toolbar">
            <div className="view-tabs" aria-label="Choose result view">
              <button className={view === "ALL" ? "active" : ""} onClick={() => { setView("ALL"); setVisibleCount(PAGE_SIZE); }}>All <span>{jobs.length}</span></button>
              <button className={view === "POTENTIAL" ? "active" : ""} onClick={() => { setView("POTENTIAL"); setVisibleCount(PAGE_SIZE); }}>Potential matches <span>{potentialCount}</span></button>
              <button className={view === "UNAVAILABLE" ? "active" : ""} onClick={() => { setView("UNAVAILABLE"); setVisibleCount(PAGE_SIZE); }}>Unavailable <span>{jobs.length - potentialCount}</span></button>
            </div>
            <input className="result-search" aria-label="Filter current results" placeholder="Filter title, company, or location" value={withinResults} onChange={(event) => { setWithinResults(event.target.value); setVisibleCount(PAGE_SIZE); }} />
          </div>
          <div className="filter-bar" aria-label="Filter jobs by sponsorship status">
            <button className={category === "ALL" ? "active" : ""} onClick={() => { setCategory("ALL"); setVisibleCount(PAGE_SIZE); }}>All signals</button>
            {(Object.keys(categoryMeta) as Category[]).map((key) => {
              const count = jobs.filter((job) => job.category === key).length;
              return count ? <button key={key} className={category === key ? "active" : ""} onClick={() => { setCategory(key); setVisibleCount(PAGE_SIZE); }}>{categoryMeta[key].short} <span>{count}</span></button> : null;
            })}
          </div>
          <p className="result-context">Showing {Math.min(visibleCount, filtered.length)} of {filtered.length} matching roles · strongest sponsorship signals shown first</p>
          <div className="job-grid">{filtered.slice(0, visibleCount).map((job) => {
            const meta = categoryMeta[job.category]; const evidence = job.current_policy_evidence?.[0]?.sentence;
            return <article className="job-card" key={job.id}><div className="card-top">
              <div className="company-logo">{job.company.slice(0, 1).toUpperCase()}</div><div className="job-title"><h3>{job.title}</h3><p>{job.company}</p></div>
              <span className="status" style={{ color: meta.color, background: `${meta.color}14`, borderColor: `${meta.color}35` }}><i style={{ background: meta.color }} />{meta.short}</span>
            </div><div className="meta"><span>⌖ {locationOf(job)}</span>{job.employment_type && <span>◷ {job.employment_type.replaceAll("_", " ")}</span>}<span>{postedLabel(job.posted_at)}</span></div>
              <div className="evidence"><span>Why this label</span><p>{evidence ?? (job.historical_support ? `${job.historical_evidence?.matched_dol_employer ?? job.company} has relevant certified H-1B filings on record.` : "No explicit sponsorship policy was found in this posting.")}</p></div>
              <div className="card-bottom"><small>Historical activity never overrides a current restriction.</small><a href={job.apply_url} target="_blank" rel="noreferrer">View job <span>↗</span></a></div>
            </article>;
          })}</div>
          {!filtered.length && <div className="empty-state compact">No roles match these filters.</div>}
          {visibleCount < filtered.length && <button className="load-more" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>Show more roles</button>}
        </>}
      </>}
    </section>
    <footer><div className="shell"><a className="brand" href="#top"><span className="brand-mark">S</span>SponsorScope</a><p>Evidence-based estimates only—not immigration or legal advice.</p></div></footer>
  </main>;
}
