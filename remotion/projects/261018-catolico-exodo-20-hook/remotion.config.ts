import os from 'node:os';
import path from 'node:path';
import { Config } from '@remotion/cli/config';

Config.setEntryPoint('./src/index.ts');
Config.setVideoImageFormat('jpeg');
// Footage lives in the media root, never in Git.
Config.setPublicDir(path.join(os.homedir(), 'dev/albatroz-media/remotion/261018-catolico-exodo-20-hook'));
