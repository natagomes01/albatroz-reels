import React, { createContext, useContext, useEffect, useState } from 'react';
import {
  AbsoluteFill,
  Audio,
  continueRender,
  delayRender,
  Easing,
  interpolate,
  OffthreadVideo,
  random,
  staticFile,
  useCurrentFrame,
} from 'remotion';

// 0.00 to 4.95 s of the job master (spec: 03-spec/261018-catolico-exodo-20-hook.md).
export const HOOK_FRAMES = 149;

export const C = {
  black: '#000000',
  green: '#A6FF00',
  purple: '#2B0B3F',
  yellow: '#FFE600',
  red: '#E3001B',
  white: '#FFFFFF',
};
export type Palette = typeof C;
// v1 colours by default; the V3 Reel provides the Católico na Bíblia IDV tones instead (src/v3).
export const PaletteContext = createContext<Palette>(C);
export const usePalette = () => useContext(PaletteContext);
export const FONT = 'Anton';
const CAPTION_Y = 1400; // same caption row as the body (job setting caption_y)

export type Shot =
  | { kind: 'face'; from: number; to: number; zoom: [number, number]; rotate?: number;
      word?: string; wordColor?: string; wordSize?: number; ghost?: number; shake?: number }
  | { kind: 'stamp'; from: number; to: number }
  | { kind: 'single'; from: number; to: number }
  | { kind: 'triple'; from: number; to: number }
  | { kind: 'wall'; from: number; to: number; count: number; seed: string; drift: number; banner?: string };

// Frames: word starts in jobs/261018-biblia-proibe-imagens/words.json (t * 30), moved to the audio onsets
// (per-frame RMS) where whisper was late: first "20" at 23, second at 42.
export const SHOTS: Shot[] = [
  { kind: 'stamp', from: 0, to: 10 }, // frame 0 must read on its own in the feed
  { kind: 'face', from: 10, to: 23, zoom: [1.08, 1.14], word: 'ÊXODO', wordSize: 200 },
  { kind: 'single', from: 23, to: 42 },
  { kind: 'triple', from: 42, to: 53 },
  { kind: 'face', from: 53, to: 65, zoom: [1.32, 1.38], rotate: -4, word: 'ÊXODO', wordSize: 220 },
  { kind: 'wall', from: 65, to: 73, count: 8, seed: 'a', drift: 40 },
  { kind: 'face', from: 73, to: 83, zoom: [1.22, 1.28], rotate: 3, ghost: 0.35 },
  { kind: 'wall', from: 83, to: 94, count: 16, seed: 'b', drift: 90 },
  { kind: 'face', from: 94, to: 102, zoom: [1.4, 1.45], word: '20', wordSize: 700 },
  { kind: 'face', from: 102, to: 113, zoom: [1.15, 1.2], ghost: 0.5, shake: 14 },
  { kind: 'wall', from: 113, to: 129, count: 30, seed: 'c', drift: 220, banner: 'VOCÊ NÃO LEU?' },
  { kind: 'face', from: 129, to: HOOK_FRAMES, zoom: [1.0, 1.1] },
];

const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

export const useAnton = () => {
  const [handle] = useState(() => delayRender('Anton'));
  useEffect(() => {
    const face = new FontFace(FONT, `url(${staticFile('Anton-Regular.ttf')})`);
    face.load().then((f) => {
      document.fonts.add(f);
      continueRender(handle);
    });
  }, [handle]);
};

// Comic halftone over the cards.
export const Halftone: React.FC<{ color: string; opacity: number }> = ({ color, opacity }) => (
  <AbsoluteFill
    style={{
      backgroundImage: `radial-gradient(${color} 28%, transparent 30%)`,
      backgroundSize: '18px 18px',
      opacity,
      mixBlendMode: 'overlay',
    }}
  />
);

export const shake = (frame: number, amp: number) =>
  `${(random(`x${frame}`) - 0.5) * 2 * amp}px ${(random(`y${frame}`) - 0.5) * 2 * amp}px`;

export const Inked: React.FC<{ text: string; size: number; color: string; style?: React.CSSProperties }> = ({
  text, size, color, style,
}) => {
  const C = usePalette();
  return (
  <div
    style={{
      fontFamily: FONT,
      fontSize: size,
      lineHeight: 0.9,
      color,
      WebkitTextStroke: `${Math.max(4, size / 28)}px ${C.black}`,
      paintOrder: 'stroke fill',
      textShadow: `${size / 22}px ${size / 22}px 0 ${C.black}`,
      whiteSpace: 'nowrap',
      ...style,
    }}
  >
    {text}
  </div>
  );
};

const Wall: React.FC<{ count: number; seed: string; local: number; drift: number }> = ({
  count, seed, local, drift,
}) => {
  const C = usePalette();
  const WALL_COLORS = [C.green, C.yellow, C.white, C.green, C.red];
  return (
  <AbsoluteFill style={{ overflow: 'hidden' }}>
    {Array.from({ length: count }, (_, i) => {
      const r = (k: string) => random(`${seed}-${i}-${k}`);
      const size = 90 + r('s') * (count > 20 ? 300 : 380);
      const dir = r('d') > 0.5 ? 1 : -1;
      return (
        <Inked
          key={i}
          text={r('t') > 0.3 ? 'ÊXODO 20' : '20'}
          size={size}
          color={WALL_COLORS[Math.floor(r('c') * WALL_COLORS.length)]}
          style={{
            position: 'absolute',
            left: -200 + r('x') * 1200,
            top: -100 + r('y') * 2000,
            rotate: `${(r('r') - 0.5) * 36}deg`,
            translate: `${dir * drift * (local / 15)}px 0px`,
            // each word lands a frame or two after the previous one: the wall builds up
            opacity: local >= Math.floor((i / count) * 5) ? 1 : 0,
          }}
        />
      );
    })}
  </AbsoluteFill>
  );
};

const Face: React.FC<{ shot: Extract<Shot, { kind: 'face' }>; local: number; len: number }> = ({
  shot, local, len,
}) => {
  const C = usePalette();
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: C.black }}>
      <AbsoluteFill
        style={{
          scale: interpolate(local, [0, len], shot.zoom, clamp),
          rotate: `${shot.rotate ?? 0}deg`,
          translate: shot.shake ? shake(frame, interpolate(local, [0, len], [shot.shake, 3], clamp)) : '0px 0px',
          transformOrigin: '52% 32%', // the face in the hook framing
        }}
      >
        <OffthreadVideo muted src={staticFile('hook-src.mp4')} style={{ width: '100%', height: '100%' }} />
      </AbsoluteFill>
      {shot.ghost ? (
        <AbsoluteFill style={{ opacity: shot.ghost, mixBlendMode: 'screen' }}>
          <Wall count={14} seed={`g${shot.from}`} local={local + 5} drift={60} />
        </AbsoluteFill>
      ) : null}
      {shot.word ? (
        <AbsoluteFill
          style={shot.word === '20'
            ? { justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 160 }
            : { justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 1920 - CAPTION_Y }}
        >
          <Inked
            text={shot.word}
            size={shot.wordSize ?? 200}
            color={shot.wordColor ?? (shot.word === '20' ? C.red : C.white)}
            style={{
              scale: interpolate(local, [0, 4], [1.5, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
              rotate: `${-(shot.rotate ?? 0) * 1.5}deg`,
            }}
          />
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

const LastWords: React.FC<{ frame: number }> = ({ frame }) => {
  const C = usePalette();
  // "você" 4.29 s, "não" 4.41 s, "leu?" 4.53 s
  const words = [
    { w: 'VOCÊ', at: 129 },
    { w: 'NÃO', at: 132 },
    { w: 'LEU?', at: 136 },
  ];
  return (
    <AbsoluteFill style={{ top: CAPTION_Y - 150, height: 200, flexDirection: 'row', justifyContent: 'center', gap: 28 }}>
      {words.map(({ w, at }) => (
        <Inked
          key={w}
          text={w}
          size={140}
          color={w === 'LEU?' ? C.yellow : C.white}
          style={{
            opacity: frame >= at ? 1 : 0,
            scale: interpolate(frame, [at, at + 3], [1.3, 1], clamp),
          }}
        />
      ))}
    </AbsoluteFill>
  );
};

export const Exodo20Hook: React.FC = () => {
  useAnton();
  const C = usePalette();
  const frame = useCurrentFrame();
  const shot = SHOTS.find((s) => frame >= s.from && frame < s.to) ?? SHOTS[SHOTS.length - 1];
  const local = frame - shot.from;
  const len = shot.to - shot.from;

  let body: React.ReactNode;
  if (shot.kind === 'face') {
    body = <Face shot={shot} local={local} len={len} />;
  } else if (shot.kind === 'stamp') {
    body = (
      <AbsoluteFill style={{ backgroundColor: C.black, justifyContent: 'center', alignItems: 'center' }}>
        <Halftone color={C.red} opacity={0.5} />
        <div style={{ rotate: '-7deg', translate: shake(frame, 8), display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <Inked text="ÊXODO" size={330} color={C.white} />
          <Inked text="20" size={760} color={C.green} style={{ marginTop: -40 }} />
        </div>
      </AbsoluteFill>
    );
  } else if (shot.kind === 'single') {
    body = (
      <AbsoluteFill style={{ backgroundColor: C.black, justifyContent: 'center', alignItems: 'center' }}>
        <Halftone color={C.green} opacity={0.35} />
        <Inked
          text="20"
          size={1100}
          color={C.green}
          style={{
            scale: interpolate(local, [0, 5], [1.7, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
            translate: shake(frame, interpolate(local, [0, 10], [30, 4], clamp)),
          }}
        />
      </AbsoluteFill>
    );
  } else if (shot.kind === 'triple') {
    body = (
      <AbsoluteFill style={{ backgroundColor: C.purple, justifyContent: 'center', alignItems: 'center' }}>
        <Halftone color={C.yellow} opacity={0.3} />
        {[C.green, C.yellow, C.green].map((c, i) => (
          <Inked
            key={i}
            text="20"
            size={560}
            color={c}
            style={{
              rotate: `${(i - 1) * 8}deg`,
              translate: shake(frame + i * 7, 10),
              opacity: local >= i * 2 ? 1 : 0,
              marginTop: i ? -120 : 0,
            }}
          />
        ))}
      </AbsoluteFill>
    );
  } else {
    body = (
      <AbsoluteFill style={{ backgroundColor: shot.count > 20 ? C.black : C.purple }}>
        <Wall count={shot.count} seed={shot.seed} local={local} drift={shot.drift} />
        <Halftone color={C.green} opacity={0.25} />
        {shot.banner ? (
          <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
            <div style={{ backgroundColor: C.red, padding: '10px 40px', rotate: '-6deg', translate: shake(frame, 6) }}>
              <Inked text={shot.banner} size={150} color={C.white} />
            </div>
          </AbsoluteFill>
        ) : null}
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: C.black }}>
      <Audio src={staticFile('hook-src.mp4')} />
      {body}
      {frame >= 129 ? <LastWords frame={frame} /> : null}
    </AbsoluteFill>
  );
};
