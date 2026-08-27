import React from 'react';
import {Composition} from 'remotion';
import {CloseRunning} from './CloseRunning';

export const Root: React.FC = () => (
  <Composition
    id="CloseRunning"
    component={CloseRunning}
    durationInFrames={18 * 30}
    fps={30}
    width={1708}
    height={812}
  />
);
