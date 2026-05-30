import React from 'react'

const METRIC_LABELS = {
  deployment_frequency: 'Deploy Freq',
  lead_time_for_changes: 'Lead Time',
  change_failure_rate: 'CFR',
  mean_time_to_recovery: 'MTTR',
}

const LEVEL_COLOR = {
  Elite:  'bg-emerald-500',
  High:   'bg-green-500',
  Medium: 'bg-yellow-500',
  Low:    'bg-red-500',
}

function levelClass(level) {
  return LEVEL_COLOR[level] || 'bg-gray-600'
}

export function LevelHistory({ data }) {
  const snapshots = data?.snapshots || []
  if (!snapshots.length) {
    return (
      <section className="bg-gray-800 rounded-xl p-6 border border-gray-700">
        <h3 className="text-lg font-semibold text-white mb-2">DORA Level History</h3>
        <p className="text-sm text-gray-400">
          No weekly snapshots yet — they accumulate over time.
          Run <code className="text-gray-300">POST /api/v1/collect/level-snapshots?weeks=12</code> to backfill.
        </p>
      </section>
    )
  }

  return (
    <section className="bg-gray-800 rounded-xl p-6 border border-gray-700">
      <h3 className="text-lg font-semibold text-white mb-4">DORA Level History</h3>
      <div className="overflow-x-auto">
        <table className="text-xs min-w-full">
          <thead>
            <tr className="text-gray-400">
              <th className="text-left pr-3 pb-2 font-medium">Metric</th>
              {snapshots.map((s) => (
                <th key={s.week_start} className="px-1 pb-2 font-normal whitespace-nowrap">
                  {s.week_start.slice(5, 10)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.keys(METRIC_LABELS).map((metric) => (
              <tr key={metric} className="border-t border-gray-700/40">
                <td className="text-gray-300 pr-3 py-1.5 whitespace-nowrap">
                  {METRIC_LABELS[metric]}
                </td>
                {snapshots.map((s) => {
                  const cell = s.metrics?.[metric]
                  return (
                    <td key={s.week_start} className="px-1 py-1.5 text-center">
                      <span
                        title={`${cell?.level || '—'}${cell?.value != null ? ` (${cell.value})` : ''}`}
                        className={`inline-block w-5 h-5 rounded ${levelClass(cell?.level)}`}
                        aria-label={`${METRIC_LABELS[metric]} ${s.week_start}: ${cell?.level || 'no data'}`}
                      />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-400">
        {Object.entries(LEVEL_COLOR).map(([level, cls]) => (
          <span key={level} className="flex items-center gap-1.5">
            <span className={`inline-block w-3 h-3 rounded ${cls}`} />
            {level}
          </span>
        ))}
      </div>
    </section>
  )
}
