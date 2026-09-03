import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {ACCENT, INK_DEEP, MONO, MUTED, SANS, ground} from './theme';

/**
 * Shot 11 — the end card.
 *
 * Holds four seconds on a still frame at the end, deliberately, so it can be
 * paused and screenshotted. A card that dissolves the instant the last word
 * lands is a card nobody can use.
 */

export const Card: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const mark = interpolate(frame, [0, fps * 0.7], [0, 1], {extrapolateRight: 'clamp'});
  const word = interpolate(frame, [fps * 0.5, fps * 1.1], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const line = interpolate(frame, [fps * 1.2, fps * 1.9], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const urls = interpolate(frame, [fps * 2.1, fps * 2.8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{...ground, fontFamily: SANS, alignItems: 'center', justifyContent: 'center'}}
    >
      <div style={{display: 'flex', alignItems: 'center', gap: 22, marginBottom: 34}}>
        <svg
          width={96}
          height={110}
          viewBox="2 3 38 44"
          fill="none"
          style={{
            opacity: mark,
            transform: `translateY(${interpolate(mark, [0, 1], [16, 0])}px)`,
          }}
        >
          <path
            d="M14 3 H35 C39.5 3 41.5 7.6 38.6 11L30.5 20.6 L14.5 25.2 L7.4 44.4 C6.1 48 1.6 47.2 2 43.4 L6.4 10.4 C6.9 6.2 9.9 3 14 3 Z"
            fill={ACCENT}
          />
          <path
            d="M8.4 30.2 L26.6 24.2 C29.8 23.2 32 26.6 30 29.2 L20.6 40.6 C18 43.8 13 42.6 12.4 38.6 Z"
            fill="#93B4FA"
          />
          <path
            d="M14.5 25.2 L30.5 20.6 L26.6 24.2 L8.4 30.2 Z"
            fill="#12327E"
            opacity={0.55}
          />
        </svg>
        <div
          style={{
            fontSize: 92,
            fontWeight: 600,
            letterSpacing: '-0.04em',
            color: INK_DEEP,
            opacity: word,
            transform: `translateX(${interpolate(word, [0, 1], [-18, 0])}px)`,
          }}
        >
          Fin<span style={{color: ACCENT}}>Con</span>
        </div>
      </div>

      <div
        style={{
          fontSize: 34,
          color: INK_DEEP,
          fontWeight: 300,
          textAlign: 'center',
          maxWidth: 1080,
          lineHeight: 1.35,
          opacity: line,
        }}
      >
        Close the books with a <span style={{fontWeight: 600}}>proof</span>, not a plug.
      </div>

      <div
        style={{
          marginTop: 52,
          display: 'flex',
          gap: 46,
          fontFamily: MONO,
          fontSize: 24,
          color: MUTED,
          opacity: urls,
        }}
      >
        <span style={{color: ACCENT}}>fincon.astutecomputer.com</span>
        <span>github.com/Abishai95141/FinCon</span>
      </div>
    </AbsoluteFill>
  );
};
