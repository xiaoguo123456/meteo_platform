import { useEffect, useRef, useState } from 'react';
import { geoOrthographic, geoPath, geoGraticule10 } from 'd3-geo';
import type { Grid } from './windMath';
import { loadEarthTexture, type EarthTexture } from './basemap';
import type { Viewport } from './viewTiles';

export type SatelliteOverlay = {
 id:string;
 name:string;
 category:string;
 color:string;
 position:{longitude:number;latitude:number};
 track?:{longitude:number;latitude:number}[];
};

export default function WeatherGlobe({grid,animated,onViewChange,onPoint,satellite,satellites=[],selectedSatelliteId,onSatelliteClick}:{grid:Grid|null;satellite:EarthTexture|null;animated:boolean;onViewChange:(view:Viewport)=>void;onPoint:(point:[number,number])=>void;satellites?:SatelliteOverlay[];selectedSatelliteId?:string;onSatelliteClick?:(id:string)=>void}){
 const pointCallback=useRef(onPoint);pointCallback.current=onPoint;
 const satelliteCallback=useRef(onSatelliteClick);satelliteCallback.current=onSatelliteClick;
 const satellitesRef=useRef<SatelliteOverlay[]>(satellites);satellitesRef.current=satellites;
 const selectedSatelliteRef=useRef(selectedSatelliteId);selectedSatelliteRef.current=selectedSatelliteId;
 const redraw=useRef<()=>void>(()=>{});
 const [renderError,setRenderError]=useState('');
 const viewCallback=useRef(onViewChange);viewCallback.current=onViewChange;
 const updateSatellite=useRef<(value:EarthTexture|null)=>void>(()=>{});
 const updateGrid=useRef<(value:Grid|null)=>void>(()=>{});
 const host=useRef<HTMLDivElement>(null),base=useRef<HTMLCanvasElement>(null),lines=useRef<HTMLCanvasElement>(null),map=useRef<HTMLCanvasElement>(null);
 const view=useRef<{zoom:number;rotation:[number,number,number]}>({zoom:1,rotation:[-115,-12,0]});
 const enabled=useRef(animated);enabled.current=animated;
 useEffect(()=>{
  if(!host.current||!base.current||!lines.current||!map.current)return;
  setRenderError('');
  const container=host.current,bg=base.current,wind=lines.current,fg=map.current;
  const worker=new Worker(new URL('./wind.worker.ts',import.meta.url),{type:'module'});
  let width=0,height=0,radius=0,zoom=view.current.zoom,rotation:[number,number,number]=[...view.current.rotation],version=0,generation=0,busy=false,pending:any=null,vectors:Float32Array|null=null,frame=0,last=0,disposed=false;
  const dpr=Math.min(window.devicePixelRatio||1,2);
  const raster=document.createElement('canvas');
  let coast:any=null,provinces:any=null,displayed:any=null;
  let rebuildTimer:ReturnType<typeof setTimeout>;
  const ctx=wind.getContext('2d')!,bctx=bg.getContext('2d')!,mctx=fg.getContext('2d')!;
  worker.onerror=()=>setRenderError('风场渲染失败，请刷新页面重试');
  const samples:{model:string;field:string;time:string;totalMs:number;waitMs:number;buildMs:number}[]=[];
  let measuredFrames=0,measuredCost=0,measureStart=performance.now();
  let particles:{x:number;y:number;age:number}[]=[];
  const drawMap=()=>{if(!displayed)return;const {rotation,radius,field}=displayed;const projected=geoOrthographic().rotate(rotation).translate([width/2,height/2]).scale(radius).clipAngle(90);mctx.clearRect(0,0,width,height);const path=geoPath(projected,mctx);mctx.beginPath();path(geoGraticule10());mctx.strokeStyle=field&&field!=='wind'?'rgba(47,77,89,.13)':'rgba(174,191,238,.18)';mctx.lineWidth=.55;mctx.stroke();if(coast){mctx.beginPath();path(coast);mctx.strokeStyle=field&&field!=='wind'?'rgba(47,77,89,.5)':'rgba(187,205,255,.8)';mctx.lineWidth=.65;mctx.stroke();}if(provinces){mctx.beginPath();path(provinces);mctx.strokeStyle=field&&field!=='wind'?'rgba(35,61,67,.65)':'rgba(221,233,245,.8)';mctx.lineWidth=.7;mctx.stroke();}
   // 卫星轨迹绘制在边界之上；只渲染当前可见半球，避免轨迹“飘”在地球背面。
   const selectedSatellite=satellitesRef.current.find(item=>item.id===selectedSatelliteRef.current);
   if(selectedSatellite){
    const points=selectedSatellite.track||[];
    const frontPath=new Path2D();
    let frontDrawing=false,previousLongitude:number|undefined;
    for(const point of points){
     const xy=projected([point.longitude,point.latitude]);
     const crossesDateLine=previousLongitude!==undefined&&Math.abs(point.longitude-previousLongitude)>120;
     if(!xy||crossesDateLine){frontDrawing=false;previousLongitude=point.longitude;continue;}
     if(xy){
      if(!frontDrawing){frontPath.moveTo(xy[0],xy[1]);frontDrawing=true;}else frontPath.lineTo(xy[0],xy[1]);
     }
     previousLongitude=point.longitude;
    }
    mctx.strokeStyle=selectedSatellite.color;mctx.lineWidth=1.8;mctx.stroke(frontPath);
    const marker=projected([selectedSatellite.position.longitude,selectedSatellite.position.latitude]);if(marker){mctx.beginPath();mctx.arc(marker[0],marker[1],5,0,Math.PI*2);mctx.fillStyle=selectedSatellite.color;mctx.fill();mctx.strokeStyle='rgba(255,255,255,.95)';mctx.lineWidth=1.5;mctx.stroke();}
   }
   mctx.beginPath();mctx.arc(width/2,height/2,radius,0,2*Math.PI);mctx.strokeStyle='#718c92';mctx.stroke();};
  const submit=()=>{if(busy||!pending||disposed)return;busy=true;worker.postMessage(pending);pending=null;};
  let reported='';
  const report=()=>{const value={width,height,radius,rotation:[...rotation] as [number,number,number]},key=JSON.stringify(value);if(key!==reported){reported=key;viewCallback.current(value);}};
  const request=(coarse=false)=>{version++;vectors=null;radius=Math.min(width*.46,height*.46)*zoom;if(!coarse)report();pending={id:version,generation,width,height,radius,rotation:[...rotation],coarse};submit();};
  const rebuild=()=>{clearTimeout(rebuildTimer);request(true);rebuildTimer=setTimeout(()=>request(false),100);};
  const respawn=(p:{x:number;y:number;age:number})=>{for(let n=0;n<100;n++){p.x=Math.random()*width;p.y=Math.random()*height;if(vectors&&Number.isFinite(vectors[(Math.floor(p.y)*width+Math.floor(p.x))*3])){p.age=0;return;}}p.age=101;};
  worker.onmessage=({data})=>{
   busy=false;
   if(data.generation===generation&&data.width===width&&data.height===height){
    container.dataset.fieldBuildMs=String(Math.round(data.elapsed));container.dataset.basemap=data.hasBasemap?'esri':'loading';
    vectors=data.id===version?data.vectors:null;
    raster.width=data.width;raster.height=data.height;raster.getContext('2d')!.putImageData(new ImageData(data.pixels,data.width,data.height),0,0);
    // 新画面和边界在同一帧提交；计算过程中不清空上一帧。
    bctx.clearRect(0,0,width,height);bctx.save();bctx.beginPath();bctx.arc(width/2,height/2,data.radius,0,Math.PI*2);bctx.clip();bctx.imageSmoothingEnabled=true;bctx.filter=data.coarse?'blur(2px)':'none';bctx.drawImage(raster,0,0,width,height);bctx.restore();
    displayed=data;drawMap();ctx.clearRect(0,0,width,height);
    if(!data.coarse&&data.id===version&&data.meta?.complete&&data.meta.requestedAt){
     const entry={model:data.meta.model,field:data.field,time:data.meta.valid_time,totalMs:Math.round(performance.now()-data.meta.requestedAt+(data.meta.waitMs||0)),waitMs:Math.round(data.meta.waitMs||0),buildMs:Math.round(data.elapsed)};
     if(samples[samples.length-1]?.time!==entry.time||samples[samples.length-1]?.field!==entry.field||samples[samples.length-1]?.model!==entry.model){samples.push(entry);if(samples.length>120)samples.shift();}
     container.dataset.renderSamples=JSON.stringify(samples);
    }
    if(vectors)particles=Array.from({length:Math.round(Math.min(width,2*data.radius)*7)},()=>{const p={x:0,y:0,age:0};respawn(p);p.age=Math.floor(Math.random()*100);return p;});
   }
   submit();
  };
  updateSatellite.current=value=>{generation++;worker.postMessage({satellite:value});request();};
  updateGrid.current=value=>{generation++;worker.postMessage({grid:value});request();};
  const resize=()=>{
   const nextWidth=Math.max(1,Math.round(container.clientWidth)),nextHeight=Math.max(1,Math.round(container.clientHeight));
   if(nextWidth===width&&nextHeight===height)return;
   const previous=document.createElement('canvas');previous.width=bg.width;previous.height=bg.height;previous.getContext('2d')!.drawImage(bg,0,0);
   width=nextWidth;height=nextHeight;
   [bg,wind,fg].forEach(c=>{c.width=Math.round(width*dpr);c.height=Math.round(height*dpr);c.getContext('2d')!.setTransform(dpr,0,0,dpr,0,0);});
   bctx.drawImage(previous,0,0,width,height);rebuild();
  };
  loadEarthTexture().then(texture=>{if(disposed)return;worker.postMessage({texture});request();}).catch(()=>{if(!disposed)setRenderError('Esri 底图加载失败，请检查网络后刷新');});
  const observer=new ResizeObserver(resize);observer.observe(container);resize();
  // 只加载海岸线，不将未经核验的国界冒充正式中国边界。
  fetch('/coastline.geojson').then(r=>r.ok?r.json():null).then(c=>{if(!disposed){coast=c;drawMap();}}).catch(()=>{});
  fetch('/api/boundaries/provinces').then(r=>{if(!r.ok)throw new Error('省界读取失败');return r.json();}).then(c=>{if(!disposed){provinces=c;drawMap();}}).catch(()=>{if(!disposed)setRenderError('中国省界加载失败');});
  let drag:{x:number;y:number;r:[number,number,number]}|null=null;
  const down=(e:PointerEvent)=>{container.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY,r:[...rotation]};};
  const move=(e:PointerEvent)=>{if(!drag)return;rotation=[drag.r[0]+(e.clientX-drag.x)*.3,Math.max(-85,Math.min(85,drag.r[1]-(e.clientY-drag.y)*.3)),0];rebuild();};
  const up=(e:PointerEvent)=>{if(drag&&e.type==='pointerup'&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<5&&displayed){const rect=container.getBoundingClientRect(),px=e.clientX-rect.left,py=e.clientY-rect.top;if(Math.hypot(px-width/2,py-height/2)<=displayed.radius){const projected=geoOrthographic().rotate(displayed.rotation).translate([width/2,height/2]).scale(displayed.radius).clipAngle(90);let hit:string|undefined;let distance=14;for(const item of satellitesRef.current){const marker=projected([item.position.longitude,item.position.latitude]);if(!marker)continue;const d=Math.hypot(px-marker[0],py-marker[1]);if(d<distance){distance=d;hit=item.id;}}if(hit&&satelliteCallback.current){satelliteCallback.current(hit);}else{const p=projected.invert!([px,py]);if(p)pointCallback.current(p);}}}drag=null;clearTimeout(rebuildTimer);request();};const wheel=(e:WheelEvent)=>{e.preventDefault();zoom=Math.max(.65,Math.min(3,zoom*Math.exp(-e.deltaY*.001)));rebuild();};
  const keydown=(e:KeyboardEvent)=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-'].includes(e.key)){e.preventDefault();if(e.key==='ArrowLeft')rotation[0]-=8;if(e.key==='ArrowRight')rotation[0]+=8;if(e.key==='ArrowUp')rotation[1]=Math.min(85,rotation[1]+8);if(e.key==='ArrowDown')rotation[1]=Math.max(-85,rotation[1]-8);if(e.key==='+'||e.key==='=')zoom=Math.min(3,zoom*1.15);if(e.key==='-')zoom=Math.max(.65,zoom/1.15);rebuild();}};
  container.addEventListener('keydown',keydown);
  container.addEventListener('pointerdown',down);container.addEventListener('pointermove',move);container.addEventListener('pointerup',up);container.addEventListener('pointercancel',up);container.addEventListener('wheel',wheel,{passive:false});
  const tick=(now:number)=>{frame=requestAnimationFrame(tick);if(now-last<33)return;last=now;if(!enabled.current){ctx.clearRect(0,0,width,height);return;}if(!vectors||drag)return;
   const started=performance.now();
   ctx.globalCompositeOperation='destination-in';ctx.fillStyle='rgba(0,0,0,.96)';ctx.fillRect(0,0,width,height);ctx.globalCompositeOperation='source-over';
   const buckets:Array<number[]>=Array.from({length:8},()=>[]);
   for(const p of particles){if(p.age++>100)respawn(p);const i=(Math.floor(p.y)*width+Math.floor(p.x))*3;const u=vectors[i],v=vectors[i+1],s=vectors[i+2];if(!Number.isFinite(s)){p.age=101;continue;}const x=p.x+u,y=p.y+v,j=(Math.floor(y)*width+Math.floor(x))*3;if(x<0||x>=width||y<0||y>=height||!Number.isFinite(vectors[j])){p.age=101;continue;}buckets[Math.min(7,Math.floor(s/5))].push(p.x,p.y,x,y);p.x=x;p.y=y;}
   buckets.forEach((b,i)=>{ctx.beginPath();ctx.strokeStyle=`rgba(${160+i*10},${195+i*7},${195+i*7},.65)`;ctx.lineWidth=.8;for(let j=0;j<b.length;j+=4){ctx.moveTo(b[j],b[j+1]);ctx.lineTo(b[j+2],b[j+3]);}ctx.stroke();});
   measuredFrames++;measuredCost+=performance.now()-started;if(now-measureStart>=2000){container.dataset.fps=(measuredFrames*1000/(now-measureStart)).toFixed(1);container.dataset.frameCostMs=(measuredCost/measuredFrames).toFixed(2);measuredFrames=0;measuredCost=0;measureStart=now;}
  };frame=requestAnimationFrame(tick);
  redraw.current=drawMap;
  return()=>{view.current={zoom,rotation};disposed=true;redraw.current=()=>{};clearTimeout(rebuildTimer);cancelAnimationFrame(frame);worker.terminate();observer.disconnect();container.removeEventListener('keydown',keydown);container.removeEventListener('pointerdown',down);container.removeEventListener('pointermove',move);container.removeEventListener('pointerup',up);container.removeEventListener('pointercancel',up);container.removeEventListener('wheel',wheel);};
 },[]);
 useEffect(()=>{updateGrid.current(grid);},[grid]);
 useEffect(()=>{updateSatellite.current(satellite);},[satellite]);
 useEffect(()=>{satellitesRef.current=satellites;selectedSatelliteRef.current=selectedSatelliteId;redraw.current();},[satellites,selectedSatelliteId]);
 return <div className="weather-globe" ref={host} tabIndex={0} aria-label="地球视图，方向键旋转，加减键缩放"><canvas ref={base}/><canvas ref={lines}/><canvas ref={map}/>{renderError&&<div role="alert" className="load-status error">{renderError}</div>}</div>;
}
