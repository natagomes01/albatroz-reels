import { Composition } from 'remotion';
import { Exodo20Hook, HOOK_FRAMES } from './Exodo20Hook';
import { END_FRAMES, EndCard, Reel, REEL_FRAMES } from './Reel';
import { HookV2 } from './v2/HookV2';
import { EndCardV2, REEL_V2_FRAMES, ReelV2 } from './v2/ReelV2';
import { EndCardV3, HookV3, ReelV3 } from './v3/ReelV3';
import { ReelV4 } from './v4/ReelV4';
import { ReelV5 } from './v5/ReelV5';

const video = { fps: 30, width: 1080, height: 1920 };

export const Root = () => (
  <>
    <Composition id="Reel" component={Reel} durationInFrames={REEL_FRAMES} {...video} />
    <Composition id="Exodo20Hook" component={Exodo20Hook} durationInFrames={HOOK_FRAMES} {...video} />
    <Composition id="EndCard" component={EndCard} durationInFrames={END_FRAMES} {...video} />
    <Composition id="ReelV2" component={ReelV2} durationInFrames={REEL_V2_FRAMES} {...video} />
    <Composition id="HookV2" component={HookV2} durationInFrames={HOOK_FRAMES} {...video} />
    <Composition id="EndCardV2" component={EndCardV2} durationInFrames={END_FRAMES} {...video} />
    <Composition id="ReelV3" component={ReelV3} durationInFrames={REEL_FRAMES} {...video} />
    <Composition id="HookV3" component={HookV3} durationInFrames={HOOK_FRAMES} {...video} />
    <Composition id="EndCardV3" component={EndCardV3} durationInFrames={END_FRAMES} {...video} />
    <Composition id="ReelV4" component={ReelV4} durationInFrames={REEL_FRAMES} {...video} />
    <Composition id="ReelV5" component={ReelV5} durationInFrames={REEL_FRAMES} {...video} />
  </>
);
