import { useState } from "react";

import { useCopy } from "../../../app/copy";
import type { EquityPoint } from "../api";

function buildPolyline(points: EquityPoint[], width: number, height: number) {
  if (points.length === 0) {
    return "";
  }

  const values = points.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  return points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((point.equity - min) / range) * height;
      return `${x},${y}`;
    })
    .join(" ");
}

export function EquityCurveCard({ points }: { points: EquityPoint[] }) {
  const copy = useCopy();
  const [range, setRange] = useState<"1m" | "3m" | "1y" | "all">("all");

  if (points.length === 0) {
    return (
      <div className="app-panel rounded-2xl p-4 sm:p-5">
        <div className="app-kicker text-xs uppercase tracking-[0.18em]">
          {copy.overview.equityCurve.title}
        </div>
        <div className="app-panel-strong mt-4 rounded-2xl p-4 sm:p-5">
          <div className="text-base font-semibold">{copy.overview.equityCurve.emptyTitle}</div>
          <div className="app-muted mt-2 text-sm leading-6">
            {copy.overview.equityCurve.emptyDetail}
          </div>
          <div className="app-kicker mt-3 text-[11px] uppercase tracking-[0.16em]">
            {copy.overview.equityCurve.emptyHint}
          </div>
        </div>
      </div>
    );
  }

  const latestTimestamp = new Date(points[points.length - 1]?.timestamp ?? Date.now()).getTime();
  const daysByRange = { "1m": 31, "3m": 93, "1y": 366, all: Number.POSITIVE_INFINITY };
  const filteredPoints = points.filter((point) => {
    if (range === "all") {
      return true;
    }
    const ageInDays = (latestTimestamp - new Date(point.timestamp).getTime()) / 86_400_000;
    return ageInDays <= daysByRange[range];
  });
  const displayedPoints = filteredPoints.length >= 2 ? filteredPoints : points;
  const polyline = buildPolyline(displayedPoints, 640, 220);
  const labels = copy.overview.equityCurve;
  const startValue = displayedPoints[0]?.equity ?? 0;
  const endValue = displayedPoints[displayedPoints.length - 1]?.equity ?? 0;

  return (
    <div className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="app-kicker text-xs uppercase tracking-[0.18em]">
          {labels.title}
        </div>
        <div className="flex flex-wrap gap-2">
          {([
            ["1m", labels.oneMonth],
            ["3m", labels.threeMonths],
            ["1y", labels.oneYear],
            ["all", labels.all],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setRange(value)}
              className={`rounded-xl px-3 py-2 text-sm transition ${
                range === value ? "app-button-primary" : "app-button-secondary"
              }`}
              aria-label={`${labels.range}: ${label}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <svg
        viewBox="0 0 640 220"
        className="h-44 w-full text-[var(--app-chart-line)] sm:h-52 lg:h-56"
      >
        {[20, 75, 130, 185].map((y) => (
          <line
            key={y}
            x1="0"
            y1={y}
            x2="640"
            y2={y}
            className="app-chart-grid-line"
            strokeWidth="1"
            strokeDasharray="4 6"
          />
        ))}
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          points={polyline}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <text x="0" y="212" className="app-chart-axis-label" fontSize="12">
          {new Date(displayedPoints[0]?.timestamp ?? Date.now()).toLocaleDateString()}
        </text>
        <text x="640" y="212" textAnchor="end" className="app-chart-axis-label" fontSize="12">
          {new Date(
            displayedPoints[displayedPoints.length - 1]?.timestamp ?? Date.now(),
          ).toLocaleDateString()}
        </text>
        <text x="0" y="16" className="app-chart-axis-label" fontSize="12">
          {startValue.toFixed(2)}
        </text>
        <text x="640" y="16" textAnchor="end" className="app-chart-axis-label" fontSize="12">
          {endValue.toFixed(2)}
        </text>
      </svg>
    </div>
  );
}
