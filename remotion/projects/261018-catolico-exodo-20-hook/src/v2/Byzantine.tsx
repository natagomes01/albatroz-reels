import React from 'react';
import { AbsoluteFill, random } from 'remotion';
import { loadFont } from '@remotion/google-fonts/EBGaramond';

// Católico na Bíblia IDV v0 (catolico/_padroes/identidade-catolico-na-biblia.md): navy, aged gold,
// ivory and liturgical red, plus nearby tones of blue, red and gold for the fast cuts.
export const K = {
  navy: '#0F1F3D',
  field: '#182C52',
  deep: '#0A1530',
  blue: '#24427A',
  ivory: '#F3EBDC',
  ivorySoft: 'rgba(243, 235, 220, 0.72)',
  gold: '#B8963E',
  goldDeep: '#8C7020',
  goldLight: '#E0C87F',
  red: '#8B1E1E',
  redBright: '#B02A2A',
  wine: '#5E1A22',
};

export const { fontFamily: GARAMOND } = loadFont('normal', {
  weights: ['600', '700', '800'],
  subsets: ['latin', 'latin-ext'],
});

const svgUri = (svg: string) => `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;

// Tesserae: 12 px squares, 2 px joint, slight tone and rotation per piece (IDV 3, item 2).
const tesserae = (tones: string[], joint: string, seed: string, n = 10, cell = 14) => {
  let rects = '';
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const r = (k: string) => random(`${seed}-${x}-${y}-${k}`);
      const fill = tones[Math.floor(r('t') * tones.length)];
      const rot = (r('r') * 6 - 3).toFixed(1);
      const cx = x * cell + cell / 2;
      const cy = y * cell + cell / 2;
      rects += `<rect x="${x * cell + 1}" y="${y * cell + 1}" width="${cell - 2}" height="${cell - 2}" fill="${fill}" transform="rotate(${rot} ${cx} ${cy})"/>`;
    }
  }
  const s = n * cell;
  return svgUri(`<svg xmlns="http://www.w3.org/2000/svg" width="${s}" height="${s}"><rect width="${s}" height="${s}" fill="${joint}"/>${rects}</svg>`);
};

export const GOLD_TESSERAE = tesserae(['#B8963E', '#C9A54E', '#A8862F', '#E0C87F', '#9C7B2A', '#D4B565'], '#6B5418', 'gold');
export const FIELD_TESSERAE = tesserae(['#182C52', '#1C3260', '#15274A', '#1F3766', '#132343'], '#0A1530', 'field');
export const RED_TESSERAE = tesserae(['#8B1E1E', '#9A2424', '#7A1A1A', '#A52B2B', '#6E1717'], '#3E0E0E', 'red');

export const Tesserae: React.FC<{ pattern: string; opacity: number; size?: number }> = ({ pattern, opacity, size = 140 }) => (
  <AbsoluteFill style={{ backgroundImage: pattern, backgroundSize: `${size}px ${size}px`, opacity }} />
);

// Gold-mosaic lettering: the text is filled with gold tesserae.
export const Mosaic: React.FC<{ text: string; size: number; pattern?: string; style?: React.CSSProperties }> = ({
  text, size, pattern = GOLD_TESSERAE, style,
}) => (
  <div
    style={{
      fontFamily: GARAMOND,
      fontWeight: 800,
      fontSize: size,
      lineHeight: 0.92,
      whiteSpace: 'nowrap',
      backgroundImage: pattern,
      backgroundSize: `${Math.max(70, size / 5)}px ${Math.max(70, size / 5)}px`,
      WebkitBackgroundClip: 'text',
      backgroundClip: 'text',
      color: 'transparent',
      filter: `drop-shadow(${size / 40}px ${size / 40}px 0 ${K.deep})`,
      ...style,
    }}
  >
    {text}
  </div>
);

export const Serif: React.FC<{ text: string; size: number; color: string; weight?: number; style?: React.CSSProperties }> = ({
  text, size, color, weight = 700, style,
}) => (
  <div
    style={{
      fontFamily: GARAMOND,
      fontWeight: weight,
      fontSize: size,
      lineHeight: 0.95,
      color,
      whiteSpace: 'nowrap',
      textShadow: `0 ${size / 30}px ${size / 12}px rgba(10, 21, 48, 0.85), ${size / 45}px ${size / 45}px 0 ${K.deep}`,
      ...style,
    }}
  >
    {text}
  </div>
);

// Greek cross of equal arms, gold stroke (IDV 3, item 1).
const Cross: React.FC<{ x: number; y: number }> = ({ x, y }) => (
  <g transform={`translate(${x} ${y})`} stroke={K.gold} strokeWidth={2.5} fill="none">
    <path d="M -9 -3 H -3 V -9 H 3 V -3 H 9 V 3 H 3 V 9 H -3 V 3 H -9 Z" />
  </g>
);

// Double gold frame at 24 px with a cross at each corner; the signature of every IDV piece.
export const Frame: React.FC<{ opacity?: number }> = ({ opacity = 1 }) => (
  <AbsoluteFill style={{ opacity, pointerEvents: 'none' }}>
    <svg width={1080} height={1920}>
      <rect x={24} y={24} width={1032} height={1872} fill="none" stroke={K.gold} strokeWidth={3} />
      <rect x={36} y={36} width={1008} height={1848} fill="none" stroke={K.gold} strokeOpacity={0.6} strokeWidth={1.5} />
      <Cross x={30} y={30} />
      <Cross x={1050} y={30} />
      <Cross x={30} y={1890} />
      <Cross x={1050} y={1890} />
    </svg>
  </AbsoluteFill>
);

// Gold halo with short rays behind a number (IDV 3, item 4); stroke only, never filled.
export const Halo: React.FC<{ r: number; rays?: number; style?: React.CSSProperties; color?: string }> = ({
  r, rays = 16, style, color = K.gold,
}) => {
  const s = r * 2 + 120;
  const c = s / 2;
  return (
    <svg width={s} height={s} style={{ position: 'absolute', ...style }}>
      <circle cx={c} cy={c} r={r} fill="none" stroke={color} strokeWidth={6} />
      <circle cx={c} cy={c} r={r - 16} fill="none" stroke={color} strokeOpacity={0.5} strokeWidth={2} />
      {Array.from({ length: rays }, (_, i) => {
        const a = (i / rays) * Math.PI * 2;
        return (
          <line
            key={i}
            x1={c + Math.cos(a) * (r + 14)}
            y1={c + Math.sin(a) * (r + 14)}
            x2={c + Math.cos(a) * (r + 50)}
            y2={c + Math.sin(a) * (r + 50)}
            stroke={color}
            strokeWidth={5}
            strokeLinecap="round"
          />
        );
      })}
    </svg>
  );
};

// Liturgical-red ribbon with gold fillets (IDV 3, item 3).
export const Ribbon: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div
    style={{
      backgroundColor: K.red,
      backgroundImage: RED_TESSERAE,
      backgroundSize: '140px 140px',
      borderTop: `5px solid ${K.gold}`,
      borderBottom: `5px solid ${K.gold}`,
      padding: '14px 60px',
      ...style,
    }}
  >
    {children}
  </div>
);
