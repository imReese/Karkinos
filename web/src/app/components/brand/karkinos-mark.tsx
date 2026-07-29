import type { SVGProps } from 'react';

export function KarkinosMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 28 28"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      data-testid="karkinos-mark"
      {...props}
    >
      <path d="M8.25 5.25v17.5" strokeWidth="2.5" />
      <path d="M9 14h4.25L20 7.25" strokeWidth="2.25" />
      <path d="m13.25 14 6.75 6.75" strokeWidth="2.25" />
      <circle cx="20.4" cy="6.85" r="1.35" fill="currentColor" stroke="none" />
      <circle cx="20.4" cy="21.15" r="1.35" fill="currentColor" stroke="none" />
    </svg>
  );
}
