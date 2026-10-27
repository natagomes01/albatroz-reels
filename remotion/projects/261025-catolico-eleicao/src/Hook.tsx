import React, { createContext, useContext, useEffect, useState } from 'react';
import {
  AbsoluteFill,
  Audio,
  continueRender,
  delayRender,
  Easing,
  Img,
  interpolate,
  OffthreadVideo,
  random,
  staticFile,
  useCurrentFrame,
} from 'remotion';

// 23.30 to 27.50 s of the job master (job 261025-catolico-eleicao, election day):
// "Você já pecou, cara. Você já pecou, não importa se faz parte do lado A ou do lado B."
export const HOOK_FRAMES = 126;

// Católico na Bíblia IDV tones for short video (catolico/_padroes/identidade-catolico-na-biblia.md, section 9).
export const C = {
  black: '#0A1530', // deep navy: card background and ink
  gold: '#C9A54E',
  field: '#182C52', // alternate card background
  lightGold: '#E0C87F',
  red: '#B02A2A',
  white: '#F3EBDC', // ivory
};
export type Palette = typeof C;
export const PaletteContext = createContext<Palette>(C);
export const usePalette = () => useContext(PaletteContext);
export const FONT = 'Anton';
// The caption row of the whole Reel, close to the face (owner, 2026-10-22). Everything on screen stays inside the
// Reels safe zone (assets/safe-zone.png in albatroz-shorts: y 252 to 1080), so nothing sits under the app's buttons.
export const CAPTION_Y = 960;
const WORD_BOTTOM = CAPTION_Y + 100; // bottom edge of the hook's inked words

export type Shot =
  | { kind: 'face'; from: number; to: number; zoom: [number, number]; rotate?: number;
      word?: string; wordColor?: keyof Palette; wordSize?: number; ghost?: number; shake?: number }
  | { kind: 'stamp'; from: number; to: number }
  | { kind: 'single'; from: number; to: number; text: string; color: keyof Palette; size: number }
  | { kind: 'triple'; from: number; to: number; text: string }
  // a theosis image (public dir hook/), slow push-in, with the spoken word inked over it
  // held about 1 s so the viewer can tell what it is; the spoken words change over it
  | { kind: 'image'; from: number; to: number; file: string; origin: string;
      words?: { w: string; at: number; color?: keyof Palette; size?: number }[]; banner?: { at: number; to: number; text: string } }
  | { kind: 'wall'; from: number; to: number; count: number; seed: string; drift: number; banner?: string };

// Frames are the audio onsets of hook-src.mp4 (per-frame RMS), not the whisper word times:
// você 2, já 14, pecou 19, cara 24, (pause 29 to 38), você 39, já 47, pecou 51, não 60, importa 66,
// se faz 77, parte 86, do lado A 93, ou do 102, lado B 106, end 123.
export const SHOTS: Shot[] = [
  { kind: 'stamp', from: 0, to: 2 }, // frame 0 must read on its own in the feed
  { kind: 'face', from: 2, to: 14, zoom: [1.22, 1.28], rotate: 3, word: 'VOCÊ', wordSize: 240 },
  { kind: 'image', from: 14, to: 39, file: 'caim-abel-ticiano.jpg', origin: '50% 40%',
    words: [{ w: 'JÁ', at: 14, color: 'gold', size: 260 }, { w: 'PECOU', at: 19, color: 'red', size: 270 }, { w: 'CARA', at: 24 }] },
  { kind: 'face', from: 39, to: 51, zoom: [1.32, 1.38], rotate: -3, word: 'VOCÊ JÁ', wordSize: 200, ghost: 0.55 },
  { kind: 'wall', from: 51, to: 60, count: 34, seed: 'pecou', drift: 50, banner: 'PECOU' },
  { kind: 'image', from: 60, to: 93, file: 'juizo-final-michelangelo.jpg', origin: '50% 30%',
    words: [{ w: 'NÃO IMPORTA', at: 60, size: 170 }, { w: 'SE FAZ PARTE', at: 77, color: 'lightGold', size: 170 }] },
  { kind: 'face', from: 93, to: HOOK_FRAMES, zoom: [1.12, 1.16] },
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

// "PECOU" multiplying until it fills the screen, with a few "VOCÊ JÁ" among them.
const Wall: React.FC<{ count: number; seed: string; local: number; drift: number }> = ({
  count, seed, local, drift,
}) => {
  const C = usePalette();
  const WALL_COLORS = [C.gold, C.lightGold, C.white, C.gold, C.red];
  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      {Array.from({ length: count }, (_, i) => {
        const r = (k: string) => random(`${seed}-${i}-${k}`);
        const size = 90 + r('s') * (count > 20 ? 300 : 380);
        const dir = r('d') > 0.5 ? 1 : -1;
        return (
          <Inked
            key={i}
            text={r('t') > 0.25 ? 'PECOU' : 'VOCÊ JÁ'}
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
          transformOrigin: '50% 30%', // the face in the car framing
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
        <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 1920 - WORD_BOTTOM }}>
          <Inked
            text={shot.word}
            size={shot.wordSize ?? 200}
            color={C[shot.wordColor ?? 'white']}
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

// The closing question on the clean face, word by word at the caption row (two rows, inside x 72 to 1026).
const LAST_AT = 93;
const LastWords: React.FC<{ frame: number }> = ({ frame }) => {
  const C = usePalette();
  const rows = [
    [{ w: 'LADO A', at: 93, color: C.white }, { w: 'OU', at: 102, color: C.lightGold }],
    [{ w: 'LADO B?', at: 106, color: C.gold }],
  ];
  return (
    <AbsoluteFill style={{ top: CAPTION_Y - 150, height: 330, alignItems: 'center', gap: 6 }}>
      {rows.map((row, i) => (
        <div key={i} style={{ display: 'flex', gap: 30 }}>
          {row.map(({ w, at, color }) => (
            <Inked
              key={w}
              text={w}
              size={i ? 180 : 150}
              color={color}
              style={{
                opacity: frame >= at ? 1 : 0,
                scale: interpolate(frame, [at, at + 3], [1.3, 1], clamp),
              }}
            />
          ))}
        </div>
      ))}
    </AbsoluteFill>
  );
};

export const Hook: React.FC = () => {
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
        <Halftone color={C.gold} opacity={0.45} />
        <div style={{ rotate: '-7deg', translate: shake(frame, 8), display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <Inked text="VOCÊ" size={300} color={C.white} />
          <Inked text="JÁ" size={260} color={C.gold} style={{ marginTop: -10 }} />
          <Inked text="PECOU" size={330} color={C.red} style={{ marginTop: -10 }} />
        </div>
      </AbsoluteFill>
    );
  } else if (shot.kind === 'single') {
    body = (
      <AbsoluteFill style={{ backgroundColor: shot.color === 'gold' ? C.black : C.field, justifyContent: 'center', alignItems: 'center' }}>
        <Halftone color={C.gold} opacity={0.35} />
        <Inked
          text={shot.text}
          size={shot.size}
          color={C[shot.color]}
          style={{
            scale: interpolate(local, [0, 5], [1.7, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
            translate: shake(frame, interpolate(local, [0, 10], [30, 4], clamp)),
          }}
        />
      </AbsoluteFill>
    );
  } else if (shot.kind === 'image') {
    body = (
      <AbsoluteFill style={{ backgroundColor: C.black, overflow: 'hidden' }}>
        <Img
          src={staticFile(`hook/${shot.file}`)}
          style={{
            width: '100%', height: '100%', objectFit: 'cover', objectPosition: shot.origin,
            transformOrigin: shot.origin,
            scale: interpolate(local, [0, len], [1.25, 1.1], { ...clamp, easing: Easing.out(Easing.cubic) }),
          }}
        />
        <Halftone color={C.gold} opacity={0.18} />
        {(() => {
          const cur = [...(shot.words ?? [])].reverse().find((w) => frame >= w.at);
          if (!cur) return null;
          const since = frame - cur.at;
          return (
            <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 1920 - WORD_BOTTOM }}>
              <Inked
                key={cur.w}
                text={cur.w}
                size={cur.size ?? 210}
                color={C[cur.color ?? 'white']}
                style={{
                  scale: interpolate(since, [0, 4], [1.6, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
                  translate: shake(frame, interpolate(since, [0, 8], [18, 2], clamp)),
                }}
              />
            </AbsoluteFill>
          );
        })()}
        {shot.banner && frame >= shot.banner.at && frame < shot.banner.to ? (
          <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 1920 - WORD_BOTTOM }}>
            <div style={{ backgroundColor: C.red, padding: '10px 50px', rotate: '-6deg', translate: shake(frame, 6),
                          border: `6px solid ${C.black}`, boxShadow: `12px 12px 0 ${C.black}` }}>
              <Inked text={shot.banner.text} size={190} color={C.white} />
            </div>
          </AbsoluteFill>
        ) : null}
      </AbsoluteFill>
    );
  } else if (shot.kind === 'triple') {
    body = (
      <AbsoluteFill style={{ backgroundColor: C.field, justifyContent: 'center', alignItems: 'center' }}>
        <Halftone color={C.lightGold} opacity={0.3} />
        {[C.white, C.gold, C.white].map((c, i) => (
          <Inked
            key={i}
            text={shot.text}
            size={330}
            color={c}
            style={{
              rotate: `${(i - 1) * 8}deg`,
              translate: shake(frame + i * 7, 10),
              opacity: local >= i * 2 ? 1 : 0,
              marginTop: i ? -40 : 0,
            }}
          />
        ))}
      </AbsoluteFill>
    );
  } else {
    body = (
      <AbsoluteFill style={{ backgroundColor: shot.count > 20 ? C.black : C.field }}>
        <Wall count={shot.count} seed={shot.seed} local={local} drift={shot.drift} />
        <Halftone color={C.gold} opacity={0.25} />
        {shot.banner ? (
          <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
            <div style={{ backgroundColor: C.red, padding: '10px 50px', rotate: '-6deg', translate: shake(frame, 6) }}>
              <Inked text={shot.banner} size={190} color={C.white} />
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
      {frame >= LAST_AT ? <LastWords frame={frame} /> : null}
    </AbsoluteFill>
  );
};
