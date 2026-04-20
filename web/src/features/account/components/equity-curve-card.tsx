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

  if (points.length === 0) {
    return (
      <div className="app-panel rounded-2xl p-5 text-sm app-muted">{copy.overview.equityCurve.empty}</div>
    );
  }

  const polyline = buildPolyline(points, 640, 220);

  return (
    <div className="app-panel rounded-2xl p-5">
      <div className="app-kicker mb-4 text-xs uppercase tracking-[0.18em]">
        {copy.overview.equityCurve.title}
      </div>
      <svg viewBox="0 0 640 220" className="h-56 w-full">
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          points={polyline}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}
