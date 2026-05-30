import React from 'react'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'

// Issue #19: side-by-side trend direction across all configured repos.
// Goal of this page is _identifying shared bottlenecks_, not ranking teams.
// We deliberately surface direction (improving / declining) instead of raw
// absolute numbers, so a faster team isn't visually penalised for working
// on harder code, and a slower one isn't shamed.

const METRICS = [
  { key: 'deployment_frequency', label: 'Deploy Freq',
    headline: 'deploys_per_day', higherIsBetter: true },
  { key: 'lead_time_for_changes', label: 'Lead Time',
    headline: 'median_hours', higherIsBetter: false },
  { key: 'change_failure_rate', label: 'CFR',
    headline: 'cfr_pct', higherIsBetter: false },
  { key: 'mean_time_to_recovery', label: 'MTTR',
    headline: 'median_hours', higherIsBetter: false },
]

function trendArrow(current, prior, higherIsBetter) {
  if (current == null || prior == null) return { glyph: '—', color: 'text-gray-500', label: 'no data' }
  if (current === prior) return { glyph: '→', color: 'text-gray-400', label: 'flat' }
  const improving = higherIsBetter ? current > prior : current < prior
  return improving
    ? { glyph: '↑', color: 'text-emerald-400', label: 'improving' }
    : { glyph: '↓', color: 'text-red-400', label: 'declining' }
}

function RepoRow({ repo }) {
  const { data: current } = useApi(() => api.getDoraSummary(repo, { days: 30 }), [repo])
  const { data: prior } = useApi(() => {
    const end = new Date(Date.now() - 30 * 86400_000).toISOString()
    const start = new Date(Date.now() - 60 * 86400_000).toISOString()
    return api.getDoraSummary(repo, { start, end })
  }, [repo])

  return (
    <tr className="border-t border-gray-700/50">
      <td className="py-2 pr-4 text-sm font-medium text-white">{repo}</td>
      {METRICS.map((m) => {
        const cur = current?.[m.key]?.[m.headline]
        const prv = prior?.[m.key]?.[m.headline]
        const trend = trendArrow(cur, prv, m.higherIsBetter)
        const level = current?.[m.key]?.dora_level || '—'
        return (
          <td key={m.key} className="py-2 px-2 text-center">
            <div className="flex items-center justify-center gap-2">
              <span className={`text-lg ${trend.color}`} aria-label={trend.label}>
                {trend.glyph}
              </span>
              <span className="text-xs text-gray-300">{level}</span>
            </div>
          </td>
        )
      })}
    </tr>
  )
}

export default function Compare() {
  const { data: repos, notReady } = useApi(() => api.getRepos(), [])
  const list = repos?.repos || []

  return (
    <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
      <div className="rounded-md border border-blue-700/40 bg-blue-900/20 px-4 py-3 text-sm text-blue-200">
        This view is for identifying <strong>shared challenges</strong> across teams,
        not ranking them. Direction (improving / declining) over the last 30 days
        compared to the previous 30 days, alongside the current DORA level.
      </div>

      {notReady && (
        <div className="text-sm text-yellow-200">Backend not ready yet…</div>
      )}

      {!list.length ? (
        <div className="text-gray-400 text-sm">No repos configured.</div>
      ) : (
        <section className="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <table className="w-full">
            <thead>
              <tr className="text-gray-400 text-xs">
                <th className="text-left pr-4 pb-2 font-medium">Repository</th>
                {METRICS.map((m) => (
                  <th key={m.key} className="px-2 pb-2 font-medium">{m.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map((r) => <RepoRow key={r} repo={r} />)}
            </tbody>
          </table>
        </section>
      )}
    </main>
  )
}
