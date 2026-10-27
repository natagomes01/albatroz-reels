import React from 'react';
import { AbsoluteFill, Easing, Img, interpolate, Sequence, staticFile, useCurrentFrame } from 'remotion';
import { FONT, Halftone, HOOK_FRAMES, Inked, PaletteContext, usePalette } from '../Exodo20Hook';
import { Reel } from '../Reel';
import { IDV_TONES } from '../v3/ReelV3';
import captions from './ebook-captions.json';

// V4: V3 plus the ebook passing on screen while the owner says the CTA, so the viewer sees what they get.
// Times are body-clip seconds (clips/a931c03); the body starts after the hook.
const FPS = 30;
const at = (clipS: number) => HOOK_FRAMES + Math.round(clipS * FPS);
const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

type Page = { file: string; from: number }; // from: clip seconds
type Pass = { from: number; to: number; pages: Page[]; tags: { text: string; from: number; to: number }[] };

// Pass 1: "lista compilada com todas as 76 passagens ... lugar sagrado de culto" (master 80.6 to 92.1 s).
// Pass 2: "você vai pegar a sua Bíblia e vai conferir na sua casa um por um" (master 102.5 to 106.6 s).
const PASSES: Pass[] = [
  {
    from: 68.94,
    to: 80.97, // the clip cut after "culto": the Fouquet B-roll runs until here
    pages: [
      { file: 'page-01.jpg', from: 68.94 },
      { file: 'page-02.jpg', from: 72.12 },
      { file: 'page-08.jpg', from: 73.82 },
      { file: 'page-14.jpg', from: 75.0 },
      { file: 'page-18.jpg', from: 76.26 },
      { file: 'page-26.jpg', from: 77.4 },
      { file: 'page-35.jpg', from: 78.5 },
      { file: 'page-39.jpg', from: 79.4 },
    ],
    tags: [
      { text: 'EBOOK GRÁTIS', from: 68.94, to: 71.2 },
      { text: '76 VERSÍCULOS', from: 71.24, to: 73.8 },
    ],
  },
  {
    from: 90.27,
    to: 94.39,
    pages: [
      { file: 'page-20.jpg', from: 90.27 },
      { file: 'page-22.jpg', from: 92.3 },
    ],
    tags: [{ text: 'CONFIRA UM POR UM', from: 90.6, to: 94.39 }],
  },
];

const PAGE_H = 1000;
const PAGE_W = Math.round((PAGE_H * 1130) / 1600);
const PAGE_TOP = 150;

// One page of the ebook: slides in from the right and settles with a small tilt; older pages stay
// stacked behind it, pushed back and darker.
const PageCard: React.FC<{ page: Page; index: number; frame: number; passFrom: number; current: number }> = ({
  page, index, frame, passFrom, current,
}) => {
  const C = usePalette();
  const start = at(page.from) - at(passFrom);
  const local = frame - start;
  const first = index === 0;
  const depth = current - index; // 0 = on top
  const tilt = ((index % 2 === 0 ? -1 : 1) * 2.5);
  return (
    <div
      style={{
        position: 'absolute',
        left: (1080 - PAGE_W) / 2,
        top: PAGE_TOP,
        width: PAGE_W,
        height: PAGE_H,
        opacity: depth > 2 ? 0 : 1,
        translate: first
          ? `0px ${interpolate(local, [0, 8], [500, 0], { ...clamp, easing: Easing.out(Easing.cubic) })}px`
          : `${interpolate(local, [0, 7], [1100, 0], { ...clamp, easing: Easing.out(Easing.back(1.4)) })}px ${depth * -18}px`,
        rotate: `${first ? interpolate(local, [0, 8], [-14, tilt], clamp) : interpolate(local, [0, 7], [12, tilt], clamp)}deg`,
        scale: (first ? interpolate(local, [0, 8], [0.55, 1], { ...clamp, easing: Easing.out(Easing.cubic) }) : 1) * (1 - depth * 0.04),
        filter: `brightness(${1 - depth * 0.18})`,
        boxShadow: `18px 22px 0 ${C.black}, 0 30px 60px rgba(0, 0, 0, 0.45)`,
        border: `6px solid ${C.black}`,
        backgroundColor: C.white,
      }}
    >
      <Img src={staticFile(`ebook/${page.file}`)} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
    </div>
  );
};

const Tag: React.FC<{ text: string; local: number; len: number }> = ({ text, local, len }) => {
  const C = usePalette();
  return (
    <AbsoluteFill style={{ alignItems: 'center', paddingTop: 70 }}>
      <div
        style={{
          backgroundColor: C.green,
          padding: '4px 34px',
          rotate: '-4deg',
          border: `6px solid ${C.black}`,
          boxShadow: `10px 10px 0 ${C.black}`,
          scale: interpolate(local, [0, 5], [1.4, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
          opacity: interpolate(local, [len - 4, len], [1, 0], clamp),
        }}
      >
        <div style={{ fontFamily: FONT, fontSize: 110, lineHeight: 1.05, color: C.black, whiteSpace: 'nowrap' }}>{text}</div>
      </div>
    </AbsoluteFill>
  );
};

// The body's own captions (ASS Anton 128, black outline 6, yellow word), redrawn over the ebook so they
// do not disappear while the pages cover the screen. Lines come from captions.ass.
type CapEvent = { s: number; e: number; y: number; parts: { t: string; hl: boolean }[] };
const CAPTIONS = (captions as { events: CapEvent[] }).events;

const Captions: React.FC<{ clipS: number }> = ({ clipS }) => (
  <AbsoluteFill>
    {CAPTIONS.filter((c) => clipS >= c.s && clipS < c.e).map((c, i) => (
      <div
        key={i}
        style={{
          position: 'absolute',
          left: 0,
          width: 1094,
          bottom: 1920 - c.y,
          textAlign: 'center',
          fontFamily: FONT,
          // libass sizes a font by its full line height (ascent + descent, 1.506 em for Anton)
          fontSize: 75,
          lineHeight: '128px',
          letterSpacing: 1,
          WebkitTextStroke: '9px #000000',
          paintOrder: 'stroke fill',
          whiteSpace: 'nowrap',
        }}
      >
        {c.parts.map((p, j) => (
          <span key={j} style={{ color: p.hl ? '#FFE500' : '#FFFFFF' }}>
            {p.t}
          </span>
        ))}
      </div>
    ))}
  </AbsoluteFill>
);

const EbookPass: React.FC<{ pass: Pass }> = ({ pass }) => {
  const C = usePalette();
  const frame = useCurrentFrame(); // local to the pass
  const len = at(pass.to) - at(pass.from);
  const clipS = pass.from + frame / FPS;
  const current = pass.pages.reduce((n, p, i) => (frame >= at(p.from) - at(pass.from) ? i : n), 0);
  return (
    <AbsoluteFill
      style={{
        backgroundColor: C.purple,
        // hard cuts in and out (a fade let the B-roll under it show through); a push-in before the cut out
        scale: interpolate(frame, [len - 5, len], [1, 1.15], clamp),
      }}
    >
      <Halftone color={C.green} opacity={0.3} />
      {pass.pages.map((p, i) =>
        frame >= at(p.from) - at(pass.from) ? (
          <PageCard key={p.file} page={p} index={i} frame={frame} passFrom={pass.from} current={current} />
        ) : null,
      )}
      {pass.tags.map((t) => {
        const s = at(t.from) - at(pass.from);
        const e = at(t.to) - at(pass.from);
        return frame >= s && frame < e ? <Tag key={t.text} text={t.text} local={frame - s} len={e - s} /> : null;
      })}
      <Captions clipS={clipS} />
    </AbsoluteFill>
  );
};

export const ReelV4: React.FC = () => (
  <PaletteContext.Provider value={IDV_TONES}>
    <AbsoluteFill>
      <Reel />
      {PASSES.map((pass) => (
        <Sequence key={pass.from} from={at(pass.from)} durationInFrames={at(pass.to) - at(pass.from)}>
          <EbookPass pass={pass} />
        </Sequence>
      ))}
    </AbsoluteFill>
  </PaletteContext.Provider>
);
