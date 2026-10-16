import NewsPage from './NewsPage';
import StationForecast from './StationForecast';
import {SatelliteObservationPanel, SatelliteOrbitPanel, warmSatellite, type SatelliteDetail, type SatelliteSummary} from './SatellitePanel';
import type {EarthTexture} from './basemap';
import { useEffect, useState, useRef } from 'react';
import PointForecast from './PointForecast';
import PowerOutlook from './PowerOutlook';
import WeatherGlobe from './WeatherGlobe';
import type { SatelliteOverlay } from './WeatherGlobe';
import { ESRI_CREDIT } from './basemap';
import { cancelPendingFrames, loadFrame } from './frameLoader';
import type { Viewport } from './viewTiles';
import { fields, type Grid } from './windMath';

type Batch={model:string;run_time:string|null;times:string[];field_times?:Record<string,string[]>;total:number;state:string;error:string|null};
type SatelliteMode='observation'|'orbit'|false;
const formatTime=(iso:string|null|undefined)=>iso?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(iso)).replace(/\//g,'-'):'—';
const localOrbitInput=()=>{const value=new Date();value.setSeconds(0,0);const offset=value.getTimezoneOffset();return new Date(value.getTime()-offset*60000).toISOString().slice(0,16);};
function WeatherApp({satelliteMode}:{satelliteMode:SatelliteMode}) {
 const playbackWait=useRef(0);
 const [satellite,setSatellite]=useState<EarthTexture|null>(null);
 const [point,setPoint]=useState<[number,number]|null>(null);
 const [model,setModel]=useState('gfs'),[grid,setGrid]=useState<Grid|null>(null),[field,setField]=useState('wind'),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const [viewport,setViewport]=useState<Viewport|null>(null),[waiting,setWaiting]=useState(false);
 const [batch,setBatch]=useState<Batch|null>(null),[index,setIndex]=useState(0),[playing,setPlaying]=useState(false),[syncError,setSyncError]=useState('');
 const [satellites,setSatellites]=useState<SatelliteSummary[]>([]),[selectedSatelliteId,setSelectedSatelliteId]=useState(''),[satelliteDetail,setSatelliteDetail]=useState<SatelliteDetail|null>(null);
 const [orbitAt,setOrbitAt]=useState(localOrbitInput),[orbitCount,setOrbitCount]=useState(3);
 const satelliteOrbitMode=satelliteMode==='orbit';
 const satelliteObservationMode=satelliteMode==='observation';
 // 卫星观测页才需要预热葵花纹理；首页切换天气要素时不再抢占同一条连接。
 useEffect(()=>{if(!satelliteObservationMode)return;const timer=setTimeout(()=>void warmSatellite(),3000);return()=>clearTimeout(timer);},[satelliteObservationMode]);
 useEffect(()=>{if(!satelliteOrbitMode)return;let active=true;const abort=new AbortController();fetch('/api/satellites?limit=120',{signal:abort.signal}).then(async r=>{if(!r.ok)throw new Error('卫星目录读取失败');return r.json()}).then(body=>{if(active){setSatellites(body.items||[]);if(!selectedSatelliteId&&body.items?.[0])setSelectedSatelliteId(body.items[0].id);}}).catch(()=>{});return()=>{active=false;abort.abort();};},[satelliteOrbitMode]);
 useEffect(()=>{if(!satelliteOrbitMode||!selectedSatelliteId)return;let active=true;const abort=new AbortController();const params=new URLSearchParams({orbits:String(orbitCount)});if(orbitAt){const parsed=new Date(orbitAt);if(!Number.isNaN(parsed.getTime()))params.set('at',parsed.toISOString());}const read=()=>fetch(`/api/satellites/${encodeURIComponent(selectedSatelliteId)}?${params}`,{signal:abort.signal}).then(async r=>{if(!r.ok)throw new Error('卫星资料读取失败');return r.json()}).then(value=>{if(active)setSatelliteDetail(value)}).catch(()=>{if(active)setSatelliteDetail(null)});void read();const timer=setInterval(()=>void read(),30000);return()=>{active=false;abort.abort();clearInterval(timer);};},[satelliteOrbitMode,selectedSatelliteId,orbitAt,orbitCount]);
 useEffect(()=>{
  let active=true;const abort=new AbortController();setBatch(null);setIndex(0);setPlaying(false);setSyncError('');
  const poll=async()=>{try{
   const response=await fetch(`/api/models/${model}/runs`,{signal:abort.signal,cache:'default'});const body=await response.json();
   if(!response.ok)throw new Error(body.detail);
   if(active){setBatch(previous=>{if(previous?.run_time!==body.run_time){setIndex(0);setPlaying(false);}return body;});setSyncError(body.error||'');}
  }catch(e){if(active)setSyncError(e instanceof Error?e.message:'起报清单读取失败');}};
  void poll();const timer=setInterval(poll,10000);return()=>{active=false;abort.abort();clearInterval(timer);};
 },[model]);
 const activeBatch=batch?.model===model?batch:null;
 const times=activeBatch?.field_times?.[field] ?? activeBatch?.times ?? [];
 const availableFields=Object.keys(fields).filter(id=>(activeBatch?.field_times?.[id]?.length??0)>0);
 useEffect(()=>{if(availableFields.length&&!availableFields.includes(field)){setField(availableFields[0]);setIndex(0);}},[field,availableFields.join(',')]);
 const run=activeBatch?.run_time, valid=times[index];
 useEffect(()=>{
  let active=true;setError('');
  if(satelliteMode||!viewport)return;
  if(!run||!valid){setGrid(null);setLoading(false);return;}
  setLoading(true);
  // 切换模型、要素或预报时刻时，不继续显示上一份数据，避免看起来像切换完成。
  setGrid(previous=>previous&&previous.meta.model===model&&previous.meta.field===field&&previous.meta.valid_time===valid?previous:null);
  const requestedAt=performance.now(),waitMs=playbackWait.current;playbackWait.current=0;
  // 只有完整帧才进入渲染和预取队列。逐块回调会让粒子、色带和预取任务反复重建，
  // 在全球视野下会把一次请求放大成多轮请求，是切换变慢的主要原因。
  loadFrame(model,field,run,valid,viewport,false).then(data=>{if(active)setGrid({...data,meta:{...data.meta,requestedAt,waitMs}});}).catch(e=>{if(active){setError(e.message);setPlaying(false);}}).finally(()=>{if(active)setLoading(false);});
  return()=>{active=false;};
 },[model,field,run,valid,viewport,activeBatch?.state,satelliteMode]);
 // 只在视野或数据上下文变化时取消请求，播放推进不能打断后续帧预取。
 useEffect(()=>{setPlaying(false);setWaiting(false);return()=>cancelPendingFrames();},[viewport,model,field,run,satelliteMode]);
 useEffect(()=>{
  if(satelliteMode||!viewport||loading||!run||!grid||!grid.meta.complete||grid.meta.model!==model||grid.meta.field!==field||grid.meta.valid_time!==valid)return;
  let active=true;
  const timer=setTimeout(()=>{void(async()=>{
   const ahead=times.slice(index+1,index+7).map(time=>({field,time}));
   // 静止浏览时提前备好其他要素的首帧；播放时把带宽留给后续时刻。
   const alternatives=playing?[]:availableFields.filter(id=>id!==field).map(id=>({field:id,time:activeBatch?.field_times?.[id]?.[0]})).filter(item=>item.time);
   const queue=[...ahead.slice(0,1),...alternatives,...ahead.slice(1)];
   let cursor=0;
   const consume=async()=>{while(active&&cursor<queue.length){
    const item=queue[cursor++];
    await loadFrame(model,item.field,run,item.time!,viewport,true);
   }};
   await Promise.all([consume(),consume()]);
  })().catch(()=>{/* 预取失败由前台读取时显示，不能填充替代数据。 */});},100);
  return()=>{active=false;clearTimeout(timer);};
 },[viewport,loading,grid,index,run,valid,model,field,times.length,satelliteMode,playing,availableFields.join(',')]);
 useEffect(()=>{
  if(!playing||loading||!grid||!grid.meta.complete||grid.meta.valid_time!==valid||!viewport||!run)return;
  if(index>=times.length-1){
   if(activeBatch?.state==='ready')setPlaying(false);
   else setWaiting(true);
   return;
  }
  let active=true;
  const timer=setTimeout(()=>{
   setWaiting(true);const waitStarted=performance.now();
   void loadFrame(model,field,run,times[index+1],viewport,true).then(()=>{
    if(active){playbackWait.current=performance.now()-waitStarted;setWaiting(false);setIndex(index+1);}
   }).catch(e=>{if(active){setError(e.message);setPlaying(false);setWaiting(false);}});
  },1500);
  return()=>{active=false;clearTimeout(timer);};
 },[playing,loading,grid,index,valid,viewport,run,model,field,times.length,activeBatch?.state]);
 const spec=fields[grid?.meta.field||field];
 const ticks=Array.from({length:5},(_,i)=>spec.min+(spec.max-spec.min)*i/4);
 const gradient=`linear-gradient(90deg,${spec.colors.map(c=>`rgb(${c.slice(1).join(',')}) ${(c[0]-spec.min)/(spec.max-spec.min)*100}%`).join(',')})`;
 const time=formatTime(grid?.meta.valid_time);
 const status=error||syncError||(loading?'正在加载预报…':!times.length?(batch?.state==='ready'?'当前模型未提供该要素数据':'该要素正在提前缓存…'):'');
 const satelliteOverlays:SatelliteOverlay[]=satellites.map(item=>({id:item.id,name:item.name,category:item.category,color:item.id===selectedSatelliteId?'#d97745':'#2f7f83',position:item.position?{longitude:item.position.longitude,latitude:item.position.latitude}:{longitude:0,latitude:0},track:item.track}));
 if(satelliteDetail){const track=(satelliteDetail.track||[]).map(point=>({longitude:point.longitude,latitude:point.latitude}));const overlay=satelliteOverlays.find(item=>item.id===satelliteDetail.id);if(overlay){overlay.track=track;overlay.position={longitude:satelliteDetail.position?.longitude??overlay.position.longitude,latitude:satelliteDetail.position?.latitude??overlay.position.latitude};}else{satelliteOverlays.push({id:satelliteDetail.id,name:satelliteDetail.name,category:satelliteDetail.category,color:'#d97745',position:{longitude:satelliteDetail.position?.longitude??0,latitude:satelliteDetail.position?.latitude??0},track});}}

 return <div className="app-shell"><main className="weather-workspace">
  <WeatherGlobe onPoint={p=>{if(!satelliteMode)setPoint(p);}} satellite={satelliteObservationMode?satellite:null} onViewChange={setViewport} grid={satelliteMode?null:grid} animated={!satelliteMode&&grid?.meta.field==='wind'} satellites={satelliteOrbitMode?satelliteOverlays:[]} selectedSatelliteId={satelliteOrbitMode?selectedSatelliteId:undefined} onSatelliteClick={satelliteOrbitMode?setSelectedSatelliteId:undefined}/>
  {!satelliteMode&&point&&run&&availableFields.length>0&&<PointForecast point={point} model={model} run={run} available={availableFields} onClose={()=>setPoint(null)}/>}

  {!satelliteMode&&status&&<div role="status" className={`load-status ${error||syncError?'error':''}`}>{status}</div>}
  {satelliteObservationMode?<div className="satellite-modules"><SatelliteObservationPanel onTexture={setSatellite}/></div>:satelliteOrbitMode?<div className="satellite-modules"><SatelliteOrbitPanel satellites={satellites} selectedId={selectedSatelliteId} detail={satelliteDetail} onSelect={setSelectedSatelliteId} orbitAt={orbitAt} orbitCount={orbitCount} onOrbitAtChange={setOrbitAt} onOrbitCountChange={setOrbitCount}/></div>:<aside className="control-panel">
   <div className="control-line"><span className="control-key">模式</span><div className="choice-row">{['gfs','grapes','ifs','aifs'].map(m=><button key={m} className={`choice ${model===m?'active':''}`} onClick={()=>setModel(m)}>{m.toUpperCase()}</button>)}</div></div>
   <div className="control-line"><span className="control-key">要素</span><div className="choice-row">{Object.entries(fields).filter(([id])=>availableFields.includes(id)).map(([id,item])=><button key={id} className={`choice ${field===id?'active':''}`} onClick={()=>{setField(id);setIndex(0);setPlaying(false);}}>{item.label}</button>)}</div></div>
   {grid&&<div className="control-line"><span className="control-key">层次</span><span className="choice">{grid.meta.level}{grid.meta.field==='precipitation'&&grid.meta.interval_start?`（${formatTime(grid.meta.interval_start)}—${formatTime(grid.meta.valid_time)}）`:''}</span></div>}
   <div className="run-readout">起报 {formatTime(run)} · 北京时间{batch?.state==='syncing'&&<span>缓存 {batch.times.length}/{batch.total}</span>}</div>
   <div className="timeline"><button aria-label={playing?'暂停预报播放':'播放预报'} disabled={!activeBatch||times.length<2||!!error} onClick={()=>{if(playing){setPlaying(false);return;}if(index>=times.length-1)setIndex(0);setWaiting(false);setPlaying(true);}}>{playing?'Ⅱ':'▶'}</button><input aria-label="预报时间" type="range" min="0" max={Math.max(0,(times.length||1)-1)} value={index} disabled={!times.length} onChange={e=>{setPlaying(false);setIndex(Number(e.target.value));}}/></div>
   <div className="timeline-labels"><span>{formatTime(times[0])}</span><span>{formatTime(times[times.length-1])}</span></div>
   <div className="panel-divider"/><div className="forecast-readout"><strong>{time}</strong><span>北京时间</span></div>
   {grid&&<div className="wind-legend"><div style={{background:gradient}}/>{ticks.map((n,i)=><span key={n} style={{position:'absolute',left:`${i*25}%`,transform:i===0?undefined:i===4?'translateX(-100%)':'translateX(-50%)'}}>{n}{i===4?` ${spec.unit}`:''}</span>)}</div>}

 </aside>}<div className="data-credit">{satelliteObservationMode?'JMA · Himawari-9':satelliteOrbitMode?'CelesTrak 轨道参数':`Open-Meteo S3 · ${grid?.meta.dx ?? (model==='grapes'?0.125:0.25)}°`} / <a href="https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9" target="_blank" rel="noreferrer">{ESRI_CREDIT}</a> · <a href="https://docs.gmt-china.org/latest/dataset/CN-border/" target="_blank" rel="noreferrer">省界：GMT / 全国地理信息资源目录服务系统</a></div>
 </main></div>;
}

export default function App(){
 const getMode=()=>location.hash.startsWith('#news')?'news':location.hash==='#outlook'?'outlook':location.hash==='#station'?'station':location.hash==='#satellite'?'satellite':location.hash==='#observation'?'observation':'home';
 const [mode,setMode]=useState(getMode);
 useEffect(()=>{const changed=()=>setMode(getMode());addEventListener('hashchange',changed);return()=>removeEventListener('hashchange',changed);},[]);
 return <><header className="topbar"><span className="brand-name">晴川观象</span><nav aria-label="主导航">{[['home','首页'],['observation','葵花卫星'],['satellite','卫星轨迹'],['station','站点预测'],['outlook','新能源态势'],['news','资讯']].map(([id,title])=><button key={id} className={`nav-item ${mode===id?'nav-item-active':''}`} onClick={()=>{location.hash=id==='home'?'':id;setMode(id);}}>{title}</button>)}</nav></header>{mode==='news'?<NewsPage/>:mode==='outlook'?<PowerOutlook/>:mode==='station'?<StationForecast/>:<WeatherApp satelliteMode={mode==='satellite'?'orbit':mode==='observation'?'observation':false}/>}</>;
}
