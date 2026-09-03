import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {ACCENT, FAINT, INK, INK_DEEP, LINE, MONO, MUTED, SANS, WARN, ground} from './theme';

/**
 * Shot 2 — the match is not the problem.
 *
 * The 97% bar is the setup. The punchline is the 3% falling off it and becoming
 * a stack of grey rows with NO labels: their blankness is the argument, so
 * resist the urge to write anything in them. A viewer who reads "E14 · ₹89,406"
 * on those rows has been shown the solution twenty seconds early.
 *
 * 90–99% and the 47-minute figure are from docs/00-RESEARCH-DOSSIER.md.
 */

const QUEUE_ROWS = 9;

export const SolvedAndNotSolved: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // 0.4s  bar fills
  // 2.6s  "already solved" lands, bar dims
  // 3.4s  the tail detaches and falls
  // 5.2s  it becomes a queue
  // 6.8s  the stopwatch
  // 8.6s  the queue starts growing; the rule ticket greys out
  const fill = interpolate(frame, [fps * 0.4, fps * 2.4], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const solved = interpolate(frame, [fps * 2.6, fps * 3.2], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const fall = interpolate(frame, [fps * 3.4, fps * 4.6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const queue = interpolate(frame, [fps * 5.2, fps * 6.4], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const watch = interpolate(frame, [fps * 6.8, fps * 7.6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const decay = interpolate(frame, [fps * 8.6, fps * 11.5], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{...ground, fontFamily: SANS, padding: 100}}>
      {/* the solved part */}
      <div style={{opacity: 1 - solved * 0.55}}>
        <div
          style={{
            fontFamily: MONO,
            fontSize: 14,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: FAINT,
            marginBottom: 18,
          }}
        >
          Auto-match, industry
        </div>
        <div
          style={{
            height: 78,
            borderRadius: 12,
            background: 'rgba(226,232,240,.55)',
            overflow: 'hidden',
            position: 'relative',
            border: `1px solid ${LINE}`,
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: 0,
              width: `${fill * 97}%`,
              background: `linear-gradient(90deg, ${ACCENT}, #5E9BFF)`,
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: 28,
              top: 0,
              bottom: 0,
              display: 'flex',
              alignItems: 'center',
              fontFamily: MONO,
              fontSize: 34,
              fontWeight: 700,
              color: '#fff',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {Math.round(fill * 97)}%
          </div>
        </div>
        <div
          style={{
            marginTop: 16,
            fontSize: 30,
            fontWeight: 600,
            color: INK_DEEP,
            opacity: solved,
            letterSpacing: '-0.02em',
          }}
        >
          Already solved.
        </div>
      </div>

      {/* the part nobody solved */}
      <div
        style={{
          marginTop: 46,
          transform: `translateY(${interpolate(fall, [0, 1], [-30, 0])}px)`,
          opacity: fall,
        }}
      >
        <div style={{display: 'flex', gap: 46, alignItems: 'flex-start'}}>
          <div style={{flex: '0 0 auto'}}>
            <div
              style={{
                fontFamily: MONO,
                fontSize: 14,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
                color: FAINT,
                marginBottom: 14,
              }}
            >
              The rest
            </div>
            {/* deliberately blank rows — the absence of a reason IS the point */}
            {Array.from({length: QUEUE_ROWS}).map((_, i) => {
              const born = i < 5 ? queue : decay * (i - 4) * 0.9;
              return (
                <div
                  key={i}
                  style={{
                    width: 430,
                    height: 30,
                    marginBottom: 7,
                    borderRadius: 6,
                    background: 'rgba(148,163,184,.28)',
                    border: '1px solid rgba(148,163,184,.34)',
                    opacity: Math.min(1, Math.max(0, born)),
                    transform: `translateX(${interpolate(
                      Math.min(1, Math.max(0, born)),
                      [0, 1],
                      [-24, 0],
                    )}px)`,
                  }}
                />
              );
            })}
          </div>

          <div style={{flex: 1, paddingTop: 44}}>
            {/* the stopwatch */}
            <div style={{opacity: watch, marginBottom: 40}}>
              <div
                style={{
                  fontFamily: MONO,
                  fontSize: 46,
                  fontWeight: 700,
                  color: INK_DEEP,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                47 min <span style={{color: FAINT}}>→</span>{' '}
                <span style={{color: ACCENT}}>exception handling only</span>
              </div>
              <div style={{fontSize: 22, color: MUTED, marginTop: 10, maxWidth: 560}}>
                The matched records were never the cost.
              </div>
            </div>

            {/* the treadmill */}
            <div
              style={{
                opacity: decay,
                display: 'flex',
                alignItems: 'center',
                gap: 18,
                padding: '18px 24px',
                borderRadius: 10,
                border: `1px dashed ${WARN}`,
                background: 'rgba(245,158,11,.07)',
                maxWidth: 560,
              }}
            >
              <div
                style={{
                  fontFamily: MONO,
                  fontSize: 15,
                  letterSpacing: '0.1em',
                  color: '#B45309',
                  textTransform: 'uppercase',
                }}
              >
                new rule
              </div>
              <div style={{flex: 1, height: 1, background: 'rgba(180,83,9,.3)'}} />
              <div style={{fontSize: 20, color: '#B45309'}}>engineering backlog</div>
            </div>
            <div
              style={{
                opacity: decay,
                fontSize: 20,
                color: MUTED,
                marginTop: 14,
                maxWidth: 560,
                lineHeight: 1.5,
              }}
            >
              The person who understands the exception is never the person who can fix it.
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
