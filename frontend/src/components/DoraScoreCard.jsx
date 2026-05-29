import React from 'react'

const LEVEL_COLORS = {
  Elite: 'bg-green-500',
  High: 'bg-blue-500',
  Medium: 'bg-yellow-500',
  Low: 'bg-red-500',
  Unknown: 'bg-gray-500',
}

export function DoraScoreCard({ title, value, unit, level, description }) {
  return (
    <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium text-gray-400">{title}</h3>
        <span className={`px-2 py-0.5 rounded text-xs font-bold text-white ${LEVEL_COLORS[level] || LEVEL_COLORS.Unknown}`}>
          {level}
        </span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-3xl font-bold text-white">
          {value !== null && value !== undefined ? value : '—'}
        </span>
        {unit && <span className="text-sm text-gray-400">{unit}</span>}
      </div>
      {description && (
        <p className="mt-2 text-xs text-gray-500">{description}</p>
      )}
    </div>
  )
}
