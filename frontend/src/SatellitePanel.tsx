import {useEffect,useState} from 'react';
import type {EarthTexture} from './basemap';
const cache=new Map<string,Promise<EarthTexture>>();
const iso=(s:string)=>`${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}T${s.slice(8,10)}:${s.slice(10,12)}:00Z`;
const label=(s:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(iso(s)));
type Product='truecolor'|'infrared';
const names={truecolor:'真彩色',infrared:'红外云图'};
type Catalog={times:string[];error?:string;stale?:boolean};
const catalogs=new Map<Product,{expires:number;value:Promise<Catalog>}>();
function getCatalog(product:Product){
 const cached=catalogs.get(product);if(cached&&cached.expires>Date.now())return cached.value;
 const value=fetch(`/api/satellite/himawari/latest?product=${product}`).then(r=>{if(!r.ok)throw new Error('卫星清单读取失败');return r.json() as Promise<Catalog>;});
 catalogs.set(product,{expires:Date.now()+30000,value});value.catch(()=>catalogs.delete(product));return value;
}
function load(time:string,product:Product){
 const key=product+time;
 const old=cache.get(key);if(old)return old;
 const p=(async()=>{const r=await fetch(`/api/satellite/himawari/images/${product}/${time}.display.webp`);if(!r.ok)throw new Error('卫星云图缓存读取失败');const image=await createImageBitmap(await r.blob());const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;const ctx=canvas.getContext('2d')!;ctx.drawImage(image,0,0);image.close();return {width:canvas.width,height:canvas.height,pixels:ctx.getImageData(0,0,canvas.width,canvas.height).data};})();
 cache.set(key,p);p.catch(()=>cache.delete(key));while(cache.size>8)cache.delete(cache.keys().next().value!);return p;
}
// 首页空闲时准备最新真彩色，进入卫星页可直接复用解码结果。
export async function warmSatellite(){
 try{const v=await getCatalog('truecolor');const time=v.times[v.times.length-1];if(time)await load(time,'truecolor');const ir=await getCatalog('infrared');const t=ir.times[ir.times.length-1];if(t)await load(t,'infrared');}catch{/* 页面仍会显示实际加载错误。 */}
}
export default function SatellitePanel({onTexture}:{onTexture:(texture:EarthTexture|null)=>void}){
 const [product,setProduct]=useState<Product>('truecolor');
 const [shownProduct,setShownProduct]=useState<Product>('truecolor');
 const [times,setTimes]=useState<string[]>([]),[selected,setSelected]=useState(''),[shown,setShown]=useState(''),[playing,setPlaying]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState(''),[sourceError,setSourceError]=useState('');
 useEffect(()=>{let active=true;const poll=async()=>{try{const v=await getCatalog(product);if(active){setTimes(v.times);setSelected(old=>v.times.includes(old)?old:v.times[v.times.length-1]||'');setSourceError(v.error|| (v.stale?'卫星观测已过期':''));}}catch(e){if(active)setSourceError((e as Error).message);}};void poll();const timer=setInterval(poll,30000);return()=>{active=false;clearInterval(timer);};},[product]);
 useEffect(()=>()=>onTexture(null),[]);
 useEffect(()=>{if(!selected||!times.includes(selected))return;let active=true;setLoading(true);setError('');load(selected,product).then(t=>{if(active){onTexture(t);setShown(selected);setShownProduct(product);}}).catch(e=>{if(active){setError(e.message);setPlaying(false);}}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[selected,product,times.join(',')]);
 const index=times.indexOf(selected);
 useEffect(()=>{if(loading||index<0)return;let active=true;void(async()=>{
 const next=index===times.length-1?times.slice(0,3):times.slice(index+1,index+4);
 for(const time of next){if(!active)return;await load(time,product);}
 if(!active)return;
 const other:Product=product==='truecolor'?'infrared':'truecolor';
 const v=await getCatalog(other);if(!active)return;if(v.times.includes(selected))await load(selected,other);
 })().catch(()=>{});return()=>{active=false;};},[index,loading,product,times.join(',')]);
 useEffect(()=>{if(!playing||loading)return;if(index>=times.length-1){setPlaying(false);return;}const timer=setTimeout(()=>setSelected(times[index+1]),1000);return()=>clearTimeout(timer);},[playing,loading,index,times.join(',')]);
 return <aside className="control-panel"><div className="control-line"><strong>葵花 9 号</strong></div>
  <div className="control-line"><span className="control-label">云图</span>{(Object.keys(names) as Product[]).map(p=><button key={p} aria-pressed={product===p} className={product===p?'choice active':'choice'} onClick={()=>{if(p===product)return;setPlaying(false);setTimes([]);setSourceError('');setProduct(p);}}>{names[p]}</button>)}</div>
  {(error||sourceError)&&<p role="alert">{error||sourceError}</p>}
  {!times.length&&<p role="status">正在提前缓存卫星观测…</p>}
  <div className="timeline"><button aria-label={playing?'暂停卫星播放':'播放卫星观测'} disabled={times.length<2} onClick={()=>{if(!playing&&index===times.length-1)setSelected(times[0]);setPlaying(!playing);}}>{playing?'Ⅱ':'▶'}</button><input aria-label="卫星观测时间" type="range" min={0} max={Math.max(0,times.length-1)} value={Math.max(0,index)} disabled={!times.length} onChange={e=>{setPlaying(false);setSelected(times[Number(e.target.value)]);}}/></div>
  <div className="timeline-labels"><span>{times[0]?label(times[0]):'—'}</span><span>{times.length?label(times[times.length-1]):'—'}</span></div>
  <div className="forecast-readout"><strong>{shown?label(shown):'—'}</strong><span>北京时间</span></div>
  <div className="run-readout">JMA · {names[shownProduct]} · 观测</div>
 </aside>;
}
