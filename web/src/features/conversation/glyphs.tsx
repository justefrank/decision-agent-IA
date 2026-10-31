/** Deux glyphes propres à cette fonctionnalité (copier, déplier) : évite de toucher à la liste partagée. */
export function CopyGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 9h10v11H9zM5 15V4h10" />
    </svg>
  );
}

export function ChevronGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg aria-hidden="true" focusable="false" className="cv-chevron" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}
