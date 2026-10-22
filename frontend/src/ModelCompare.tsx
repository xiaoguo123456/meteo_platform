import {useEffect,useState} from 'react';
import {fields} from './windMath';
import {largestSpread,valueAt,type SeriesPoint} from './compareMath';
import {MODELS} from './share';
import {fetchJson} from './net';
const COLORS:Record<string,string>={gfs:'#127e87',grapes:'#c0612b',ifs:'#4f5fb0',aifs:'#9a5d74'};
const time=(s:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',hour12:false}).format(new Date(s));
type Result={model:string;state:'loading'|'ok'|'missing'|'empty'|'error';run?:string;level?:string;points:SeriesPoint[];message?:string};
// 起报清单绕过浏览器缓存（Cloudflare 规则会把浏览器缓存改成 4 小时）；统一限时与重试。
const read=(url:string,signal:AbortSignal)=>fetchJson(url,{signal,cache:'no-store'});
// 每个模型用自己最新的起报批次，分别读取单点或省平均，再按实际时刻画在同一张图上。
export default function ModelCompare({point,province,field}:{point:[number,number];province:string;field:string}){
 const [results,setResults]=useState<Result[]>([]),[hover,setHover]=useState<number|null>(null);
 useEffect(()=>{const abort=new AbortController();setHover(null);setResults(MODELS.map(model=>({model,state:'loading',points:[]})));
  const update=(value:Result)=>setResults(old=>old.map(item=>item.model===value.model?value:item));
  for(const model of MODELS)void(async()=>{
   try{
    const batch=await read(`/api/models/${model}/runs`,abort.signal);
    if(!batch.run_time||!batch.times?.length){update({model,state:'empty',points:[]});return;}
    if(!batch.field_times?.[field]?.length){update({model,state:'missing',points:[]});return;}
    const q=province?new URLSearchParams({code:province,field,run_time:batch.run_time}):new URLSearchParams({longitude:String(point[0]),latitude:String(point[1]),field,run_time:batch.run_time});
    const body=await read(province?`/api/province-forecast/${model}?${q}`:`/api/point/${model}?${q}`,abort.signal);
    update({model,state:'ok',run:batch.run_time,level:body.level,points:body.points.map((p:{time:string;value?:number|null;mean?:number|null})=>({time:p.time,value:province?p.mean??null:p.value??null}))});
   }catch(e){if(!abort.signal.aborted)update({model,state:'error',points:[],message:e instanceof Error?e.message:'读取失败'});}
  })();
  return()=>abort.abort();
 },[point,province,field]);
 const spec=fields[field];
 const ok=results.filter(r=>r.state==='ok'&&r.points.length);
 const all=ok.flatMap(r=>r.points);
 const finite=all.map(p=>p.value).filter((v):v is number=>v!=null),lo=finite.length?Math.min(...finite):0,hi=finite.length?Math.max(...finite):1;
 const stamps=all.map(p=>Date.parse(p.time)),start=stamps.length?Math.min(...stamps):0,end=stamps.length?Math.max(...stamps):1;
 const x=(t:number)=>45+450*(t-start)/Math.max(1,end-start),y=(v:number)=>140-110*(v-lo)/Math.max(1,hi-lo);
 const line=(points:SeriesPoint[])=>{let pen=false;return points.map(p=>{if(p.value==null){pen=false;return '';}const d=`${pen?'L':'M'}${x(Date.parse(p.time))},${y(p.value)}`;pen=true;return d;}).join(' ');};
 const spread=largestSpread(ok);
 const digits=field==='precipitation'?2:1;
 const hoverTime=hover;
 const pending=results.some(r=>r.state==='loading');
 return <div className="model-compare">
  {!ok.length?<p role="status">{pending?'正在读取四个模型…':'四个模型都没有该要素的可用预报'}</p>:<>
   <svg viewBox="0 0 520 180" role="img" aria-label={`${spec.label}四模型对比折线图`} onPointerMove={e=>{const rect=e.currentTarget.getBoundingClientRect();setHover(start+((e.clientX-rect.left)/rect.width*520-45)/450*(end-start));}} onPointerLeave={()=>setHover(null)}>
    {[lo,(lo+hi)/2,hi].map((v,i)=><g key={i}><path d={`M45 ${y(v)}H495`} stroke="#dbe4e5"/><text x="1" y={y(v)+4} fontSize="11" fill="#52686c">{v.toFixed(1)}</text></g>)}
    {ok.map(r=><path key={r.model} d={line(r.points)} stroke={COLORS[r.model]} strokeWidth="1.8" fill="none"/>)}
    <text x="45" y="166" fontSize="11">{time(new Date(start).toISOString())}</text><text x="495" y="166" textAnchor="end" fontSize="11">{time(new Date(end).toISOString())}</text>
    {hoverTime!=null&&<path d={`M${x(hoverTime)} 30V140`} stroke="#9fb4b8" strokeDasharray="3 3"/>}
    {hoverTime!=null&&ok.map(r=>{const v=valueAt(r.points,hoverTime);return v==null?null:<circle key={r.model} cx={x(hoverTime)} cy={y(v)} r="3.5" fill={COLORS[r.model]}/>;})}
   </svg>
   <ul className="compare-legend">{results.map(r=><li key={r.model}><i style={{background:COLORS[r.model]}}/><b>{r.model.toUpperCase()}</b>
    <span>{r.state==='ok'?`${r.level} · ${time(r.run!)} 起报${hoverTime!=null?` · ${valueAt(r.points,hoverTime)?.toFixed(digits)??'—'} ${spec.unit}`:''}`:r.state==='loading'?'读取中…':r.state==='missing'?'不提供该要素':r.state==='empty'?'暂无可用预报':r.message}</span></li>)}</ul>
   <div className="run-readout">{hoverTime!=null?`${time(new Date(hoverTime).toISOString())} · 各模型取最近一帧`:spread?`未来 24 小时 ${spread.models} 个模型最多相差 ${spread.spread.toFixed(digits)} ${spec.unit}（${time(spread.time)}）`:'模型时段不重叠，暂无法比较'}</div>
   {/* GFS 的风在 80m、温湿在 1000hPa，与其他模型的 10m/2m 不同层次。 */}
   {['wind','temperature','humidity'].includes(field)&&ok.some(r=>r.model==='gfs')&&<p className="compare-note">GFS 高度与其他模型不同，仅供参考</p>}
  </>}
 </div>;
}
