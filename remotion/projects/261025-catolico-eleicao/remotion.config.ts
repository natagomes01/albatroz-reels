import os from 'node:os';
import path from 'node:path';
import { Config } from '@remotion/cli/config';

Config.setEntryPoint('./src/index.ts');
Config.setVideoImageFormat('jpeg');
// Footage lives in the media root, never in Git. CLI runs still need --public-dir (catolico-reel playbook).
Config.setPublicDir(path.join(os.homedir(), 'dev/albatroz-media/remotion/261025-catolico-eleicao'));
