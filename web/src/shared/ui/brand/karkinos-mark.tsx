import { useId, type SVGProps } from 'react';

export function KarkinosMark(props: SVGProps<SVGSVGElement>) {
  const maskId = useId();

  return (
    <svg
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
      focusable="false"
      data-testid="karkinos-mark"
      {...props}
    >
      {/* Node cutout mask to ensure hollow celestial nodes without line bleed */}
      <mask id={maskId}>
        <rect width="28" height="28" fill="white" />
        <circle cx="17.57" cy="2.48" r="0.95" fill="black" />
        <circle cx="14.26" cy="12.25" r="1.1" fill="black" />
        <circle cx="8.90" cy="13.10" r="1.1" fill="black" />
        <circle cx="14.26" cy="15.23" r="1.45" fill="black" />
        <circle cx="14.26" cy="18.20" r="1.1" fill="black" />
        <circle cx="11.28" cy="23.98" r="1.25" fill="black" />
        <circle cx="19.10" cy="21.94" r="1.1" fill="black" />
      </mask>

      {/* Transit lines masked out at node perimeters (Cancer Constellation x Scalpel) */}
      <g
        mask={`url(#${maskId})`}
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      >
        {/* Upper-right tentacle / scalpel razor edge (γ -> ι) */}
        <line x1="14.26" y1="12.25" x2="17.57" y2="2.48" strokeWidth="1.4" />
        {/* Scalpel bevel facet reflection line */}
        <line
          x1="14.26"
          y1="12.25"
          x2="15.75"
          y2="7.90"
          strokeWidth="0.8"
          opacity="0.85"
        />
        {/* Left wing transit (ζ -> γ) */}
        <line x1="8.90" y1="13.10" x2="14.26" y2="12.25" />
        {/* Central precision instrument datum / vertical spine (γ -> δ) */}
        <line x1="14.26" y1="12.25" x2="14.26" y2="18.20" />
        {/* Lower left leg / grip balance (δ -> β) */}
        <line x1="14.26" y1="18.20" x2="11.28" y2="23.98" strokeWidth="1.3" />
        {/* Lower right leg / grip balance (δ -> α) */}
        <line x1="14.26" y1="18.20" x2="19.10" y2="21.94" />
      </g>

      {/* Hollow celestial star nodes & central M44 Praesepe aperture */}
      <g stroke="currentColor" strokeWidth="1.1" fill="none">
        {/* ι Decapoda (Scalpel razor tip) */}
        <circle cx="17.57" cy="2.48" r="0.95" />
        {/* γ Asellus Borealis (Upper nexus) */}
        <circle cx="14.26" cy="12.25" r="1.1" />
        {/* ζ Tegmine (Left star) */}
        <circle cx="8.90" cy="13.10" r="1.1" />
        {/* M44 Praesepe (Locking slot / cluster ring) */}
        <circle cx="14.26" cy="15.23" r="1.45" strokeWidth="1.1" />
        {/* δ Asellus Australis (Lower nexus) */}
        <circle cx="14.26" cy="18.20" r="1.1" />
        {/* β Altarf (Primary luminary star) */}
        <circle cx="11.28" cy="23.98" r="1.25" strokeWidth="1.2" />
        {/* α Acubens (Right claw star) */}
        <circle cx="19.10" cy="21.94" r="1.1" />
      </g>

      {/* Central M44 core dot */}
      <circle cx="14.26" cy="15.23" r="0.45" fill="currentColor" />
    </svg>
  );
}
