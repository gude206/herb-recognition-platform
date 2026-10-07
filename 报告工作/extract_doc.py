from pathlib import Path
import struct, json

source=Path(r'D:\Study\AI全栈开发\AI全栈开发实验1报告模板-2026-黄底红字请删除.doc')
b=source.read_bytes()
u16=lambda x,o: struct.unpack_from('<H',x,o)[0]
u32=lambda x,o: struct.unpack_from('<I',x,o)[0]
ss=1<<u16(b,30)
ms=1<<u16(b,32)
def sector(i): return b[(i+1)*ss:(i+2)*ss]
dif=list(struct.unpack_from('<109I',b,76))
dif=[x for x in dif if x<0xFFFFFFFA]
did=u32(b,68)
for _ in range(u32(b,72)):
    s=sector(did); dif.extend(struct.unpack_from('<'+str(ss//4-1)+'I',s,0)); did=u32(s,ss-4)
fat=[]
for i in dif[:u32(b,44)]: fat.extend(struct.unpack('<'+str(ss//4)+'I',sector(i)))
def chain(start,table):
    seen=set(); out=[]
    while start<0xFFFFFFFA:
        if start in seen: raise ValueError('FAT loop')
        seen.add(start); out.append(start); start=table[start]
    return out
def regular(start): return b''.join(sector(i) for i in chain(start,fat))
db=regular(u32(b,48)); entries=[]
for o in range(0,len(db),128):
    d=db[o:o+128]; nl=u16(d,64)
    if nl>0:
        entries.append({'name':d[:nl-2].decode('utf-16le'),'type':d[66],'start':u32(d,116),'size':struct.unpack_from('<Q',d,120)[0]})
root=next(x for x in entries if x['type']==5)
minidata=regular(root['start'])[:root['size']]
mfbytes=regular(u32(b,60)) if u32(b,64) else b''
minifat=list(struct.unpack('<'+str(len(mfbytes)//4)+'I',mfbytes))
def stream(name):
    e=next(x for x in entries if x['name']==name)
    if e['size']<u32(b,56): return b''.join(minidata[i*ms:(i+1)*ms] for i in chain(e['start'],minifat))[:e['size']]
    return regular(e['start'])[:e['size']]
w=stream('WordDocument'); t=stream('1Table' if u16(w,10)&512 else '0Table')
o=32; csw=u16(w,o); o+=2+csw*2; cslw=u16(w,o); o+=2+cslw*4; cf=u16(w,o); o+=2
fc,lcb=struct.unpack_from('<II',w,o+33*8)
clx=t[fc:fc+lcb]; pos=0
while clx[pos]==1: pos+=3+u16(clx,pos+1)
assert clx[pos]==2
pl=clx[pos+5:pos+5+u32(clx,pos+1)]; n=(len(pl)-4)//12
cps=struct.unpack_from('<'+str(n+1)+'I',pl,0); pcd=4*(n+1); chunks=[]
for i in range(n):
    f=u32(pl,pcd+i*8+2); count=cps[i+1]-cps[i]
    if f&0x40000000:
        f=(f&0x3FFFFFFF)//2; chunks.append(w[f:f+count].decode('cp1252',errors='replace'))
    else:
        chunks.append(w[f:f+count*2].decode('utf-16le',errors='replace'))
text=''.join(chunks)
out=source.parent/'报告工作'/'template-text.txt'; out.write_text(text,encoding='utf-8')
print(json.dumps(entries,ensure_ascii=False))
print(text)
