# Third-party code and assets

## mutonby/openshorts (MIT)

https://github.com/mutonby/openshorts

Ported and adapted, not imported:

- `src/shorts/tracking.py`: dead zone and jump confirmation from `SmoothedCameraman`
  (`main.py`). The constant 3 px/frame pan was replaced by eased, speed-capped motion.
- `src/shorts/render.py`: the pattern of analysing at low resolution and driving the crop from
  ffmpeg `sendcmd`, so no frame passes through Python.
- `src/shorts/captions.py`: one ASS event per word with the active word highlighted.

MIT License, Copyright (c) mutonby. Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED.

## Anton font (SIL Open Font License 1.1)

`assets/fonts/Anton-Regular.ttf`, Copyright 2020 The Anton Project Authors
(https://github.com/googlefonts/AntonFont). License text in `assets/fonts/OFL.txt`.

## Detection models off the Mac (downloaded at first use, never in Git)

`src/shorts/detect_onnx.py` downloads both into the per-user model cache
(`%LOCALAPPDATA%\albatroz-shorts\models`, or `SHORTS_MODELS_DIR`) and checks the sha256 pinned there.

- YuNet face detector, `face_detection_yunet_2023mar.onnx`, from opencv/opencv_zoo
  (https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet), MIT License.
- YOLOX-S, `yolox_s.onnx` (release 0.1.1rc0), from Megvii-BaseDetection/YOLOX
  (https://github.com/Megvii-BaseDetection/YOLOX), Apache License 2.0. The decode of the raw
  output (grid and strides 8, 16, 32) follows its `demo/ONNXRuntime` example.

Left out on purpose: Ultralytics YOLO (AGPL-3.0) and the InsightFace/SCRFD weights (non-commercial).
