import numpy as np, sys
s=sys.argv[1]
a=np.fromfile(s+'/orig.raw',np.float32); b=np.fromfile(s+'/reac.raw',np.float32)[:8000*60]
from numpy.fft import rfft,irfft
# spectral-flux style: STFT magnitude in 300-3000 Hz, correlate per band summed
def spec(x,h=80,w=256):
    n=(len(x)-w)//h; idx=np.arange(w)[None,:]+h*np.arange(n)[:,None]
    m=np.abs(np.fft.rfft(x[idx]*np.hanning(w),axis=1))[:,10:96]
    m=np.log(m+1e-4); m-=m.mean(0); m/=m.std(0)+1e-6; return m
A,B=spec(a),spec(b)
for t0 in range(0,40,4):
    seg=A[t0*100:(t0+4)*100]
    best=None
    for j in range(0,len(B)-len(seg)):
        sc=(B[j:j+len(seg)]*seg).mean()
        if best is None or sc>best[1]: best=(j,sc)
    print('orig',t0,'-> reac',best[0]/100,'off',round(best[0]/100-t0,2),'score',round(best[1],3))
