import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

/**
 * Shot 9 — check it without us.
 *
 * A terminal, typing two real curl commands and printing two real responses.
 * Both came out of `tools/demo_verify_capture.py`, which hits the deployed
 * endpoint and keeps exactly what came back; nothing on this screen was typed
 * by a person pretending to be a server.
 *
 * That matters more here than in any other shot. This one *is* the claim that
 * a stranger can re-derive our arithmetic without an account — a mocked
 * transcript would be a fabricated record of the one property the product is
 * sold on.
 *
 * Rendered rather than screen-recorded because the first plan had a human
 * capture a terminal, which is why this was the only shot still missing when
 * everything else was cut. A shot the pipeline cannot re-make is a shot that
 * goes stale and then goes absent.
 */

const BG = '#070C16';
const DIM = '#61708A';
const TEXT = '#C9D4E6';
const PROMPT = '#6BA4FF';
const OK = '#4ADE80';
const BAD = '#F87171';
const KEY = '#8FBBFF';
const MONO = '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace';

type Step = {typed: string; response: Record<string, unknown>};
type Session = {base: string; leg: string; bent_from: string; bent_to: string; steps: Step[]};

/** Characters a second. Fast enough not to bore, slow enough to read. */
const CPS = 42;

/** The shape of the shot, in seconds. Exported because `Root.tsx` needs the
 *  total and computing it twice is how the composition comes to be a different
 *  length from the thing inside it.
 *
 *  Sized from the narration, not from taste: the line is 52 words, and at the
 *  125 wpm the rest of the film reads at that is 25 seconds. The first render
 *  came in at 14.2s, which would have needed 220 wpm — the two long holds are
 *  where a viewer reads `proven: true` and then reads the refusal. */
export const BEATS = {
  start: 0.6,
  settle: 0.45,
  readOk: 6.0,
  beforeBent: 2.0,
  tail: 9.5,
};

export const seconds = (session: Session): number =>
  BEATS.start +
  session.steps[0].typed.length / CPS +
  BEATS.settle +
  BEATS.readOk +
  BEATS.beforeBent +
  session.steps[1].typed.length / CPS +
  BEATS.settle +
  BEATS.tail;

const line = (t: number, at: number) => (t >= at ? 1 : 0);

/** How much of a string has been typed by time `t`. */
function typed(text: string, t: number, from: number): string {
  if (t < from) return '';
  return text.slice(0, Math.floor((t - from) * CPS));
}

function Json({value, tone}: {value: Record<string, unknown>; tone?: string}) {
  const rows = Object.entries(value);
  return (
    <div style={{marginTop: 10}}>
      <span style={{color: DIM}}>{'{'}</span>
      {rows.map(([k, v]) => (
        <div key={k} style={{paddingLeft: 34, display: 'flex', gap: 12}}>
          <span style={{color: KEY}}>"{k}":</span>
          <span style={{color: tone ?? TEXT, flex: 1, whiteSpace: 'pre-wrap'}}>
            {Array.isArray(v)
              ? v.map((x) => String(x)).join('\n')
              : typeof v === 'boolean'
                ? String(v)
                : `"${String(v)}"`}
          </span>
        </div>
      ))}
      <span style={{color: DIM}}>{'}'}</span>
    </div>
  );
}

export const Verify: React.FC<{session: Session}> = ({session}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;

  const [one, two] = session.steps;

  // Laid out in sequence off the first command's length, so a longer URL moves
  // everything after it rather than overlapping.
  const t1 = BEATS.start;
  const r1 = t1 + one.typed.length / CPS + BEATS.settle;
  const note = r1 + BEATS.readOk;
  const t2 = note + BEATS.beforeBent;
  const r2 = t2 + two.typed.length / CPS + BEATS.settle;

  const opacity = interpolate(t, [0, 0.4], [0, 1], {extrapolateRight: 'clamp'});
  const cursor = Math.floor(t * 2) % 2 === 0 ? '▋' : ' ';

  return (
    <AbsoluteFill style={{background: BG, opacity, padding: '70px 90px', fontFamily: MONO}}>
      <div style={{fontSize: 25, lineHeight: 1.65, color: TEXT}}>
        {/* the honest case */}
        <div>
          <span style={{color: PROMPT}}>$ </span>
          {typed(one.typed, t, t1)}
          {t >= t1 && t < r1 ? cursor : ''}
        </div>
        {line(t, r1) ? <Json value={one.response} tone={OK} /> : null}

        {/* the same proof, one number changed */}
        {line(t, note) ? (
          <div style={{marginTop: 34, color: DIM}}>
            # change leg '{session.leg}' by one rupee — {session.bent_from} → {session.bent_to}
          </div>
        ) : null}

        {line(t, t2) ? (
          <div style={{marginTop: 8}}>
            <span style={{color: PROMPT}}>$ </span>
            {typed(two.typed, t, t2)}
            {t >= t2 && t < r2 ? cursor : ''}
          </div>
        ) : null}
        {line(t, r2) ? <Json value={two.response} tone={BAD} /> : null}
      </div>
    </AbsoluteFill>
  );
};
