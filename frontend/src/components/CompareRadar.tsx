'use client';

import React from 'react';

interface RadarData {
  labels: string[];
  p1: Record<string, number>;
  p2: Record<string, number>;
}

interface CompareRadarProps {
  data: RadarData;
  p1Name: string;
  p2Name: string;
}

export const CompareRadar: React.FC<CompareRadarProps> = ({ data, p1Name, p2Name }) => {
  const { labels, p1, p2 } = data;
  const numAxes = labels.length;
  if (numAxes === 0) return null;

  const size = 360;
  const center = size / 2;
  const radius = (size / 2) - 48; // padding for labels

  // Compute vertex coordinate on radar
  const getCoordinates = (index: number, value: number) => {
    // Value 0 to 100
    const angle = (Math.PI * 2 / numAxes) * index - Math.PI / 2;
    const distance = (Math.max(0, Math.min(100, value)) / 100) * radius;
    const x = center + distance * Math.cos(angle);
    const y = center + distance * Math.sin(angle);
    return { x, y };
  };

  // Grid levels (20%, 40%, 60%, 80%, 100%)
  const levels = [20, 40, 60, 80, 100];

  const p1Points = labels.map((label, i) => {
    const val = p1[label] ?? 50;
    const { x, y } = getCoordinates(i, val);
    return `${x},${y}`;
  }).join(' ');

  const p2Points = labels.map((label, i) => {
    const val = p2[label] ?? 50;
    const { x, y } = getCoordinates(i, val);
    return `${x},${y}`;
  }).join(' ');

  return (
    <div className="flex flex-col items-center justify-center p-4 bg-slate-950/80 rounded-2xl border border-slate-800">
      <div className="w-full max-w-[380px] aspect-square relative">
        <svg viewBox={`0 0 ${size} ${size}`} className="w-full h-full overflow-visible">
          {/* Background Concentric Polygons */}
          {levels.map((level) => {
            const levelPoints = labels.map((_, i) => {
              const { x, y } = getCoordinates(i, level);
              return `${x},${y}`;
            }).join(' ');

            return (
              <polygon
                key={level}
                points={levelPoints}
                fill="none"
                stroke="#1e293b"
                strokeWidth={level === 100 ? '1.5' : '1'}
                strokeDasharray={level === 100 ? 'none' : '3 3'}
              />
            );
          })}

          {/* Radial axis lines */}
          {labels.map((label, i) => {
            const { x, y } = getCoordinates(i, 100);
            return (
              <line
                key={`line-${i}`}
                x1={center}
                y1={center}
                x2={x}
                y2={y}
                stroke="#334155"
                strokeWidth="1"
              />
            );
          })}

          {/* Player 1 Polygon (Orange) */}
          <polygon
            points={p1Points}
            fill="rgba(249, 115, 22, 0.35)"
            stroke="#f97316"
            strokeWidth="2.5"
            className="transition-all duration-300"
          />

          {/* Player 2 Polygon (Cyan) */}
          <polygon
            points={p2Points}
            fill="rgba(14, 165, 233, 0.35)"
            stroke="#0ea5e9"
            strokeWidth="2.5"
            className="transition-all duration-300"
          />

          {/* Player 1 Data Dots */}
          {labels.map((label, i) => {
            const val = p1[label] ?? 50;
            const { x, y } = getCoordinates(i, val);
            return (
              <circle
                key={`dot-p1-${i}`}
                cx={x}
                cy={y}
                r="4"
                fill="#f97316"
                stroke="#ffffff"
                strokeWidth="1.5"
              />
            );
          })}

          {/* Player 2 Data Dots */}
          {labels.map((label, i) => {
            const val = p2[label] ?? 50;
            const { x, y } = getCoordinates(i, val);
            return (
              <circle
                key={`dot-p2-${i}`}
                cx={x}
                cy={y}
                r="4"
                fill="#0ea5e9"
                stroke="#ffffff"
                strokeWidth="1.5"
              />
            );
          })}

          {/* Dimension Labels */}
          {labels.map((label, i) => {
            const angle = (Math.PI * 2 / numAxes) * i - Math.PI / 2;
            const labelDistance = radius + 22;
            const lx = center + labelDistance * Math.cos(angle);
            const ly = center + labelDistance * Math.sin(angle);

            const isTop = Math.abs(angle + Math.PI / 2) < 0.2;
            const isBottom = Math.abs(angle - Math.PI / 2) < 0.2;
            const isLeft = Math.cos(angle) < -0.2;
            const isRight = Math.cos(angle) > 0.2;

            let anchor: 'middle' | 'start' | 'end' = 'middle';
            if (isLeft) anchor = 'end';
            if (isRight) anchor = 'start';

            return (
              <text
                key={`lbl-${i}`}
                x={lx}
                y={ly + (isTop ? -4 : isBottom ? 10 : 3)}
                textAnchor={anchor}
                fill="#cbd5e1"
                fontSize="11"
                fontWeight="700"
                className="select-none tracking-tight font-sans drop-shadow-sm"
              >
                {label}
              </text>
            );
          })}
        </svg>
      </div>

      {/* Legend & Current Values */}
      <div className="flex items-center justify-center gap-6 mt-4 pt-3 border-t border-slate-800 w-full text-xs font-semibold">
        <div className="flex items-center gap-2">
          <span className="w-3.5 h-3.5 rounded-full bg-orange-500 shadow-sm shadow-orange-500/50" />
          <span className="text-orange-400 font-bold">{p1Name}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3.5 h-3.5 rounded-full bg-sky-500 shadow-sm shadow-sky-500/50" />
          <span className="text-sky-400 font-bold">{p2Name}</span>
        </div>
      </div>
    </div>
  );
};
