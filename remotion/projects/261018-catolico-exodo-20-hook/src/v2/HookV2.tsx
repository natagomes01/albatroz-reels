import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Easing,
  interpolate,
  OffthreadVideo,
  random,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import { SHOTS, shake, type Shot } from '../Exodo20Hook';
import {
  FIELD_TESSERAE, Frame, GOLD_TESSERAE, Halo, K, Mosaic, RED_TESSERAE, Ribbon, Serif, Tesserae,
} from './Byzantine';

// V2 of the hook: same cuts and timing as v1 (SHOTS), dressed in the Católico na Bíblia IDV.
const CAPTION_Y = 1400;
const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;
const pop = (local: number, from = 1.5) =>
  interpolate(local, [0, 5], [from, 1], { ...clamp, easing: Easing.out(Easing.cubic) });

const WALL = [
  { kind: 'mosaic' as const },
  { kind: 'ivory' as const },
  { kind: 'mosaic' as const },
  { kind: 'red' as const },
  { kind: 'goldLight' as const },
];

const Wall: React.FC<{ count: number; seed: string; local: number; drift: number }> = ({ count, seed, local, drift }) => (
  <AbsoluteFill style={{ overflow: 'hidden' }}>
    {Array.from({ length: count }, (_, i) => {
      const r = (k: string) => random(`${seed}-${i}-${k}`);
      const size = 90 + r('s') * (count > 20 ? 300 : 380);
      const dir = r('d') > 0.5 ? 1 : -1;
      const text = r('t') > 0.3 ? 'ÊXODO 20' : '20';
      const kind = WALL[Math.floor(r('c') * WALL.length)].kind;
      const style: React.CSSProperties = {
        position: 'absolute',
        left: -200 + r('x') * 1200,
        top: -100 + r('y') * 2000,
        rotate: `${(r('r') - 0.5) * 30}deg`,
        translate: `${dir * drift * (local / 15)}px 0px`,
        // the mosaic builds up: each word lands a frame or two after the previous one
        opacity: local >= Math.floor((i / count) * 5) ? 1 : 0,
      };
      if (kind === 'mosaic') return <Mosaic key={i} text={text} size={size} style={style} />;
      if (kind === 'red') return <Mosaic key={i} text={text} size={size} pattern={RED_TESSERAE} style={style} />;
      return <Serif key={i} text={text} size={size} weight={800} color={kind === 'ivory' ? K.ivory : K.goldLight} style={style} />;
    })}
  </AbsoluteFill>
);

const Face: React.FC<{ shot: Extract<Shot, { kind: 'face' }>; local: number; len: number }> = ({ shot, local, len }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: K.deep }}>
      <AbsoluteFill
        style={{
          scale: interpolate(local, [0, len], shot.zoom, clamp),
          rotate: `${shot.rotate ?? 0}deg`,
          translate: shot.shake ? shake(frame, interpolate(local, [0, len], [shot.shake, 3], clamp)) : '0px 0px',
          transformOrigin: '52% 32%',
        }}
      >
        <OffthreadVideo muted src={staticFile('hook-src.mp4')} style={{ width: '100%', height: '100%' }} />
      </AbsoluteFill>
      {/* navy vignette ties the room footage to the cards */}
      <AbsoluteFill style={{ background: 'radial-gradient(ellipse at 52% 38%, transparent 45%, rgba(10, 21, 48, 0.75) 100%)' }} />
      {shot.ghost ? (
        <AbsoluteFill style={{ opacity: shot.ghost, mixBlendMode: 'screen' }}>
          <Wall count={14} seed={`g${shot.from}`} local={local + 5} drift={60} />
        </AbsoluteFill>
      ) : null}
      {shot.word === '20' ? (
        <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 160 }}>
          <Mosaic text="20" size={720} pattern={RED_TESSERAE} style={{ scale: pop(local), filter: `drop-shadow(0 0 0 ${K.gold}) drop-shadow(12px 12px 0 ${K.deep})` }} />
        </AbsoluteFill>
      ) : shot.word ? (
        <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 1920 - CAPTION_Y }}>
          <Serif text={shot.word} size={210} weight={800} color={K.ivory} style={{ scale: pop(local), rotate: `${-(shot.rotate ?? 0) * 1.5}deg` }} />
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

const LastWords: React.FC<{ frame: number }> = ({ frame }) => (
  <AbsoluteFill style={{ top: CAPTION_Y - 170, height: 220, flexDirection: 'row', justifyContent: 'center', gap: 30 }}>
    {[
      { w: 'VOCÊ', at: 129 },
      { w: 'NÃO', at: 132 },
      { w: 'LEU?', at: 136 },
    ].map(({ w, at }) =>
      w === 'LEU?' ? (
        <Mosaic key={w} text={w} size={118} style={{ opacity: frame >= at ? 1 : 0, scale: interpolate(frame, [at, at + 3], [1.3, 1], clamp) }} />
      ) : (
        <Serif key={w} text={w} size={118} weight={800} color={K.ivory} style={{ opacity: frame >= at ? 1 : 0, scale: interpolate(frame, [at, at + 3], [1.3, 1], clamp) }} />
      ),
    )}
  </AbsoluteFill>
);

const Card: React.FC<{ bg: string; tesserae: string; opacity: number; children: React.ReactNode }> = ({ bg, tesserae, opacity, children }) => (
  <AbsoluteFill style={{ backgroundColor: bg, justifyContent: 'center', alignItems: 'center' }}>
    <Tesserae pattern={tesserae} opacity={opacity} />
    {children}
  </AbsoluteFill>
);

export const HookV2: React.FC = () => {
  const frame = useCurrentFrame();
  const shot = SHOTS.find((s) => frame >= s.from && frame < s.to) ?? SHOTS[SHOTS.length - 1];
  const local = frame - shot.from;
  const len = shot.to - shot.from;

  let body: React.ReactNode;
  if (shot.kind === 'face') {
    body = <Face shot={shot} local={local} len={len} />;
  } else if (shot.kind === 'stamp') {
    body = (
      <Card bg={K.navy} tesserae={FIELD_TESSERAE} opacity={0.35}>
        <Halo r={330} style={{ top: 960 - 390 + 130, left: 540 - 390, opacity: 0.9 }} />
        <div style={{ rotate: '-5deg', translate: shake(frame, 7), display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <Serif text="ÊXODO" size={225} weight={800} color={K.ivory} />
          <Mosaic text="20" size={780} style={{ marginTop: -50 }} />
        </div>
      </Card>
    );
  } else if (shot.kind === 'single') {
    body = (
      <Card bg={K.red} tesserae={RED_TESSERAE} opacity={0.55}>
        <Halo r={430} rays={16} style={{ opacity: interpolate(local, [0, 6], [0, 1], clamp), scale: interpolate(local, [0, len], [0.9, 1.04], clamp) }} />
        <Mosaic
          text="20"
          size={1050}
          style={{ scale: pop(local, 1.7), translate: shake(frame, interpolate(local, [0, 10], [30, 4], clamp)) }}
        />
      </Card>
    );
  } else if (shot.kind === 'triple') {
    body = (
      <Card bg={K.navy} tesserae={FIELD_TESSERAE} opacity={0.5}>
        {[0, 1, 2].map((i) => {
          const style: React.CSSProperties = {
            rotate: `${(i - 1) * 8}deg`,
            translate: shake(frame + i * 7, 10),
            opacity: local >= i * 2 ? 1 : 0,
            marginTop: i ? -110 : 0,
          };
          return i === 1 ? (
            <Serif key={i} text="20" size={560} weight={800} color={K.ivory} style={style} />
          ) : (
            <Mosaic key={i} text="20" size={560} pattern={i === 2 ? RED_TESSERAE : GOLD_TESSERAE} style={style} />
          );
        })}
      </Card>
    );
  } else {
    body = (
      <Card bg={shot.count > 20 ? K.deep : K.blue} tesserae={FIELD_TESSERAE} opacity={shot.count > 20 ? 0.6 : 0.4}>
        <Wall count={shot.count} seed={shot.seed} local={local} drift={shot.drift} />
        {shot.banner ? (
          <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
            <Ribbon style={{ rotate: '-5deg', translate: shake(frame, 6) }}>
              <Serif text={shot.banner} size={100} weight={800} color={K.ivory} />
            </Ribbon>
          </AbsoluteFill>
        ) : null}
      </Card>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: K.deep }}>
      <Audio src={staticFile('hook-src.mp4')} />
      {body}
      {frame >= 129 ? <LastWords frame={frame} /> : null}
      <Frame />
    </AbsoluteFill>
  );
};
