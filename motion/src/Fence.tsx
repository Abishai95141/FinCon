import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {ACCENT, FAINT, INK_DEEP, LINE, MONO, MUTED, OK, PLUG_RED, SANS, WARN, ground} from './theme';

/**
 * Shot 6 inset — the fence. Four seconds, picture-in-picture.
 *
 * Three model proposals slide at the ledger. Two are refused for reasons that
 * are real refusals in the code, not illustrations:
 *
 *   - a proposal may not overwrite `P0 ARITHMETIC` (recon/review.py)
 *   - a reply that is not a tool call is refused and recorded (triage/client.py)
 *
 * The third carries a name and lands as `P2 ATTESTED`. Three quarters of the
 * runtime is things being turned away, because the rhythm of refusal is the
 * point — a fence you only see one thing bounce off is a gate.
 */

type Attempt = {
  label: string;
  verdict: string;
  ok: boolean;
  at: number;
};

const ATTEMPTS: Attempt[] = [
  {label: 'model proposes E01', verdict: 'refused — may not overwrite P0 ARITHMETIC', ok: false, at: 0.3},
  {label: 'model replies in prose', verdict: 'refused — not a tool call', ok: false, at: 1.5},
  {label: 'meera accepts E08', verdict: 'P2 ATTESTED · meera@', ok: true, at: 2.7},
];

export const Fence: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill style={{...ground, fontFamily: SANS, padding: 64, justifyContent: 'center'}}>
      <div style={{display: 'flex', alignItems: 'stretch', gap: 34}}>
        {/* the attempts */}
        <div style={{flex: 1}}>
          {ATTEMPTS.map((a) => {
            const t = interpolate(frame, [fps * a.at, fps * (a.at + 0.55)], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
            const judged = interpolate(frame, [fps * (a.at + 0.6), fps * (a.at + 0.9)], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
            // refused ones recoil; the accepted one carries on through
            const push = a.ok
              ? interpolate(judged, [0, 1], [0, 120])
              : interpolate(judged, [0, 1], [0, -46]);
            return (
              <div
                key={a.label}
                style={{
                  marginBottom: 16,
                  padding: '16px 20px',
                  borderRadius: 10,
                  background: '#fff',
                  border: `1px solid ${judged > 0.5 ? (a.ok ? OK : PLUG_RED) : LINE}`,
                  opacity: t,
                  transform: `translateX(${interpolate(t, [0, 1], [-70, 0]) + push}px)`,
                }}
              >
                <div style={{fontSize: 21, color: INK_DEEP, fontWeight: 500}}>{a.label}</div>
                <div
                  style={{
                    fontFamily: MONO,
                    fontSize: 14,
                    marginTop: 7,
                    color: a.ok ? OK : PLUG_RED,
                    opacity: judged,
                  }}
                >
                  {a.verdict}
                </div>
              </div>
            );
          })}
        </div>

        {/* the fence itself */}
        <div
          style={{
            width: 4,
            borderRadius: 2,
            background: `repeating-linear-gradient(180deg, ${ACCENT} 0 14px, transparent 14px 26px)`,
            opacity: 0.75,
          }}
        />

        {/* the ledger */}
        <div style={{flex: '0 0 300px'}}>
          <div
            style={{
              fontFamily: MONO,
              fontSize: 12,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: FAINT,
              marginBottom: 12,
            }}
          >
            The ledger
          </div>
          <div
            style={{
              border: `1px solid ${LINE}`,
              borderRadius: 10,
              background: '#fff',
              padding: '20px 22px',
              fontFamily: MONO,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            <div style={{fontSize: 15, color: MUTED, marginBottom: 10}}>entries</div>
            <div style={{fontSize: 48, fontWeight: 700, color: INK_DEEP}}>
              {frame > fps * 3.6 ? 24 : 23}
            </div>
            <div style={{fontSize: 13, color: WARN, marginTop: 12, opacity: frame > fps * 3.6 ? 1 : 0}}>
              +1 · P2 ATTESTED
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
