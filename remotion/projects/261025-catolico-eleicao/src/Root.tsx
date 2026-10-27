import { Composition } from 'remotion';
import { Hook, HOOK_FRAMES } from './Hook';
import { Reel, REEL_FRAMES } from './Reel';

const video = { fps: 30, width: 1080, height: 1920 };

export const Root = () => (
  <>
    <Composition id="Reel" component={Reel} durationInFrames={REEL_FRAMES} {...video} />
    <Composition id="Hook" component={Hook} durationInFrames={HOOK_FRAMES} {...video} />
  </>
);
