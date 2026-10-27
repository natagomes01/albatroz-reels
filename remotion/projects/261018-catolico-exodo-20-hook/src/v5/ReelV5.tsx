import React from 'react';
import { AbsoluteFill, Easing, interpolate, Sequence, useCurrentFrame } from 'remotion';
import { FONT, HOOK_FRAMES, PaletteContext, usePalette } from '../Exodo20Hook';
import { IDV_TONES } from '../v3/ReelV3';
import { ReelV4 } from '../v4/ReelV4';

// V5: V4 plus a top strip right after the hook telling the viewer to stay for the free gift (the ebook is
// only named past the middle of the video).
export const STAY_FRAMES = 150; // 5 s
const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

const StayBanner: React.FC = () => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const drop = interpolate(frame, [0, 7], [-420, 0], { ...clamp, easing: Easing.out(Easing.back(1.3)) });
  const lift = interpolate(frame, [STAY_FRAMES - 6, STAY_FRAMES], [0, -420], { ...clamp, easing: Easing.in(Easing.cubic) });
  // the gift hops every second
  const hop = Math.abs(Math.sin(((frame - 7) / 30) * Math.PI)) * (frame > 7 ? 1 : 0);
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          top: 170,
          left: -20,
          width: 1120,
          rotate: '-2deg',
          translate: `0px ${drop + lift}px`,
          backgroundColor: C.green,
          borderTop: `8px solid ${C.black}`,
          borderBottom: `8px solid ${C.black}`,
          boxShadow: `0 14px 0 ${C.black}`,
          padding: '14px 0 18px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          fontFamily: FONT,
          color: C.black,
          lineHeight: 1.02,
          whiteSpace: 'nowrap',
        }}
      >
        <div style={{ fontSize: 84 }}>FIQUE ATÉ O FINAL PARA RECEBER</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
          <span style={{ fontSize: 108, color: C.red, WebkitTextStroke: `5px ${C.black}`, paintOrder: 'stroke fill' }}>
            O PRESENTE GRATUITO
          </span>
          <span style={{ fontSize: 100, display: 'inline-block', translate: `0px ${-hop * 16}px`, rotate: `${hop * 10}deg` }}>
            🎁
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const ReelV5: React.FC = () => (
  <AbsoluteFill>
    <ReelV4 />
    <PaletteContext.Provider value={IDV_TONES}>
      <Sequence from={HOOK_FRAMES} durationInFrames={STAY_FRAMES}>
        <StayBanner />
      </Sequence>
    </PaletteContext.Provider>
  </AbsoluteFill>
);
