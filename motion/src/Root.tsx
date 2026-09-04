import React from 'react';
import {Composition} from 'remotion';
import {Card} from './Card';
import {CloseRunning} from './CloseRunning';
import {Fence} from './Fence';
import {SolvedAndNotSolved} from './SolvedAndNotSolved';
import {ThePlug} from './ThePlug';
import {Timecode} from './Timecode';
import {Verify, seconds as verifySeconds} from './Verify';
import session from '../../demo/verify-session.json';

/**
 * Two audiences, one project.
 *
 * `CloseRunning` is the landing page hero — 1708×812 to sit in the page's video
 * slot. Everything else is the demo film at true 1080p, because those get cut
 * against product footage and a mismatched frame size means a rescale in the
 * edit for no reason.
 *
 * `CloseRunning` is deliberately NOT reused in the film: shot 4 shows the real
 * close running, and an animation of a thing standing next to the thing is a
 * worse version of both.
 */

const FILM = {fps: 60, width: 1920, height: 1080} as const;

export const Root: React.FC = () => (
  <>
    {/* landing page */}
    <Composition
      id="CloseRunning"
      component={CloseRunning}
      durationInFrames={18 * 30}
      fps={30}
      width={1708}
      height={812}
    />

    {/* demo film — durations are the shot list in docs/15-DEMO.md */}
    <Composition id="ThePlug" component={ThePlug} durationInFrames={18 * 60} {...FILM} />
    <Composition
      id="SolvedAndNotSolved"
      component={SolvedAndNotSolved}
      durationInFrames={32 * 60}
      {...FILM}
    />
    <Composition id="Fence" component={Fence} durationInFrames={10 * 60} {...FILM} />
    <Composition id="Card" component={Card} durationInFrames={14 * 60} {...FILM} />

    {/* Shot 9. Duration follows the transcript: two commands typed at 42
        characters a second, two responses, and a beat on each. */}
    <Composition
      id="Verify"
      component={Verify}
      durationInFrames={Math.round(verifySeconds(session) * 60)}
      {...FILM}
      defaultProps={{session}}
    />

    {/* The overlay the picture cut is timecoded with. Duration and shot list
        arrive as props from tools/demo_assemble.py, which is the only thing
        that knows where the cuts actually landed. */}
    <Composition
      id="Timecode"
      component={Timecode}
      durationInFrames={300 * 60}
      fps={60}
      width={1920}
      height={72}
      defaultProps={{shots: [] as {n: number; title: string; from: number; to: number}[]}}
    />
  </>
);
