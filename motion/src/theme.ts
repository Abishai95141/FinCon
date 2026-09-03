/**
 * The product's own tokens, so the film and the application are visibly one
 * thing. Lifted from `src/recon/api/theme.py` — a second palette maintained
 * beside the first is the copy that rots.
 */

export const ACCENT = '#2F7BFF';
export const ACCENT_DEEP = '#1D5FD8';
export const ACCENT_WASH = '#E9F1FF';
export const INK_DEEP = '#0B1E45';
export const INK = '#1E293B';
export const MUTED = '#64748B';
export const FAINT = '#94A3B8';
export const LINE = '#E2E8F0';
export const OK = '#22C55E';
export const WARN = '#F59E0B';
export const PLUG_RED = '#DC2626';

export const SANS =
  'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif';
export const MONO =
  '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace';

/** The application's own page ground: three soft radial washes over near-white. */
export const ground: React.CSSProperties = {
  backgroundColor: '#FCFDFF',
  backgroundImage: [
    'radial-gradient(52rem 34rem at 6% 0%, rgba(123,167,255,.17), transparent 62%)',
    'radial-gradient(46rem 30rem at 98% 6%, rgba(47,123,255,.11), transparent 58%)',
    'radial-gradient(50rem 34rem at 24% 100%, rgba(163,201,255,.15), transparent 62%)',
  ].join(','),
};
