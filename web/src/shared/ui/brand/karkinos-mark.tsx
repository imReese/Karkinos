import type { SVGProps } from 'react';

export function KarkinosMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
      focusable="false"
      data-testid="karkinos-mark"
      {...props}
    >
      {/* Precision vertical datum spine (truth & ledger) */}
      <rect x="5" y="4" width="3.5" height="20" rx="1.75" fill="currentColor" />
      {/* Upper caliper jaw (alpha vector) */}
      <path
        d="M11 12L17.5 5.5H22.5V10.5H20V8.5L14.5 14L11 12Z"
        fill="currentColor"
      />
      {/* Lower caliper jaw (risk boundary) */}
      <path
        d="M11 16L17.5 22.5H22.5V17.5H20V19.5L14.5 14L11 16Z"
        fill="currentColor"
        opacity="0.85"
      />
    </svg>
  );
}
