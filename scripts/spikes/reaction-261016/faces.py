import json, sys
from pathlib import Path
from shorts.vision import sample_frames, detect
from shorts.timeline import Span
src=Path(sys.argv[1]); out=[]
for t,buf,w,h in sample_frames(src, Span(0,41.92), fps=10, width=1080):
    bodies,faces=detect(buf,w,h,False,(1080,1920))
    out.append({"t":round(t,3),"faces":[[round(b.x),round(b.y),round(b.w),round(b.h)] for b in faces],
                "bodies":[[round(b.x),round(b.y),round(b.w),round(b.h)] for b in bodies]})
json.dump(out,open(sys.argv[2],"w"))
