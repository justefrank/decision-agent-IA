/** Logo du produit (repris de la maquette) : la marque et le mot-symbole. */
export function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <rect width="48" height="48" rx="11" fill="#1DC8FE" />
      <ellipse cx="24" cy="27" rx="11" ry="13" fill="#0B2545" />
      <ellipse cx="24" cy="30" rx="6.5" ry="9" fill="#fff" />
      <circle cx="24" cy="15" r="7" fill="#0B2545" />
      <circle cx="21.3" cy="14" r="1.5" fill="#fff" />
      <circle cx="26.7" cy="14" r="1.5" fill="#fff" />
      <path d="M21.5 17l2.5 2.6 2.5-2.6z" fill="#FFC83D" />
      <path d="M17 40h5l-1 2h-5zM26 40h5l1 2h-5z" fill="#FFC83D" />
    </svg>
  );
}

export function Logo({ subtitle = true }: { subtitle?: boolean }) {
  return (
    <span className="logo">
      <LogoMark />
      <span className="logo-text">
        <b>wave</b>
        {subtitle ? <span>Agent décisionnel</span> : null}
      </span>
    </span>
  );
}
