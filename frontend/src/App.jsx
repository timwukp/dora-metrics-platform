import React, { useEffect, useState } from 'react'
import { useApi } from './hooks/useApi'
import { api } from './services/api'
import { DoraScoreCard } from './components/DoraScoreCard'
import { TrendChart } from './components/TrendChart'
import { ClaudeCodePanel } from './components/ClaudeCodePanel'
import { ReviewPanel } from './components/ReviewPanel'
import { LevelHistory } from './components/LevelHistory'
import Compare from './pages/Compare'

// Tiny hash-based router. Two pages — bringing in react-router for one
// extra view would dwarf its bundle size.
function useHashRoute() {
  const [route, setRoute] = useState(() => window.location.hash.slice(1) || 'dashboard')
  useEffect(() => {
    const onChange = () => setRoute(window.location.hash.slice(1) || 'dashboard')
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}

export default function App() {
  const route = useHashRoute()
  const [days, setDays] = useState(30)
  const [repo, setRepo] = useState(null)
  // null when "Last N days" is selected; an object {start, end, label}
  // when a sprint is picked.
  const [sprint, setSprint] = useState(null)

  const { data: repos, notReady: reposNotReady } = useApi(() => api.getRepos(), [])
  const { data: sprints } = useApi(() => api.getSprints(), [])

  const range = sprint
    ? { start: sprint.start, end: sprint.end }
    : { days }
  // Stringify so useApi's dep array is stable across re-renders.
  const rangeKey = JSON.stringify(range)

  const {
    data: dora, loading, error: doraError, notReady: doraNotReady,
  } = useApi(() => api.getDoraSummary(repo, range), [repo, rangeKey])
  const { data: timeline } = useApi(() => api.getTimeline(repo, 90), [repo])
  const { data: reviews } = useApi(() => api.getReviews(repo, range), [repo, rangeKey])
  const { data: levelHistory } = useApi(() => api.getLevelHistory(repo, 26), [repo])

  const df = dora?.deployment_frequency
  const lt = dora?.lead_time_for_changes
  const cfr = dora?.change_failure_rate
  const mttr = dora?.mean_time_to_recovery
  const cc = dora?.claude_code

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">DORA Metrics Platform</h1>
            <p className="text-sm text-gray-400">Developer Performance & AI-Assisted Development</p>
            <nav className="mt-2 flex gap-3 text-sm">
              <a
                href="#dashboard"
                className={route === 'dashboard'
                  ? 'text-white font-medium border-b-2 border-emerald-500 pb-0.5'
                  : 'text-gray-400 hover:text-white'}
              >
                Dashboard
              </a>
              <a
                href="#compare"
                className={route === 'compare'
                  ? 'text-white font-medium border-b-2 border-emerald-500 pb-0.5'
                  : 'text-gray-400 hover:text-white'}
              >
                Compare
              </a>
            </nav>
          </div>
          {route === 'dashboard' && (
          <div className="flex items-center gap-4">
            {repos && (
              <select
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
                onChange={(e) => setRepo(e.target.value || null)}
                value={repo || ''}
              >
                {repos.repos.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            )}
            {sprints?.configured && sprints.sprints?.length > 0 && (
              <select
                aria-label="Sprint selector"
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
                value={sprint ? `${sprint.start}|${sprint.end}` : ''}
                onChange={(e) => {
                  if (!e.target.value) { setSprint(null); return }
                  const [start, end] = e.target.value.split('|')
                  const match = sprints.sprints.find((s) => s.start === start && s.end === end)
                  setSprint(match ? { start, end, label: match.label } : null)
                }}
              >
                <option value="">Custom range</option>
                {[...sprints.sprints].reverse().map((s) => (
                  <option key={`${s.start}|${s.end}`} value={`${s.start}|${s.end}`}>
                    {s.label}{s.is_current ? ' (current)' : ''}
                  </option>
                ))}
              </select>
            )}
            <select
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm disabled:opacity-50"
              value={days}
              disabled={!!sprint}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={60}>Last 60 days</option>
              <option value={90}>Last 90 days</option>
            </select>
            <button
              type="button"
              aria-label="Export retro report"
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm hover:bg-gray-700"
              onClick={async () => {
                try {
                  const md = await api.getRetroMarkdown(repo, range, sprint?.label)
                  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  const tag = sprint?.label
                    ? sprint.label.replace(/\s+/g, '-').toLowerCase()
                    : `last-${days}-days`
                  a.download = `dora-retro-${tag}.md`
                  document.body.appendChild(a)
                  a.click()
                  a.remove()
                  URL.revokeObjectURL(url)
                } catch (e) {
                  alert(`Export failed: ${e.message}`)
                }
              }}
            >
              Export retro
            </button>
          </div>
          )}
        </div>
      </header>

      {route === 'compare' ? <Compare /> : (
      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8">
        {(doraNotReady || reposNotReady) && (
          <div className="rounded-md border border-yellow-700/50 bg-yellow-900/20 px-4 py-3 text-sm text-yellow-200">
            Backend is starting or its database isn’t ready yet. Retrying…
          </div>
        )}

        {doraError && (
          <div className="rounded-md border border-red-700/50 bg-red-900/20 px-4 py-3 text-sm text-red-200">
            Could not load metrics: {doraError}
          </div>
        )}

        {loading && !doraError && (
          <div className="text-center py-12 text-gray-400">Loading metrics...</div>
        )}

        {!loading && dora && (
          <>
            {/* DORA Score Cards */}
            <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <DoraScoreCard
                title="Deployment Frequency"
                value={df?.deploys_per_day}
                unit="deploys/day"
                level={df?.dora_level}
                description={`${df?.effective_deploy_count} deploys in period (${df?.merged_prs} PRs merged)`}
              />
              <DoraScoreCard
                title="Lead Time for Changes"
                value={lt?.median_hours}
                unit="hours (median)"
                level={lt?.dora_level}
                description={lt?.sample_size > 0 ? `P95: ${lt?.p95_hours}h | Sample: ${lt?.sample_size} PRs` : 'No merged PRs with commit data'}
              />
              <DoraScoreCard
                title="Change Failure Rate"
                value={cfr?.cfr_pct ?? cfr?.combined_cfr_pct}
                unit="%"
                level={cfr?.dora_level}
                description={`${cfr?.failures ?? 0} failures / ${cfr?.deployments ?? cfr?.total_merged_prs ?? 0} ${cfr?.source === 'merged_prs_fallback' ? 'merged PRs' : 'deploys'}`}
              />
              <DoraScoreCard
                title="Mean Time to Recovery"
                value={mttr?.median_hours}
                unit="hours (median)"
                level={mttr?.dora_level}
                description={mttr?.sample_size > 0 ? `${mttr?.from_incidents} incidents, ${mttr?.from_hotfix_prs} hotfixes` : 'No incidents/hotfixes in period'}
              />
            </section>

            {/* Trend Charts */}
            {timeline?.timeline && (
              <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {timeline.timeline[0]?.source === 'merged_prs_fallback' && (
                  <div className="lg:col-span-2 rounded-md border border-blue-700/40 bg-blue-900/20 px-3 py-2 text-xs text-blue-200">
                    Trends use merged PRs as a deploy proxy — no formal GitHub Deployment events found in this window. Wire up your CI/CD or GitHub Deployments to see the real deploy line.
                  </div>
                )}
                <TrendChart
                  data={timeline.timeline}
                  lines={[{ key: 'deployment_frequency', name: 'Deploys/Day' }]}
                  title={`Deployment Frequency Trend${timeline.timeline[0]?.source === 'merged_prs_fallback' ? ' (proxy: merged PRs)' : ''}`}
                  yAxisLabel="deploys/day"
                />
                <TrendChart
                  data={timeline.timeline}
                  lines={[{ key: 'lead_time_hours', name: 'Lead Time (hours)' }]}
                  title="Lead Time Trend"
                  yAxisLabel="hours"
                />
                <TrendChart
                  data={timeline.timeline}
                  lines={[{ key: 'change_failure_rate', name: 'CFR %' }]}
                  title="Change Failure Rate Trend"
                  yAxisLabel="%"
                />
                <TrendChart
                  data={timeline.timeline}
                  lines={[{ key: 'mttr_hours', name: 'MTTR (hours)' }]}
                  title="MTTR Trend"
                  yAxisLabel="hours"
                />
              </section>
            )}

            {/* DORA Level History */}
            <LevelHistory data={levelHistory} />

            {/* Review Activity */}
            <ReviewPanel data={reviews} />

            {/* Claude Code */}
            <ClaudeCodePanel data={cc} />

            {/* Data Details */}
            <section className="bg-gray-800 rounded-xl p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Metric Details</h3>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <DetailTable title="Deployment Frequency" rows={[
                  ['Formal Deployments', df?.formal_deployments],
                  ['Merged PRs (proxy)', df?.merged_prs],
                  ['Successful CI on main', df?.successful_ci_runs_on_main],
                  ['Effective Deploy Count', df?.effective_deploy_count],
                ]} />
                <DetailTable title="Lead Time Breakdown" rows={[
                  ['Coding Time (median)', lt?.breakdown?.coding_time_median_hours ? `${lt.breakdown.coding_time_median_hours}h` : '—'],
                  ['Review Time (median)', lt?.breakdown?.review_time_median_hours ? `${lt.breakdown.review_time_median_hours}h` : '—'],
                  ['Total (mean)', lt?.mean_hours ? `${lt.mean_hours}h` : '—'],
                ]} />
                <DetailTable title="Change Failures" rows={[
                  ['CI Failure Rate', cfr?.ci_failure_rate_pct != null ? `${cfr.ci_failure_rate_pct}%` : '—'],
                  ['Reverts', cfr?.reverts ?? 0],
                  ['Hotfixes', cfr?.hotfixes ?? 0],
                  ['Incidents', cfr?.incidents ?? 0],
                ]} />
                <DetailTable title="Recovery" rows={[
                  ['From Incidents', mttr?.from_incidents ?? 0],
                  ['From Hotfix PRs', mttr?.from_hotfix_prs ?? 0],
                  ['Median', mttr?.median_hours ? `${mttr.median_hours}h` : '—'],
                  ['P95', mttr?.p95_hours ? `${mttr.p95_hours}h` : '—'],
                ]} />
              </div>
            </section>
          </>
        )}
      </main>
      )}

      <footer className="border-t border-gray-800 px-6 py-4 text-center text-xs text-gray-500">
        DORA Metrics Platform v1.0 | Data sources: GitHub API, Claude Code Analytics API, CI/CD Workflows
      </footer>
    </div>
  )
}

function DetailTable({ title, rows }) {
  return (
    <div>
      <h4 className="text-sm font-medium text-gray-300 mb-2">{title}</h4>
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([label, value], i) => (
            <tr key={i} className="border-b border-gray-700/50">
              <td className="py-1.5 text-gray-400">{label}</td>
              <td className="py-1.5 text-right text-white font-medium">{value ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
