import React from 'react';
import { loadFont } from '@remotion/google-fonts/EBGaramond';
import {
  AbsoluteFill,
  Easing,
  Freeze,
  Img,
  interpolate,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import { FONT, Halftone, Inked, usePalette, type Palette } from './Hook';
import body from './body.json';

// Everything over the pipeline's body render (clip e220a01, rendered with burn_captions false):
// full-screen inserts, the Mt 22,37-39 card in the top half of a split moment, reference tags, the captions
// (from the clip's captions.ass, drawn here bigger and at the middle row) and the follow CTA.
// body.json comes from build_body.py (clip frames, through the clip's edl.json).

const { fontFamily: SERIF } = loadFont('normal', { weights: ['400', '600'], subsets: ['latin', 'greek', 'greek-ext'] });

type Insert = { from: number; to: number; file: string; origin: string };
type Tag = { from: number; to: number; text: string; color?: keyof Palette; y: number };
type CapEvent = { from: number; to: number; line: number; lines: number; parts: { t: string; hl: boolean }[] };
type Body = {
  bodyFrames: number;
  inserts: Insert[];
  verse: { from: number; to: number };
  splits: { from: number; to: number }[];
  tags: Tag[];
  captions: CapEvent[];
  cta: { from: number; melhor: number; perfil: number };
};
export const BODY = body as Body;
export const HOLD_FRAMES = 36; // the CTA stays this long after the last word

const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

// A painting over the whole screen: slow push-in, hard cut in and out (a fade lets the frame under it flash).
const InsertCard: React.FC<{ item: Insert }> = ({ item }) => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const len = item.to - item.from;
  return (
    <AbsoluteFill style={{ backgroundColor: C.black, overflow: 'hidden' }}>
      <Img
        src={staticFile(`inserts/${item.file}`)}
        style={{
          width: '100%', height: '100%', objectFit: 'cover', objectPosition: item.origin, transformOrigin: item.origin,
          scale: interpolate(frame, [0, len], [1.04, 1.16], clamp),
        }}
      />
    </AbsoluteFill>
  );
};

// Mt 22,37-39 (today's Gospel, 30th Sunday, year A) in the top half (the pipeline's split moment puts a navy plate there and the face below).
const VerseCard: React.FC<{ len: number }> = ({ len }) => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const show = (at: number) => ({
    opacity: interpolate(frame, [at, at + 6], [0, 1], clamp),
    translate: `0px ${interpolate(frame, [at, at + 6], [24, 0], { ...clamp, easing: Easing.out(Easing.cubic) })}px`,
  });
  const lines = [
    { t: 'Amarás o Senhor teu Deus', hl: true },
    { t: 'de todo o teu coração.', hl: false },
    { t: 'Amarás o teu próximo', hl: true },
    { t: 'como a ti mesmo.', hl: true },
  ];
  return (
    <AbsoluteFill style={{ height: 960, backgroundColor: C.black, overflow: 'hidden' }}>
      <Halftone color={C.gold} opacity={0.16} />
      <div style={{ position: 'absolute', top: 230, left: 70, right: 70, height: 6, backgroundColor: C.gold }} />
      <div style={{ position: 'absolute', bottom: 40, left: 70, right: 70, height: 6, backgroundColor: C.gold }} />
      <AbsoluteFill style={{ alignItems: 'center', paddingTop: 270 }}>
        <div
          style={{
            backgroundColor: C.gold, padding: '4px 30px', rotate: '-3deg', border: `6px solid ${C.black}`,
            boxShadow: `10px 10px 0 ${C.white}`,
            scale: interpolate(frame, [0, 5], [1.4, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
          }}
        >
          <div style={{ fontFamily: FONT, fontSize: 96, lineHeight: 1.05, color: C.black, whiteSpace: 'nowrap' }}>MATEUS 22,37-39</div>
        </div>
        <div style={{ marginTop: 30, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
          {lines.map((l, i) => (
            <div
              key={l.t}
              style={{
                fontFamily: SERIF, fontWeight: l.hl ? 600 : 400, fontSize: l.hl ? 80 : 64, lineHeight: 1.15,
                color: l.hl ? C.gold : C.white, whiteSpace: 'nowrap', ...show(8 + i * 16),
              }}
            >
              {l.t}
            </div>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const TagBox: React.FC<{ item: Tag }> = ({ item }) => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const len = item.to - item.from;
  return (
    <AbsoluteFill style={{ alignItems: 'center', paddingTop: item.y }}>
      <div
        style={{
          backgroundColor: C[item.color ?? 'gold'],
          padding: '6px 34px',
          rotate: '-3deg',
          border: `6px solid ${C.black}`,
          boxShadow: `10px 10px 0 ${C.black}`,
          scale: interpolate(frame, [0, 5], [1.4, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
          opacity: interpolate(frame, [len - 4, len], [1, 0], clamp),
        }}
      >
        <div style={{ fontFamily: FONT, fontSize: 110, lineHeight: 1.05, color: C.black, whiteSpace: 'nowrap' }}>
          {item.text}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// The pipeline's caption screens (Anton, white, current word yellow), 30% bigger than the burned ones and
// on the middle row, near the face (the split line in split moments).
const CAPTION_PX = 98;
const PITCH = 112;
// Owner, 2026-10-25: the head fills the top half here (talking to the camera), so the caption block starts just
// below the middle of the frame, one or two lines, instead of being centred on it.
const CAPTION_TOP = 975;
const Captions: React.FC<{ frame: number }> = ({ frame }) => (
  <AbsoluteFill>
    {BODY.captions.filter((c) => frame >= c.from && frame < c.to).map((c, i) => {
      const chars = c.parts.reduce((n, p) => n + p.t.length, 0);
      const size = Math.min(CAPTION_PX, Math.floor(900 / (chars * 0.47))); // inside x 72 to 1026
      // on the split line in split moments, and a two-line screen still ends above y 1080
      const top = CAPTION_TOP + c.line * PITCH;
      return (
        <div
          key={i}
          style={{
            position: 'absolute', left: 0, width: 1080, top, height: PITCH, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            fontFamily: FONT, fontSize: size, lineHeight: 1, letterSpacing: 1,
            WebkitTextStroke: '12px #000000', paintOrder: 'stroke fill', whiteSpace: 'pre',
            textShadow: '0 6px 0 #000000',
          }}
        >
          {c.parts.map((p, j) => (
            <span key={j} style={{ color: p.hl ? '#FFE500' : '#FFFFFF' }}>{p.t}</span>
          ))}
        </div>
      );
    })}
  </AbsoluteFill>
);

// Over his last sentence, "Pode ir se confessar, é a melhor coisa que você vai fazer na sua vida": the sentence
// itself as end text under his face, then the follow CTA; all of it above y 1080 (safe zone).
const Cta: React.FC = () => {
  const C = usePalette();
  const frame = useCurrentFrame(); // local, 0 = "Pode"
  const pop = (at: number) => ({
    opacity: frame >= at ? 1 : 0,
    scale: interpolate(frame, [at, at + 6], [1.35, 1], { ...clamp, easing: Easing.out(Easing.cubic) }),
  });
  const { cta } = BODY;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute', left: 0, right: 0, top: 600, bottom: 0,
          background: `linear-gradient(to bottom, rgba(10,21,48,0) 0%, ${C.black} 12%)`,
          opacity: interpolate(frame, [0, 4], [0, 1], clamp),
        }}
      />
      <AbsoluteFill style={{ top: 700, alignItems: 'center', gap: 10 }}>
        <Inked text="PODE IR SE CONFESSAR" size={100} color={C.white} style={pop(0)} />
        <Inked text="É A MELHOR COISA QUE VOCÊ" size={66} color={C.lightGold} style={pop(cta.melhor - cta.from)} />
        <Inked text="VAI FAZER NA SUA VIDA" size={66} color={C.lightGold} style={pop(cta.melhor - cta.from)} />
        <div style={{ marginTop: 18, backgroundColor: C.gold, padding: '0 32px', rotate: '-4deg', border: `8px solid ${C.black}`,
                      boxShadow: `12px 12px 0 ${C.white}`, ...pop(cta.perfil - cta.from) }}>
          <div style={{ fontFamily: FONT, fontSize: 76, lineHeight: 1.2, color: C.black, whiteSpace: 'nowrap' }}>
            SIGA @CATOLICONABIBLIA
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const BodyLayer: React.FC = () => {
  const frame = useCurrentFrame(); // body frames
  const { cta } = BODY;
  return (
    <AbsoluteFill>
      <Sequence durationInFrames={BODY.bodyFrames}>
        <OffthreadVideo src={staticFile('body.mp4')} />
      </Sequence>
      {/* the last frame held under the CTA after the last word */}
      <Sequence from={BODY.bodyFrames}>
        <Freeze frame={BODY.bodyFrames - 1}>
          <OffthreadVideo muted src={staticFile('body.mp4')} />
        </Freeze>
      </Sequence>
      {BODY.inserts.map((it) => (
        <Sequence key={it.file} from={it.from} durationInFrames={it.to - it.from}>
          <InsertCard item={it} />
        </Sequence>
      ))}
      <Sequence from={BODY.verse.from} durationInFrames={BODY.verse.to - BODY.verse.from}>
        <VerseCard len={BODY.verse.to - BODY.verse.from} />
      </Sequence>
      {BODY.tags.map((t) => (
        <Sequence key={t.text} from={t.from} durationInFrames={t.to - t.from}>
          <TagBox item={t} />
        </Sequence>
      ))}
      {frame < cta.from ? <Captions frame={frame} /> : null}
      <Sequence from={cta.from}>
        <Cta />
      </Sequence>
    </AbsoluteFill>
  );
};
