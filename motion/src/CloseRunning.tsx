import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, spring, useVideoConfig} from 'remotion';

/**
 * M1 — the hero piece. A close actually running.
 *
 * Every number below came out of one real close of batch A through the product
 * on 2026-08-27 (run A-b7bde0f0): 543 records read, 62 decisions, 191ms. Nothing
 * here is rounded up or invented, which is the same rule the page it sits on
 * argues for — a marketing asset that overstates the engine would be the defect
 * the product exists to refuse.
 *
 * It is deliberately unglamorous. Counters tick in tabular numerals and rows
 * land without easing flourishes, because this should read as a machine working
 * rather than as a hero animation.
 */

const INK_DEEP = '#0B1E45';
const INK = '#1E293B';
const N500 = '#94A3B8';
const N600 = '#64748B';
const N300 = '#E2E8F0';
const N200 = '#F1F5F9';
const PRIMARY = '#2F7BFF';
const SUCCESS = '#22C55E';
const SURFACE = '#FFFFFF';

const SANS = 'Inter, -apple-system, "Segoe UI", Roboto, sans-serif';
const MONO = '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace';

/** The six real boundaries of the pipeline, and the fact each one produced. */
const STAGES = [
  {name: 'ingest', does: 'Read both sources and prove them', fact: '543 rows · 12 checks · verified', ms: '97 ms'},
  {name: 'block',  does: 'Narrow the pairs worth comparing', fact: '150/572 pairs · 73.8% reduction', ms: '2 ms'},
  {name: 'match',  does: "Run the loop's strategies in order", fact: '20 proposed · 7 raised', ms: '43 ms'},
  {name: 'verify', does: 'Re-derive every match from raw records', fact: '20/20 re-derived', ms: '13 ms'},
  {name: 'post',   does: 'Write the journal and assert the balance', fact: '23 entries · balanced', ms: '7 ms'},
  {name: 'record', does: 'Derive the decision log and seal it', fact: '62 events · chain sealed', ms: '29 ms'},
];

const METRICS = [
  {label: 'Auto-matched', value: '20', unit: '/ 23', foot: 'by tier T0=17 T1=2 T4=1'},
  {label: 'Proof tiers', value: 'P0=19', unit: 'P3=1', foot: '1 resting on a declared gap'},
  {label: 'Every input disposed', value: 'Yes', unit: '', foot: 'matched, excepted or out of scope'},
  {label: 'Books', value: 'Balanced', unit: '', foot: 'balance assertion held'},
];

const START = 24;      // frames before the first stage begins
const PER = 56;        // frames per stage
const CARD_AT = START + STAGES.length * PER + 10;

const Tick: React.FC<{on: boolean; p: number}> = ({on, p}) => (
  <div
    style={{
      width: 26, height: 26, borderRadius: 13, flexShrink: 0,
      border: `2px solid ${on ? SUCCESS : N300}`,
      background: on ? SUCCESS : 'transparent',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      transition: 'none',
    }}
  >
    {on ? (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
        <path d="M5 12.5l4.5 4.5L19 7" stroke="#fff" strokeWidth="3.4"
          strokeLinecap="round" strokeLinejoin="round"
          strokeDasharray="26" strokeDashoffset={26 - 26 * p} />
      </svg>
    ) : null}
  </div>
);

export const CloseRunning: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill
      style={{
        backgroundColor: '#FCFDFF',
        backgroundImage:
          'radial-gradient(52rem 34rem at 6% 0%, rgba(123,167,255,.17), transparent 62%),' +
          'radial-gradient(46rem 30rem at 98% 6%, rgba(47,123,255,.11), transparent 58%)',
        fontFamily: SANS,
        padding: '56px 72px',
      }}
    >
      {/* header — what is being closed */}
      <div style={{display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 34}}>
        <span style={{fontSize: 40, fontWeight: 600, color: INK_DEEP, letterSpacing: '-.03em'}}>
          Closing A
        </span>
        <span style={{fontFamily: MONO, fontSize: 17, color: N600}}>
          settlement_3way · policy settlement-in@v1
        </span>
        <span
          style={{
            marginLeft: 'auto', fontFamily: MONO, fontSize: 15, color: N500,
            opacity: interpolate(frame, [CARD_AT - 30, CARD_AT], [0, 1], {extrapolateRight: 'clamp', extrapolateLeft: 'clamp'}),
          }}
        >
          543 records · 62 decisions · 191 ms
        </span>
      </div>

      {/* the six stages */}
      <div style={{display: 'flex', flexDirection: 'column', gap: 4}}>
        {STAGES.map((s, i) => {
          const at = START + i * PER;
          const done = frame >= at + 22;
          const p = interpolate(frame, [at + 10, at + 26], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          const rowIn = spring({frame: frame - at, fps, config: {damping: 200}});
          const factIn = interpolate(frame, [at + 20, at + 34], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          const started = frame >= at;

          return (
            <div
              key={s.name}
              style={{
                display: 'flex', alignItems: 'center', gap: 20,
                padding: '15px 22px', borderRadius: 12,
                background: started ? SURFACE : 'transparent',
                border: `1px solid ${started ? N200 : 'transparent'}`,
                opacity: started ? 1 : 0.32,
                transform: `translateX(${(1 - rowIn) * -10}px)`,
              }}
            >
              <Tick on={done} p={p} />
              <div style={{width: 150}}>
                <div style={{fontSize: 24, fontWeight: 600, color: started ? INK_DEEP : N500, letterSpacing: '-.02em'}}>
                  {s.name}
                </div>
              </div>
              <div style={{flex: 1, fontSize: 18, color: N600}}>{s.does}</div>
              <div
                style={{
                  fontFamily: MONO, fontSize: 18, fontWeight: 500, color: PRIMARY,
                  fontVariantNumeric: 'tabular-nums', opacity: factIn, minWidth: 330, textAlign: 'right',
                }}
              >
                {s.fact}
              </div>
              <div
                style={{
                  fontFamily: MONO, fontSize: 15, color: N500, width: 70, textAlign: 'right',
                  fontVariantNumeric: 'tabular-nums', opacity: factIn,
                }}
              >
                {s.ms}
              </div>
            </div>
          );
        })}
      </div>

      {/* the scorecard, once the record is sealed */}
      <div
        style={{
          display: 'flex', gap: 16, marginTop: 30,
          opacity: interpolate(frame, [CARD_AT, CARD_AT + 18], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
        }}
      >
        {METRICS.map((m, i) => {
          const rise = spring({frame: frame - CARD_AT - i * 5, fps, config: {damping: 200}});
          return (
            <div
              key={m.label}
              style={{
                flex: 1, background: SURFACE, border: `1px solid ${N300}`, borderRadius: 16,
                padding: '20px 22px', transform: `translateY(${(1 - rise) * 14}px)`,
                boxShadow: '0 2px 6px rgba(30,41,59,.05)',
              }}
            >
              <div style={{fontSize: 16, color: N600, marginBottom: 8}}>{m.label}</div>
              <div style={{display: 'flex', alignItems: 'baseline', gap: 8}}>
                <span style={{fontSize: 36, fontWeight: 700, color: INK_DEEP, letterSpacing: '-.03em', fontVariantNumeric: 'tabular-nums'}}>
                  {m.value}
                </span>
                {m.unit ? (
                  <span style={{fontSize: 26, fontWeight: 600, color: m.label === 'Proof tiers' ? INK_DEEP : N500, fontVariantNumeric: 'tabular-nums'}}>
                    {m.unit}
                  </span>
                ) : null}
              </div>
              <div style={{fontFamily: MONO, fontSize: 13, color: N500, marginTop: 10, lineHeight: 1.45}}>
                {m.foot}
              </div>
            </div>
          );
        })}
      </div>

      {/* the line that is the whole point */}
      <div
        style={{
          marginTop: 26, textAlign: 'center', fontSize: 19, color: INK,
          opacity: interpolate(frame, [CARD_AT + 26, CARD_AT + 44], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
        }}
      >
        <strong style={{color: INK_DEEP, fontWeight: 600}}>No model ran.</strong>
        {' '}Every match above is arithmetic over the raw rows, and any of them can be
        re-derived by somebody who has never heard of us.
      </div>
    </AbsoluteFill>
  );
};
