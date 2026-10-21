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

def signed_area(ring):
    return sum(x0*y1-x1*y0 for (x0,y0),(x1,y1) in zip(ring,ring[1:]))/2


def orient(polygon):
    """d3-geo 球面填色要求外环顺时针、洞逆时针（与 RFC 7946 相反），否则会填满整个地球。"""
    return [ring if (signed_area(ring)<0)==(i==0) else ring[::-1] for i,ring in enumerate(polygon)]


def convert_regions(source, tolerance=0.001):
    """按省级行政区合并 @P 外环与 @H 洞为 MultiPolygon，供省平均统计和选中高亮。"""
    regions={};current=None;ring=None
    for line in source.splitlines():
        if line.startswith('>'):
            ring=[]
        elif line.startswith('# @D'):
            parts=line[4:].split('|');current=None
            # 中朝共有为界河岛屿，不属于单一省份，不参与省平均。
            if len(parts)>=5 and parts[-1].strip().isdigit() and parts[1]!='中朝共有':
                current=regions.setdefault(parts[-1].strip(),{'name':parts[1],'polygons':[]})
        elif line.startswith('# @P') and current is not None:
            current['polygons'].append([ring])
        elif line.startswith('# @H') and current is not None and current['polygons']:
            current['polygons'][-1].append(ring)
        elif line and not line.startswith('#') and ring is not None:
            point=list(map(float,line.split()[:2]))
            if len(point)!=2 or not all(math.isfinite(v) for v in point):raise ValueError('边界坐标无效')
            ring.append(point)
    features=[]
    for code,region in sorted(regions.items()):
        polygons=[]
        for polygon in region['polygons']:
            rings=[simplify(r,tolerance) for r in polygon]
            # 简化后不足三角形的微小岛屿保留原始坐标，避免香港、澳门等被整体丢失。
            rings=[r if len(r)>=4 else polygon[i] for i,r in enumerate(rings)]
            rings=[[[round(x,4),round(y,4)] for x,y in r] for r in rings if len(r)>=4]
            if rings:polygons.append(orient(rings))
        features.append({'type':'Feature','properties':{'code':code,'name':region['name']},
                         'geometry':{'type':'MultiPolygon','coordinates':polygons}})
    return {'type':'FeatureCollection','features':features}

if __name__=='__main__':
    source=Path(sys.argv[1]).read_text()
    if len(sys.argv)>3:
        regions=convert_regions(source);Path(sys.argv[3]).write_text(json.dumps(regions,ensure_ascii=False,separators=(',',':')))
        print('省级面',len(regions['features']))
    if len(sys.argv)>4:
        # 首页按省填色只需显示精度，0.01 度容差减小下载体积；统计仍用上面的精细面。
        shapes=convert_regions(source,0.01);Path(sys.argv[4]).write_text(json.dumps(shapes,ensure_ascii=False,separators=(',',':')))
        print('填色面点数',sum(len(r) for f in shapes['features'] for p in f['geometry']['coordinates'] for r in p))
    result,count=convert(source);Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print('线段',len(result['features']),'原始点',count,'绘制点',sum(len(f['geometry']['coordinates']) for f in result['features']))
