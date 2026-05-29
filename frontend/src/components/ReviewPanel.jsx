import React from 'react'

export function ReviewPanel({ data }) {
  if (!data) {
    return null
  }

  return (
    <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
      <h3 className="text-lg font-semibold text-white mb-4">PR Review Activity</h3>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-4">
        <Stat label="Total Reviews" value={data.total_reviews} />
        <Stat label="Human Reviews" value={data.human_reviews} />
        <Stat label="Bot Reviews" value={data.bot_reviews} />
        <Stat label="Approvals" value={data.approvals} color="text-green-400" />
        <Stat label="Changes Requested" value={data.changes_requested} color="text-red-400" />
      </div>
      {data.reviewers?.length > 0 && (
        <div className="mt-4 pt-4 border-t border-gray-700">
          <span className="text-xs text-gray-400">Active Reviewers: </span>
          <span className="text-xs text-gray-300">
            {data.reviewers.join(', ')}
          </span>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, color = 'text-white' }) {
  return (
    <div className="text-center">
      <div className={`text-2xl font-bold ${color}`}>{value ?? '—'}</div>
      <div className="text-xs text-gray-400 mt-1">{label}</div>
    </div>
  )
}
