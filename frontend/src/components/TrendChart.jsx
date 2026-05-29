import React from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'

export function TrendChart({ data, lines, title, yAxisLabel }) {
  if (!data || data.length === 0) {
    return (
      <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
        <h3 className="text-sm font-medium text-gray-400 mb-4">{title}</h3>
        <p className="text-gray-500 text-center py-8">No data available</p>
      </div>
    )
  }

  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444']

  return (
    <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
      <h3 className="text-sm font-medium text-gray-400 mb-4">{title}</h3>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="week_start"
            stroke="#9ca3af"
            fontSize={11}
            tickFormatter={(val) => new Date(val).toLocaleDateString('en', { month: 'short', day: 'numeric' })}
          />
          <YAxis stroke="#9ca3af" fontSize={11} label={{ value: yAxisLabel, angle: -90, position: 'insideLeft', style: { fill: '#9ca3af' } }} />
          <Tooltip
            contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
            labelStyle={{ color: '#9ca3af' }}
          />
          <Legend />
          {lines.map((line, i) => (
            <Line
              key={line.key}
              type="monotone"
              dataKey={line.key}
              name={line.name}
              stroke={colors[i % colors.length]}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
