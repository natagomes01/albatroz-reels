import json, subprocess, sys, numpy as np
FF="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
W, R, OUT = sys.argv[1:4]
def pcm(path, ss=0, t=None):
    a=[FF,"-v","error","-ss",str(ss)]+(["-t",str(t)] if t else [])+["-i",path,"-map","0:a:0","-ac","1","-ar","8000","-f","f32le","-"]
    return np.frombuffer(subprocess.run(a,capture_output=True).stdout,np.float32)
plan=json.load(open(W+"/plan.json"))
rows=[]; out=3.0
for a,b in plan["split"]:
    rows.append((out,a,"split")); out+=round((b-a)*30)/30
for a,b,k in plan["full"]:
    rows.append((out,a,k)); out+=round((b-a)*30)/30
rea=pcm(R)
for o,r,k in rows:
    if k in ("broll","cut") or True:
        pass
for o,r,k in rows:
    x=pcm(OUT,o+0.2,0.8)
    lo=int((r-1.0)*8000); hi=int((r+1.4)*8000)
    best=(0,-1)
    for j in range(lo,hi,8):
        seg=rea[j:j+len(x)]
        c=float(np.dot(seg,x)/(np.linalg.norm(seg)*np.linalg.norm(x)+1e-9))
        if c>best[1]: best=(j/8000,c)
    rms=20*np.log10(np.sqrt((x**2).mean())+1e-9)
    print(f"rms {rms:5.0f}dB out {o:7.2f} {k:6s} expect R {r+0.2:7.2f} found {best[0]:7.2f} err {1000*(best[0]-r-0.2):+5.0f} ms corr {best[1]:.2f}")
