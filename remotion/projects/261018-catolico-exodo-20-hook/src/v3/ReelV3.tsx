import React from 'react';
import { Exodo20Hook, PaletteContext, type Palette } from '../Exodo20Hook';
import { EndCard, Reel } from '../Reel';

// V3: the v1 design (Anton, halftone, inked type, same cuts) in the tones of the Católico na Bíblia IDV
// (navy, liturgical red, aged gold, ivory; catolico/_padroes/identidade-catolico-na-biblia.md).
export const IDV_TONES: Palette = {
  black: '#0A1530', // deep navy: background and ink
  green: '#C9A54E', // gold: the main "20"
  purple: '#182C52', // field blue: card background
  yellow: '#E0C87F', // light gold
  red: '#B02A2A', // liturgical red, one step brighter for the cuts
  white: '#F3EBDC', // ivory
};

const withTones = (Inner: React.FC): React.FC => () => (
  <PaletteContext.Provider value={IDV_TONES}>
    <Inner />
  </PaletteContext.Provider>
);

export const ReelV3 = withTones(Reel);
export const HookV3 = withTones(Exodo20Hook);
export const EndCardV3 = withTones(EndCard);
