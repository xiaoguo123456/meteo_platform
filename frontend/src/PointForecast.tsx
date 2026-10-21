import {useEffect,useRef,useState} from 'react';
import {fields} from './windMath';
type Point={time:string;value:number|null;min?:number|null;max?:number|null;direction?:number|null};
type Forecast={level:string;run_time:string;points:Point[];grid_longitude?:number;grid_latitude?:number;name?:string;cells?:number;nearest?:boolean;resolution?:number};
type Province={code:string;name:string};
export type ProvinceOutline={type:'Feature';properties:Province;geometry:unknown};
const time=(s:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',hour12:false}).format(new Date(s));
const read=async(url:string,signal?:AbortSignal)=>{const r=await fetch(url,{signal});const body=await r.json();if(!r.ok)throw new Error(body.detail||'读取失败');return body;};
// 省份目录和轮廓不随批次变化，整个页面共用一份。
let provinceList:Promise<Province[]>|null=null;const outlines=new Map<string,Promise<ProvinceOutline>>();
const listProvinces=()=>{provinceList??=read('/api/provinces').catch(e=>{provinceList=null;throw e;});return provinceList;};
const outline=(code:string)=>{let p=outlines.get(code);if(!p){p=read(`/api/provinces/${code}/outline`);outlines.set(code,p);p.catch(()=>outlines.delete(code));}return p;};
export default function PointForecast({point,model,run,available,province:selectedProvince,onProvince,onClose,onHighlight}:{point:[number,number];model:string;run:string;available:string[];province:string|null;onProvince:(code:string|null)=>void;onClose:()=>void;onHighlight:(outline:ProvinceOutline|null)=>void}){
 const [field,setField]=useState(available.includes('temperature')?'temperature':available[0]),[loaded,setLoaded]=useState<{url:string;data:Forecast}|null>(null),[failure,setFailure]=useState<{url:string;message:string}|null>(null),[hover,setHover]=useState<number|null>(null);
 const [located,setLocated]=useState<Province|null>(null),[provinces,setProvinces]=useState<Province[]>([]),[retry,setRetry]=useState(0);
 // 省份选择由上层持有，便于写入分享链接；首次定位不覆盖链接里恢复的省份。
 const provinceRef=useRef(selectedProvince);provinceRef.current=selectedProvince;const restored=useRef(!!selectedProvince);
 useEffect(()=>{if(!available.includes(field))setField(available[0]);},[available.join(','),field]);
 useEffect(()=>{void listProvinces().then(setProvinces).catch(()=>{});},[]);
 // 新点击位置所在省份：省平均模式下跟随切到该省，点到境外或海上则回到单点。
 useEffect(()=>{const abort=new AbortController();setLocated(null);
  read(`/api/provinces/locate?longitude=${point[0]}&latitude=${point[1]}`,abort.signal).then((value:Province|null)=>{setLocated(value);if(restored.current){restored.current=false;return;}if(provinceRef.current)onProvince(value?value.code:null);}).catch(()=>{if(!abort.signal.aborted&&provinceRef.current&&!restored.current)onProvince(null);});
  return()=>abort.abort();
 },[point]);
 const province=selectedProvince||'';
 useEffect(()=>{if(!province){onHighlight(null);return;}let active=true;outline(province).then(value=>{if(active)onHighlight(value);}).catch(()=>{if(active)onHighlight(null);});return()=>{active=false;};},[province]);
 useEffect(()=>()=>onHighlight(null),[]);
 const url=province?`/api/province-forecast/${model}?${new URLSearchParams({code:province,field,run_time:run})}`:`/api/point/${model}?${new URLSearchParams({longitude:String(point[0]),latitude:String(point[1]),field,run_time:run})}`;
 // 结果绑定请求地址：切换单点/省平均的同一帧里不能拿旧结构渲染新视图。
 const data=loaded?.url===url?loaded.data:null,error=failure?.url===url?failure.message:'';
 useEffect(()=>{const abort=new AbortController();setHover(null);let timer:ReturnType<typeof setTimeout>|undefined;
  read(url,abort.signal).then(body=>{setFailure(null);setLoaded({url,data:province?{...body,points:body.points.map((p:{time:string;mean:number|null;min:number|null;max:number|null;direction?:number|null})=>({time:p.time,value:p.mean,min:p.min,max:p.max,direction:p.direction}))}:body});}).catch(e=>{if(abort.signal.aborted)return;setFailure({url,message:e.message});
   // 升级后旧批次在后台补算省平均，稍后自动重试。
   if(e.message.includes('正在后台计算'))timer=setTimeout(()=>setRetry(v=>v+1),30000);});
  return()=>{abort.abort();clearTimeout(timer);};
 },[url,retry]);
 const spec=fields[field];if(!spec)return null;
 const finite=data?.points.flatMap(p=>[p.value,p.min,p.max]).filter((v):v is number=>v!=null)??[],lo=finite.length?Math.min(...finite):0,hi=finite.length?Math.max(...finite):1;
 const start=data?Date.parse(data.points[0].time):0,end=data?Date.parse(data.points[data.points.length-1].time):1;
 const x=(t:string)=>45+450*(Date.parse(t)-start)/Math.max(1,end-start),y=(v:number)=>140-110*(v-lo)/Math.max(1,hi-lo);
 let pen=false;const path=data?.points.map(p=>{if(p.value===null){pen=false;return '';}const d=`${pen?'L':'M'}${x(p.time)},${y(p.value)}`;pen=true;return d;}).join(' ');
 // 最高—最低范围按连续有值的时段分段闭合，缺测处断开。
 const band:string[]=[];let segment:Point[]=[];const flush=()=>{if(segment.length>1)band.push(`M${segment.map(p=>`${x(p.time)},${y(p.max!)}`).join('L')}L${[...segment].reverse().map(p=>`${x(p.time)},${y(p.min!)}`).join('L')}Z`);segment=[];};
 if(province)data?.points.forEach(p=>{if(p.min!=null&&p.max!=null)segment.push(p);else flush();});flush();
 const selected=hover!==null?data?.points[hover]:null;
 const value=(v:number|null|undefined)=>v==null?'缺测':`${v.toFixed(field==='precipitation'?2:1)} ${spec.unit}`;
 return <aside className="point-panel" role="dialog" aria-label={province?'省平均预报':'单点预报'}>
  <div className="point-heading"><strong>{province?`${data?.name||provinces.find(p=>p.code===province)?.name||''} · 全省平均`:`${point[0].toFixed(3)}°E / ${point[1].toFixed(3)}°N`}</strong><button aria-label="关闭预报面板" onClick={onClose}>×</button></div>
  {(located||province)&&<div className="point-scope"><div className="choice-row"><button className={`choice ${!province?'active':''}`} aria-pressed={!province} onClick={()=>onProvince(null)}>单点</button><button className={`choice ${province?'active':''}`} aria-pressed={!!province} onClick={()=>{if(located)onProvince(located.code);}}>{province?'省平均':`${located?.name}平均`}</button></div>
   {province&&provinces.length>0&&<select aria-label="选择省份" value={province} onChange={e=>onProvince(e.target.value)}>{provinces.map(p=><option key={p.code} value={p.code}>{p.name}</option>)}</select>}</div>}
  <div className="choice-row">{available.map(id=><button key={id} className={`choice ${id===field?'active':''}`} onClick={()=>setField(id)}>{fields[id].label}</button>)}</div>
  <div className="run-readout">{model.toUpperCase()} · 起报 {time(run)} · 北京时间</div>
  {error?<p role={error.includes('正在后台计算')?'status':'alert'}>{error}</p>:!data?<p role="status">{province?'正在读取省平均预报…':'正在读取单点预报…'}</p>:<>
   <div className="run-readout">{province?`${data.level} · ${data.nearest?'面积小于网格，取最近格点':`面积加权平均 · ${data.cells} 个格点（${data.resolution}°）`}`:`${data.level} · 最近网格 ${data.grid_longitude!.toFixed(3)}°, ${data.grid_latitude!.toFixed(3)}°`}</div>
   <svg viewBox="0 0 520 180" role="img" aria-label={`${spec.label}${province?'省平均':''}预报折线图`} onPointerMove={e=>{const rect=e.currentTarget.getBoundingClientRect(),t=start+((e.clientX-rect.left)/rect.width*520-45)/450*(end-start);let nearest=0;data.points.forEach((p,i)=>{if(Math.abs(Date.parse(p.time)-t)<Math.abs(Date.parse(data.points[nearest].time)-t))nearest=i;});setHover(nearest);}}>
    {[lo,(lo+hi)/2,hi].map((v,i)=><g key={i}><path d={`M45 ${y(v)}H495`} stroke="#dbe4e5"/><text x="1" y={y(v)+4} fontSize="11" fill="#52686c">{v.toFixed(1)}</text></g>)}
    {band.map((d,i)=><path key={i} d={d} fill="#127e87" fillOpacity=".14" stroke="none"/>)}
    <path d={path} stroke="#127e87" strokeWidth="2" fill="none"/>
    <text x="45" y="166" fontSize="11">{time(data.points[0].time)}</text><text x="495" y="166" textAnchor="end" fontSize="11">{time(data.points[data.points.length-1].time)}</text>
    {selected&&<path d={`M${x(selected.time)} 30V140`} stroke="#9fb4b8" strokeDasharray="3 3"/>}
    {selected&&selected.value!==null&&<circle cx={x(selected.time)} cy={y(selected.value)} r="4" fill="#127e87"/>}
   </svg>
   {province&&<div className="point-legend"><span><i className="line"/>省平均</span><span><i className="band"/>省内最低—最高</span></div>}
   <div className="run-readout">{selected?`${time(selected.time)} · ${province?`平均 ${value(selected.value)}（最低 ${value(selected.min)}，最高 ${value(selected.max)}）`:value(selected.value)}${selected.direction!=null?' · 风向 '+selected.direction.toFixed(0)+'°':''}`:`${lo.toFixed(1)}—${hi.toFixed(1)} ${spec.unit}`}</div>
  </>}
 </aside>;
}
