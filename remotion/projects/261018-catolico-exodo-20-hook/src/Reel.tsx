import React from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import { Exodo20Hook, FONT, Halftone, HOOK_FRAMES, Inked, useAnton, usePalette, type Palette } from './Exodo20Hook';
import lettering from './lettering.json';

// The whole Reel: motion hook, then the pipeline's body render (job clip a931c03) with lettering, then the end card.
export const END_FRAMES = 105; // 3.5 s

export type Lettering = { from: number; to: number; text: string; color?: keyof Palette; y?: number };
export const LETTERING = lettering as { bodyFrames: number; items: Lettering[] };
export const REEL_FRAMES = HOOK_FRAMES + LETTERING.bodyFrames + END_FRAMES;

const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

const Tag: React.FC<{ item: Lettering }> = ({ item }) => {
  const C = usePalette();
  const frame = useCurrentFrame(); // local to the Sequence
  const len = item.to - item.from;
  return (
    <AbsoluteFill style={{ alignItems: 'center', paddingTop: item.y ?? 300 }}>
      <div
        style={{
          backgroundColor: item.color ? C[item.color] : C.green,
          padding: '6px 34px',
          rotate: '-3deg',
          border: `6px solid ${C.black}`,
          boxShadow: `10px 10px 0 ${C.black}`,
          scale: interpolate(frame, [0, 5], [1.4, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
          opacity: interpolate(frame, [len - 4, len], [1, 0], clamp),
        }}
      >
        <div style={{ fontFamily: FONT, fontSize: 120, lineHeight: 1.05, color: C.black }}>{item.text}</div>
      </div>
    </AbsoluteFill>
  );
};

export const EndCard: React.FC = () => {
  useAnton();
  const C = usePalette();
  const frame = useCurrentFrame();
  const pop = (at: number) => ({
    opacity: frame >= at ? 1 : 0,
    scale: interpolate(frame, [at, at + 6], [1.35, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
  });
  return (
    <AbsoluteFill style={{ backgroundColor: C.purple, justifyContent: 'center', alignItems: 'center', gap: 30 }}>
      <Halftone color={C.green} opacity={0.25} />
      <Inked text="COMENTE" size={170} color={C.white} style={pop(0)} />
      <div style={{ backgroundColor: C.green, padding: '0 40px', rotate: '-4deg', border: `8px solid ${C.black}`, ...pop(6) }}>
        <div style={{ fontFamily: FONT, fontSize: 250, lineHeight: 1.1, color: C.black }}>IMAGENS</div>
      </div>
      <Inked text="E RECEBA O EBOOK" size={120} color={C.yellow} style={pop(14)} />
      <div style={{ fontFamily: FONT, fontSize: 70, color: C.white, marginTop: 80, ...pop(24) }}>@catoliconabiblia</div>
    </AbsoluteFill>
  );
};

export const Reel: React.FC = () => {
  useAnton();
  const C = usePalette();
  return (
    <AbsoluteFill style={{ backgroundColor: C.black }}>
      <Sequence durationInFrames={HOOK_FRAMES}>
        <Exodo20Hook />
      </Sequence>
      <Sequence from={HOOK_FRAMES} durationInFrames={LETTERING.bodyFrames}>
        <OffthreadVideo src={staticFile('body.mp4')} />
        {LETTERING.items.map((item) => (
          <Sequence key={item.text + item.from} from={item.from} durationInFrames={item.to - item.from}>
            <Tag item={item} />
          </Sequence>
        ))}
      </Sequence>
      <Sequence from={HOOK_FRAMES + LETTERING.bodyFrames} durationInFrames={END_FRAMES}>
        <EndCard />
      </Sequence>
    </AbsoluteFill>
  );
};
