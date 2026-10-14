import NewsPage from './NewsPage';
import SatellitePanel, {warmSatellite} from './SatellitePanel';
import type {EarthTexture} from './basemap';
import { useEffect, useState, useRef } from 'react';
import PointForecast from './PointForecast';
import WeatherGlobe from './WeatherGlobe';
import { ESRI_CREDIT } from './basemap';
import { cancelPendingFrames, loadFrame } from './frameLoader';
import type { Viewport } from './viewTiles';
import { fields, type Grid } from './windMath';

type Batch={model:string;run_time:string|null;times:string[];field_times?:Record<string,string[]>;total:number;state:string;error:string|null};
const formatTime=(iso:string|null|undefined)=>iso?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(iso)).replace(/\//g,'-'):'—';
function WeatherApp({satelliteMode}:{satelliteMode:boolean}) {
 const playbackWait=useRef(0);
 const [satellite,setSatellite]=useState<EarthTexture|null>(null);
 const [point,setPoint]=useState<[number,number]|null>(null);
 const [model,setModel]=useState('gfs'),[grid,setGrid]=useState<Grid|null>(null),[field,setField]=useState('wind'),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const [viewport,setViewport]=useState<Viewport|null>(null),[waiting,setWaiting]=useState(false);
 const [batch,setBatch]=useState<Batch|null>(null),[index,setIndex]=useState(0),[playing,setPlaying]=useState(false),[syncError,setSyncError]=useState('');
 useEffect(()=>{const timer=setTimeout(()=>void warmSatellite(),3000);return()=>clearTimeout(timer);},[]);
 useEffect(()=>{
  let active=true;const abort=new AbortController();setBatch(null);setIndex(0);setPlaying(false);setSyncError('');
  const poll=async()=>{try{
   const response=await fetch(`/api/models/${model}/runs`,{signal:abort.signal});const body=await response.json();
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
  if(!run||!valid){if(activeBatch?.state==='ready')setGrid(null);setLoading(false);return;}
  setLoading(true);const requestedAt=performance.now(),waitMs=playbackWait.current;playbackWait.current=0;
  loadFrame(model,field,run,valid,viewport,false,data=>{if(active)setGrid(data);}).then(data=>{if(active)setGrid({...data,meta:{...data.meta,requestedAt,waitMs}});}).catch(e=>{if(active){setError(e.message);setPlaying(false);}}).finally(()=>{if(active)setLoading(false);});
  return()=>{active=false;};
 },[model,field,run,valid,viewport,activeBatch?.state,satelliteMode]);
 // 只在视野或数据上下文变化时取消请求，播放推进不能打断后续帧预取。
 useEffect(()=>{setPlaying(false);setWaiting(false);return()=>cancelPendingFrames();},[viewport,model,field,run,satelliteMode]);
 useEffect(()=>{
  if(satelliteMode||!viewport||loading||!run||!grid||grid.meta.model!==model||grid.meta.field!==field)return;
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
 },[viewport,loading,grid,index,run,model,field,times.length,satelliteMode,playing,availableFields.join(',')]);
 useEffect(()=>{
  if(!playing||loading||!grid||!viewport||!run)return;
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
 },[playing,loading,grid,index,viewport,run,model,field,times.length,activeBatch?.state]);
 const spec=fields[grid?.meta.field||field];
 const ticks=Array.from({length:5},(_,i)=>spec.min+(spec.max-spec.min)*i/4);
 const gradient=`linear-gradient(90deg,${spec.colors.map(c=>`rgb(${c.slice(1).join(',')}) ${(c[0]-spec.min)/(spec.max-spec.min)*100}%`).join(',')})`;
 const time=formatTime(grid?.meta.valid_time);
 const status=error||syncError||(loading?'正在加载预报…':!times.length?(batch?.state==='ready'?'当前模型未提供该要素数据':'该要素正在提前缓存…'):'');

 return <div className="app-shell"><main className="weather-workspace">
  <WeatherGlobe onPoint={p=>{if(!satelliteMode)setPoint(p);}} satellite={satelliteMode?satellite:null} onViewChange={setViewport} grid={satelliteMode?null:grid} animated={!satelliteMode&&grid?.meta.field==='wind'}/>
  {!satelliteMode&&point&&run&&availableFields.length>0&&<PointForecast point={point} model={model} run={run} available={availableFields} onClose={()=>setPoint(null)}/>}

  {!satelliteMode&&status&&<div role="status" className={`load-status ${error||syncError?'error':''}`}>{status}</div>}
  {satelliteMode?<SatellitePanel onTexture={setSatellite}/>:<aside className="control-panel">
   <div className="control-line"><span className="control-key">模式</span><div className="choice-row">{['gfs','grapes','ifs','aifs'].map(m=><button key={m} className={`choice ${model===m?'active':''}`} onClick={()=>setModel(m)}>{m.toUpperCase()}</button>)}</div></div>
   <div className="control-line"><span className="control-key">要素</span><div className="choice-row">{Object.entries(fields).filter(([id])=>availableFields.includes(id)).map(([id,item])=><button key={id} className={`choice ${field===id?'active':''}`} onClick={()=>{setField(id);setIndex(0);setPlaying(false);}}>{item.label}</button>)}</div></div>
   {grid&&<div className="control-line"><span className="control-key">层次</span><span className="choice">{grid.meta.level}{grid.meta.field==='precipitation'&&grid.meta.interval_start?`（${formatTime(grid.meta.interval_start)}—${formatTime(grid.meta.valid_time)}）`:''}</span></div>}
   <div className="run-readout">起报 {formatTime(run)} · 北京时间{batch?.state==='syncing'&&<span>缓存 {batch.times.length}/{batch.total}</span>}</div>
   <div className="timeline"><button aria-label={playing?'暂停预报播放':'播放预报'} disabled={!activeBatch||times.length<2||!!error} onClick={()=>{if(playing){setPlaying(false);return;}if(index>=times.length-1)setIndex(0);setWaiting(false);setPlaying(true);}}>{playing?'Ⅱ':'▶'}</button><input aria-label="预报时间" type="range" min="0" max={Math.max(0,(times.length||1)-1)} value={index} disabled={!times.length} onChange={e=>{setPlaying(false);setIndex(Number(e.target.value));}}/></div>
   <div className="timeline-labels"><span>{formatTime(times[0])}</span><span>{formatTime(times[times.length-1])}</span></div>
   {playing&&<div className="run-readout">{waiting?'正在缓冲下一时刻…':`播放 ${index+1}/${times.length}`}</div>}
   <div className="panel-divider"/><div className="forecast-readout"><strong>{time}</strong><span>北京时间</span></div>
   {grid&&<div className="wind-legend"><div style={{background:gradient}}/>{ticks.map((n,i)=><span key={n} style={{position:'absolute',left:`${i*25}%`,transform:i===0?undefined:i===4?'translateX(-100%)':'translateX(-50%)'}}>{n}{i===4?` ${spec.unit}`:''}</span>)}</div>}

  </aside>}<div className="data-credit">{satelliteMode?'JMA · Himawari-9':`Open-Meteo S3 · ${grid?.meta.dx ?? (model==='grapes'?0.125:0.25)}°`} / <a href="https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9" target="_blank" rel="noreferrer">{ESRI_CREDIT}</a> · <a href="https://docs.gmt-china.org/latest/dataset/CN-border/" target="_blank" rel="noreferrer">省界：GMT / 全国地理信息资源目录服务系统</a></div>
 </main></div>;
}

export default function App(){
 const getMode=()=>location.hash.startsWith('#news')?'news':location.hash==='#satellite'?'satellite':'home';
 const [mode,setMode]=useState(getMode);
 useEffect(()=>{const changed=()=>setMode(getMode());addEventListener('hashchange',changed);return()=>removeEventListener('hashchange',changed);},[]);
 return <><header className="topbar"><span className="brand-name">晴川观象</span><nav aria-label="主导航">{[['home','首页'],['satellite','葵花卫星'],['news','资讯']].map(([id,title])=><button key={id} className={`nav-item ${mode===id?'nav-item-active':''}`} onClick={()=>{location.hash=id==='home'?'':id;setMode(id);}}>{title}</button>)}</nav></header>{mode==='news'?<NewsPage/>:<WeatherApp satelliteMode={mode==='satellite'}/>}</>;
}
