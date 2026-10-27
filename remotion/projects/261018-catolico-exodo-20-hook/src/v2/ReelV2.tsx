import React from 'react';
import { AbsoluteFill, Easing, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame } from 'remotion';
import { HOOK_FRAMES } from '../Exodo20Hook';
import { END_FRAMES, LETTERING, type Lettering } from '../Reel';
import { FIELD_TESSERAE, Frame, GARAMOND, Halo, K, Mosaic, Serif, Tesserae } from './Byzantine';
import { HookV2 } from './HookV2';

// V2 of the Reel: same body and lettering times as v1, IDV elements.
export const REEL_V2_FRAMES = HOOK_FRAMES + LETTERING.bodyFrames + END_FRAMES;
const TAG_Y = 1000;
const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

// Navy card with the double gold rule and a gold underline under the words (IDV 3, items 1 and 5).
const TagV2: React.FC<{ item: Lettering }> = ({ item }) => {
  const frame = useCurrentFrame();
  const len = item.to - item.from;
  return (
    // on the shirt, above the caption row: v1's top position covered the head
    <AbsoluteFill style={{ alignItems: 'center', paddingTop: TAG_Y }}>
      <div
        style={{
          backgroundColor: 'rgba(15, 31, 61, 0.92)',
          border: `3px solid ${K.gold}`,
          outline: `1.5px solid rgba(184, 150, 62, 0.6)`,
          outlineOffset: -10,
          padding: '18px 46px 22px',
          opacity: interpolate(frame, [0, 4, len - 4, len], [0, 1, 1, 0], clamp),
          translate: `0px ${interpolate(frame, [0, 6], [14, 0], { ...clamp, easing: Easing.out(Easing.cubic) })}px`,
        }}
      >
        <div
          style={{
            fontFamily: GARAMOND,
            fontWeight: 700,
            fontSize: 92,
            whiteSpace: 'nowrap',
            lineHeight: 1.05,
            color: K.ivory,
            textDecoration: 'underline',
            textDecorationColor: K.gold,
            textDecorationThickness: 5,
            textUnderlineOffset: 14,
          }}
        >
          {item.text}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const EndCardV2: React.FC = () => {
  const frame = useCurrentFrame();
  const enter = (at: number) => ({
    opacity: interpolate(frame, [at, at + 8], [0, 1], clamp),
    translate: `0px ${interpolate(frame, [at, at + 12], [12, 0], { ...clamp, easing: Easing.out(Easing.cubic) })}px`,
  });
  return (
    <AbsoluteFill style={{ backgroundColor: K.navy, justifyContent: 'center', alignItems: 'center' }}>
      <Tesserae pattern={FIELD_TESSERAE} opacity={0.25} />
      <Halo r={380} style={{ opacity: interpolate(frame, [4, 16], [0, 0.85], clamp), scale: interpolate(frame, [0, 105], [1, 1.03], clamp) }} />
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 26 }}>
        <Serif text="Comente" size={150} weight={600} color={K.ivory} style={enter(0)} />
        <Mosaic text="IMAGENS" size={185} style={enter(6)} />
        <Serif text="e receba o ebook" size={110} weight={600} color={K.ivory} style={enter(14)} />
        <div style={{ fontFamily: GARAMOND, fontWeight: 600, fontSize: 64, color: K.ivorySoft, marginTop: 90, ...enter(24) }}>
          @catoliconabiblia
        </div>
      </div>
      <Frame />
    </AbsoluteFill>
  );
};

export const ReelV2: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: K.deep }}>
    <Sequence durationInFrames={HOOK_FRAMES}>
      <HookV2 />
    </Sequence>
    <Sequence from={HOOK_FRAMES} durationInFrames={LETTERING.bodyFrames}>
      <OffthreadVideo src={staticFile('body.mp4')} />
      {LETTERING.items.map((item) => (
        <Sequence key={item.text + item.from} from={item.from} durationInFrames={item.to - item.from}>
          <TagV2 item={item} />
        </Sequence>
      ))}
    </Sequence>
    <Sequence from={HOOK_FRAMES + LETTERING.bodyFrames} durationInFrames={END_FRAMES}>
      <EndCardV2 />
    </Sequence>
  </AbsoluteFill>
);
