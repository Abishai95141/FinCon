import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {MONO} from './theme';

/**
 * A transparent timecode strip, overlaid on the picture cut so a voiceover can
 * be recorded against it.
 *
 * This exists because the ffmpeg on this machine is built without libfreetype,
 * so `drawtext` is not merely missing a font — the filter is absent entirely
 * and no font path fixes it. Rather than make everyone install a different
 * ffmpeg, the clock is rendered here and composited with `overlay`, which needs
 * no text support at all.
 *
 * It reads better than drawtext anyway: the shot number and title are on screen,
 * so a note says "shot 6 runs four seconds long" rather than "the bit with the
 * model".
 *
 * **A 1920×72 opaque strip, not a transparent full-frame overlay.** The first
 * version rendered 1080p with an alpha channel, which forces PNG frames — and
 * 16,474 of those for a four-and-a-half-minute film took longer than every
 * other step in the pipeline put together, to composite a bar occupying six
 * percent of the picture. An opaque strip needs no alpha, so it encodes from
 * JPEG frames at a ninth of the pixels, and `overlay` drops it at the bottom
 * edge where the design already put solid boxes.
 */

export type Shot = {n: number; title: string; from: number; to: number};

export const Timecode: React.FC<{shots: Shot[]}> = ({shots}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;

  const mm = Math.floor(t / 60);
  const ss = Math.floor(t % 60);
  const ff = Math.floor((t % 1) * fps);
  const clock = `${mm}:${String(ss).padStart(2, '0')}.${String(ff).padStart(2, '0')}`;

  const shot = shots.find((s) => t >= s.from && t < s.to);
  // Time left in this shot — the number that actually matters when you are
  // reading a line against picture.
  const left = shot ? Math.max(0, shot.to - t) : 0;

  return (
    <AbsoluteFill
      style={{
        background: '#070C16',
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 30px',
        fontFamily: MONO,
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      {/* which shot, and how much of it is left */}
      <div style={{fontSize: 30, color: '#fff', display: 'flex', gap: 16}}>
        {shot ? (
          <>
            <span style={{color: '#6BA4FF', fontWeight: 700}}>SHOT {shot.n}</span>
            <span style={{opacity: 0.4}}>·</span>
            <span style={{opacity: 0.9}}>{shot.title}</span>
            <span style={{opacity: 0.4}}>·</span>
            {/* the number that matters when reading a line against picture */}
            <span style={{color: left < 3 ? '#FBBF24' : '#7CFFB2', fontWeight: 700}}>
              {left.toFixed(1)}s left
            </span>
          </>
        ) : null}
      </div>

      <div style={{fontSize: 34, fontWeight: 700, color: '#fff'}}>{clock}</div>
    </AbsoluteFill>
  );
};
