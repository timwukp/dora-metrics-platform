import React from 'react'

export function ClaudeCodePanel({ data }) {
  if (!data || data.total_sessions === 0) {
    return (
      <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
        <h3 className="text-lg font-semibold text-white mb-4">Claude Code Analytics</h3>
        <p className="text-gray-500">No Claude Code data available. Configure DORA_CLAUDE_CODE_ADMIN_KEY to enable.</p>
      </div>
    )
  }

  const stats = [
    { label: 'Sessions', value: data.total_sessions },
    { label: 'Lines Added', value: data.lines_of_code?.added?.toLocaleString() },
    { label: 'Lines Removed', value: data.lines_of_code?.removed?.toLocaleString() },
    { label: 'Commits Created', value: data.commits_created },
    { label: 'PRs Created', value: data.prs_created },
    { label: 'Acceptance Rate', value: `${data.acceptance_rate_pct}%` },
    { label: 'Total Cost', value: `$${data.total_cost_usd}` },
    { label: 'Active Users', value: data.unique_users },
  ]

  return (
    <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
      <h3 className="text-lg font-semibold text-white mb-4">Claude Code Analytics</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((s) => (
          <div key={s.label} className="text-center">
            <div className="text-2xl font-bold text-blue-400">{s.value}</div>
            <div className="text-xs text-gray-400 mt-1">{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
