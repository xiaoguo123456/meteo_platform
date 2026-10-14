"""转换 CN-border-La.gmt 为只绘线的 GeoJSON；保留每个岛屿/线段。"""
import json
import math
import sys
from pathlib import Path


def simplify(points, tolerance=0.003):
    keep={0,len(points)-1};stack=[(0,len(points)-1)]
    while stack:
        a,b=stack.pop()
        if b-a<2:continue
        x,y=points[a];dx=points[b][0]-x;dy=points[b][1]-y;length=dx*dx+dy*dy
        best=-1;chosen=a
        for i in range(a+1,b):
            px,py=points[i];t=max(0,min(1,((px-x)*dx+(py-y)*dy)/length)) if length else 0
            distance=(px-x-t*dx)**2+(py-y-t*dy)**2
            if distance>best:best=distance;chosen=i
        if best>tolerance*tolerance:keep.add(chosen);stack.extend([(a,chosen),(chosen,b)])
    return [points[i] for i in sorted(keep)]


def convert(source):
    features=[];coords=[];props={};original=0
    def flush():
        if len(coords)>1:features.append({'type':'Feature','properties':dict(props),'geometry':{'type':'LineString','coordinates':simplify(coords)}})
    for line in source.splitlines():
        if line.startswith('>'):
            flush();coords=[];props={}
        elif line.startswith('# @D'):
            parts=line[4:].split('|')
            if len(parts)>=5:props={'name':parts[1],'code':parts[-1]}
        elif line and not line.startswith('#'):
            point=list(map(float,line.split()[:2]))
            if len(point)!=2 or not all(math.isfinite(v) for v in point):raise ValueError('边界坐标无效')
            coords.append(point);original+=1
    flush()
    return {'type':'FeatureCollection','features':features},original

if __name__=='__main__':
    result,count=convert(Path(sys.argv[1]).read_text());Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print('线段',len(result['features']),'原始点',count,'绘制点',sum(len(f['geometry']['coordinates']) for f in result['features']))
