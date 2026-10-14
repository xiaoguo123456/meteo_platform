import {useEffect,useState} from 'react';
import {fields} from './windMath';
type Forecast={level:string;run_time:string;grid_longitude:number;grid_latitude:number;points:{time:string;value:number|null;direction?:number|null}[]};
const time=(s:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',hour12:false}).format(new Date(s));
export default function PointForecast({point,model,run,available,onClose}:{point:[number,number];model:string;run:string;available:string[];onClose:()=>void}){
 const [field,setField]=useState(available.includes('temperature')?'temperature':available[0]),[data,setData]=useState<Forecast|null>(null),[error,setError]=useState(''),[hover,setHover]=useState<number|null>(null);
 useEffect(()=>{if(!available.includes(field))setField(available[0]);},[available.join(','),field]);
 useEffect(()=>{const abort=new AbortController();setData(null);setError('');setHover(null);
  const q=new URLSearchParams({longitude:String(point[0]),latitude:String(point[1]),field,run_time:run});
  fetch(`/api/point/${model}?${q}`,{signal:abort.signal}).then(async r=>{const body=await r.json();if(!r.ok)throw new Error(body.detail);return body;}).then(setData).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();
 },[point,model,run,field]);
 const spec=fields[field];if(!spec)return null;
 const finite=data?.points.filter(p=>p.value!==null).map(p=>p.value!)??[],lo=finite.length?Math.min(...finite):0,hi=finite.length?Math.max(...finite):1;
 const start=data?Date.parse(data.points[0].time):0,end=data?Date.parse(data.points[data.points.length-1].time):1;
 const x=(t:string)=>45+450*(Date.parse(t)-start)/Math.max(1,end-start),y=(v:number)=>140-110*(v-lo)/Math.max(1,hi-lo);
 let pen=false;const path=data?.points.map(p=>{if(p.value===null){pen=false;return '';}const d=`${pen?'L':'M'}${x(p.time)},${y(p.value)}`;pen=true;return d;}).join(' ');
 const selected=hover!==null?data?.points[hover]:null;
 return <aside className="point-panel" role="dialog" aria-label="单点预报">
  <div className="point-heading"><strong>{point[0].toFixed(3)}°E / {point[1].toFixed(3)}°N</strong><button aria-label="关闭单点预报" onClick={onClose}>×</button></div>
  <div className="choice-row">{available.map(id=><button key={id} className={`choice ${id===field?'active':''}`} onClick={()=>setField(id)}>{fields[id].label}</button>)}</div>
  <div className="run-readout">{model.toUpperCase()} · 起报 {time(run)} · 北京时间</div>
  {error?<p role="alert">{error}</p>:!data?<p role="status">正在读取单点预报…</p>:<>
   <div className="run-readout">{data.level} · 最近网格 {data.grid_longitude.toFixed(3)}°, {data.grid_latitude.toFixed(3)}°</div>
   <svg viewBox="0 0 520 180" role="img" aria-label={`${spec.label}预报折线图`} onPointerMove={e=>{const rect=e.currentTarget.getBoundingClientRect(),t=start+((e.clientX-rect.left)/rect.width*520-45)/450*(end-start);let nearest=0;data.points.forEach((p,i)=>{if(Math.abs(Date.parse(p.time)-t)<Math.abs(Date.parse(data.points[nearest].time)-t))nearest=i;});setHover(nearest);}}>
    {[lo,(lo+hi)/2,hi].map((v,i)=><g key={i}><path d={`M45 ${y(v)}H495`} stroke="#dbe4e5"/><text x="1" y={y(v)+4} fontSize="11" fill="#52686c">{v.toFixed(1)}</text></g>)}
    <path d={path} stroke="#127e87" strokeWidth="2" fill="none"/>
    <text x="45" y="166" fontSize="11">{time(data.points[0].time)}</text><text x="495" y="166" textAnchor="end" fontSize="11">{time(data.points[data.points.length-1].time)}</text>
    {selected&&selected.value!==null&&<circle cx={x(selected.time)} cy={y(selected.value)} r="4" fill="#127e87"/>}
   </svg>
   <div className="run-readout">{selected?`${time(selected.time)} · ${selected.value===null?'缺测':selected.value.toFixed(2)+' '+spec.unit}${selected.direction!=null?' · 风向 '+selected.direction.toFixed(0)+'°':''}`:`${lo.toFixed(1)}—${hi.toFixed(1)} ${spec.unit}`}</div>
  </>}
 </aside>;
}
