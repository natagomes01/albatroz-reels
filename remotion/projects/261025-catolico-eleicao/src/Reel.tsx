import React from 'react';
import { AbsoluteFill, Sequence } from 'remotion';
import { BODY, BodyLayer, HOLD_FRAMES } from './Body';
import { Hook, HOOK_FRAMES, useAnton, usePalette } from './Hook';

// The whole Reel: the motion hook ("Você já pecou"), then the pipeline's body render (job
// 261025-catolico-eleicao, clip e220a01) with inserts, the Mt 22,37-39 card, tags, captions and the follow
// CTA over his last sentence. No retention strip and no ebook pass: this video has no free material.
export const REEL_FRAMES = HOOK_FRAMES + BODY.bodyFrames + HOLD_FRAMES;

export const Reel: React.FC = () => {
  useAnton();
  const C = usePalette();
  return (
    <AbsoluteFill style={{ backgroundColor: C.black }}>
      <Sequence durationInFrames={HOOK_FRAMES}>
        <Hook />
      </Sequence>
      <Sequence from={HOOK_FRAMES} durationInFrames={BODY.bodyFrames + HOLD_FRAMES}>
        <BodyLayer />
      </Sequence>
    </AbsoluteFill>
  );
};
