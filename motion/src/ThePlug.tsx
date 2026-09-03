import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {ACCENT, FAINT, INK, INK_DEEP, LINE, MONO, PLUG_RED, SANS, ground} from './theme';

/**
 * Shot 1 — the cold open. One bank line is forty transactions.
 *
 * The beat that carries the whole problem is the chargeback: it has to visibly
 * arrive AFTER the period boundary has already swept past. Everything else in
 * the film is easier to explain once a viewer has watched money land late.
 *
 * Every figure is real. ₹51,990.42 is the credit from docs/10-THE-USER-FLOW.md;
 * the residue is what a payout-level match leaves when the fee and the late
 * chargeback are not decomposed. Nothing here is rounded to look tidier.
 */

const CREDIT = 51990.42;

type Row = {label: string; amount: number; late?: boolean};

// Forty charges collapsed to a readable eight — the count is stated in the
// label rather than drawn forty times, because forty 8px rows read as texture
// and a viewer counts nothing.
const ROWS: Row[] = [
  {label: '40 charges', amount: 54312.9},
  {label: 'gateway fee', amount: -1509.88},
  {label: 'refund · ord_1182', amount: -412.4},
  {label: 'refund · ord_1204', amount: -287.6},
  {label: 'chargeback · ch_00931', amount: -4812.6, late: true},
];

const rupees = (n: number) =>
  `${n < 0 ? '−' : ''}₹${Math.abs(n).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

export const ThePlug: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // 0.0s  credit alone
  // 1.2s  shatters into rows
  // 4.0s  period line sweeps
  // 4.8s  chargeback arrives, late and outside
  // 6.4s  rows collapse back
  // 7.4s  residue types itself
  // 8.6s  PLUG stamps
  const shatter = interpolate(frame, [fps * 1.2, fps * 2.4], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const sweep = interpolate(frame, [fps * 4.0, fps * 4.7], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const late = interpolate(frame, [fps * 4.8, fps * 5.6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const collapse = interpolate(frame, [fps * 6.4, fps * 7.2], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const residue = interpolate(frame, [fps * 7.4, fps * 8.2], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const stamp = interpolate(frame, [fps * 8.6, fps * 9.0], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{...ground, fontFamily: SANS, padding: 96}}>
      {/* the bank credit — the thing everybody starts from */}
      <div
        style={{
          transform: `translateY(${interpolate(shatter, [0, 1], [220, 0])}px)`,
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontFamily: MONO,
            fontSize: 13,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: FAINT,
            marginBottom: 14,
          }}
        >
          Bank statement · one credit
        </div>
        <div
          style={{
            fontFamily: MONO,
            fontSize: 76,
            fontWeight: 700,
            color: INK_DEEP,
            fontVariantNumeric: 'tabular-nums',
            letterSpacing: '-0.03em',
          }}
        >
          {rupees(CREDIT)}
        </div>
      </div>

      {/* what it is actually made of */}
      <div style={{marginTop: 54, position: 'relative'}}>
        {ROWS.map((row, i) => {
          const appear = interpolate(
            shatter,
            [i * 0.12, i * 0.12 + 0.42],
            [0, 1],
            {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
          );
          const visible = row.late ? late : appear;
          const gone = row.late ? 0 : collapse;
          return (
            <div
              key={row.label}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                padding: '13px 26px',
                marginBottom: 6,
                borderRadius: 10,
                background: row.late ? 'rgba(245,158,11,.10)' : 'rgba(255,255,255,.72)',
                border: `1px solid ${row.late ? 'rgba(245,158,11,.42)' : LINE}`,
                opacity: visible * (1 - gone * 0.85),
                transform: `translateX(${
                  row.late
                    ? interpolate(late, [0, 1], [420, 0])
                    : interpolate(appear, [0, 1], [-60, 0])
                }px) translateY(${interpolate(gone, [0, 1], [0, -46])}px)`,
              }}
            >
              <span style={{fontSize: 26, color: row.late ? '#B45309' : INK}}>
                {row.label}
                {row.late ? (
                  <span
                    style={{
                      fontFamily: MONO,
                      fontSize: 15,
                      marginLeft: 14,
                      color: '#B45309',
                      opacity: late,
                    }}
                  >
                    arrived after the period closed
                  </span>
                ) : null}
              </span>
              <span
                style={{
                  fontFamily: MONO,
                  fontSize: 28,
                  fontWeight: 500,
                  color: row.late ? '#B45309' : INK_DEEP,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {rupees(row.amount)}
              </span>
            </div>
          );
        })}

        {/* the period boundary, sweeping through */}
        <div
          style={{
            position: 'absolute',
            left: -40,
            right: -40,
            top: `${interpolate(sweep, [0, 1], [-8, 108])}%`,
            height: 2,
            background: ACCENT,
            opacity: sweep > 0 && sweep < 1 ? 0.9 : sweep >= 1 ? 0.28 : 0,
          }}
        >
          <span
            style={{
              position: 'absolute',
              right: 0,
              top: -30,
              fontFamily: MONO,
              fontSize: 15,
              color: ACCENT,
              letterSpacing: '0.1em',
            }}
          >
            PERIOD CLOSES
          </span>
        </div>
      </div>

      {/* what a payout-level match leaves behind */}
      <div
        style={{
          marginTop: 40,
          opacity: residue,
          transform: `translateY(${interpolate(residue, [0, 1], [24, 0])}px)`,
          position: 'relative',
        }}
      >
        <div
          style={{
            fontFamily: MONO,
            fontSize: 13,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: FAINT,
            marginBottom: 12,
          }}
        >
          Journal
        </div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontFamily: MONO,
            fontSize: 34,
            color: INK_DEEP,
            padding: '18px 26px',
            borderRadius: 10,
            background: '#fff',
            border: `1px solid ${LINE}`,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <span>Suspense : Unreconciled</span>
          <span>{rupees(4812.6)}</span>
        </div>

        <div
          style={{
            position: 'absolute',
            right: 40,
            top: 34,
            transform: `rotate(-9deg) scale(${interpolate(stamp, [0, 1], [1.9, 1])})`,
            opacity: stamp,
            border: `4px solid ${PLUG_RED}`,
            color: PLUG_RED,
            fontWeight: 700,
            fontSize: 44,
            letterSpacing: '0.16em',
            padding: '8px 26px',
            borderRadius: 8,
          }}
        >
          PLUG
        </div>
      </div>
    </AbsoluteFill>
  );
};
