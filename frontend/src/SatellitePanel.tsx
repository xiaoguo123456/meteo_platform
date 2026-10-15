import {useEffect,useState} from 'react';
import type {EarthTexture} from './basemap';
const cache=new Map<string,Promise<EarthTexture>>();
const iso=(s:string)=>`${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}T${s.slice(8,10)}:${s.slice(10,12)}:00Z`;
const label=(s:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(iso(s)));
type Product='truecolor'|'infrared';
const names={truecolor:'真彩色',infrared:'红外云图'};
type Catalog={times:string[];error?:string;stale?:boolean};
export type SatelliteSummary={id:string;name:string;category:string;country:string;operator:string;purpose:string;parent_id?:string;norad_id?:number|null;is_constellation?:boolean;is_constellation_member?:boolean;member_count?:number;position?:{longitude:number;latitude:number;altitude_km:number;velocity_km_s:number};track?:{longitude:number;latitude:number}[];orbit:{orbit_class:string;period_minutes:number;inclination_deg:number;altitude_km:number};};
export type SatelliteDetail=SatelliteSummary&{mission_summary:string;launch_date:string;cospar_id:string;norad_id:number|null;subcategories:string[];sources:{title:string;url:string;type:string}[];ai:{state:string;summary:string;confidence:string;points:string[];model:string|null;updated_at:string|null};track:{time:string;longitude:number;latitude:number;altitude_km:number;velocity_km_s:number}[]};
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
export function SatelliteObservationPanel({onTexture}:{onTexture:(texture:EarthTexture|null)=>void}){
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
 return <section className="satellite-module satellite-observation-module"><div className="satellite-section-heading"><div><span className="satellite-kicker">SATELLITE OBSERVATION</span><strong>葵花九号</strong></div><span>云图</span></div>
  <div className="control-line"><span className="control-label">云图</span>{(Object.keys(names) as Product[]).map(p=><button key={p} aria-pressed={product===p} className={product===p?'choice active':'choice'} onClick={()=>{if(p===product)return;setPlaying(false);setTimes([]);setSourceError('');setProduct(p);}}>{names[p]}</button>)}</div>
  {(error||sourceError)&&<p role="alert">{error||sourceError}</p>}
  {!times.length&&<p role="status">正在提前缓存卫星观测…</p>}
  <div className="timeline"><button aria-label={playing?'暂停卫星播放':'播放卫星观测'} disabled={times.length<2} onClick={()=>{if(!playing&&index===times.length-1)setSelected(times[0]);setPlaying(!playing);}}>{playing?'Ⅱ':'▶'}</button><input aria-label="卫星观测时间" type="range" min={0} max={Math.max(0,times.length-1)} value={Math.max(0,index)} disabled={!times.length} onChange={e=>{setPlaying(false);setSelected(times[Number(e.target.value)]);}}/></div>
  <div className="timeline-labels"><span>{times[0]?label(times[0]):'—'}</span><span>{times.length?label(times[times.length-1]):'—'}</span></div>
  <div className="forecast-readout"><strong>{shown?label(shown):'—'}</strong><span>北京时间</span></div>
  <div className="run-readout">JMA · {names[shownProduct]} · 观测</div>
 </section>;
}

export function SatelliteOrbitPanel({satellites=[],selectedId='',detail=null,onSelect}:{satellites?:SatelliteSummary[];selectedId?:string;detail?:SatelliteDetail|null;onSelect?:(id:string)=>void}){
 const [category,setCategory]=useState(''),[keyword,setKeyword]=useState(''),[expandedId,setExpandedId]=useState(''),[members,setMembers]=useState<SatelliteSummary[]>([]),[membersLoading,setMembersLoading]=useState(false);
 useEffect(()=>{if(!expandedId)return;let active=true;setMembers([]);setMembersLoading(true);fetch(`/api/satellites/${encodeURIComponent(expandedId)}/members?limit=80`).then(async r=>{if(!r.ok)throw new Error('星座成员读取失败');return r.json()}).then(body=>{if(active)setMembers(body.items||[])}).catch(()=>{if(active)setMembers([])}).finally(()=>{if(active)setMembersLoading(false)});return()=>{active=false;};},[expandedId]);
 const visibleSatellites=satellites.filter(item=>(!category||item.category===category)&&(!keyword||`${item.name}${item.purpose}${item.operator}`.toLowerCase().includes(keyword.toLowerCase())));
 const orbit=detail?.orbit;
 return <section className="satellite-module satellite-orbit-module"><div className="satellite-section-heading"><div><span className="satellite-kicker">ORBITAL CATALOG</span><strong>卫星轨迹</strong></div><span>{satellites.length} 个代表条目</span></div>
  <div className="satellite-filters"><input value={keyword} onChange={e=>setKeyword(e.target.value)} placeholder="搜索卫星" aria-label="搜索卫星"/><select value={category} onChange={e=>setCategory(e.target.value)} aria-label="卫星类型"><option value="">全部类型</option><option value="weather">气象</option><option value="earth-observation">地球遥感</option><option value="ocean">海洋观测</option><option value="communications">通信</option><option value="leo-internet">低轨互联网</option><option value="navigation">导航定位</option><option value="science">空间科学</option><option value="space-weather">空间天气</option><option value="geodesy">测绘地球物理</option><option value="crewed">载人航天</option><option value="search-rescue">搜救中继</option><option value="technology">技术验证</option><option value="amateur">教育业余无线电</option><option value="security">安全侦察</option></select></div>
  <div className="satellite-list" aria-label="卫星列表">{visibleSatellites.flatMap(item=>{const rows=[<button key={item.id} className={`satellite-list-item ${selectedId===item.id?'active':''}`} onClick={()=>{if(item.is_constellation){onSelect?.(item.id);setExpandedId(old=>old===item.id?'':item.id);}else onSelect?.(item.id);}}><span className="satellite-dot"/><span><strong>{item.name}</strong><small>{item.purpose} · {item.orbit.orbit_class}{item.is_constellation?` · ${item.member_count||'多'} 颗`:''}</small></span><em>{item.is_constellation?(expandedId===item.id?'−':'+'):'›'}</em></button>];if(item.is_constellation&&expandedId===item.id){if(membersLoading)rows.push(<div key={`${item.id}-loading`} className="satellite-member-loading">正在读取星座成员…</div>);for(const member of members)rows.push(<button key={member.id} className={`satellite-list-item satellite-member-item ${selectedId===member.id?'active':''}`} onClick={()=>onSelect?.(member.id)}><span className="satellite-dot"/><span><strong>{member.name}</strong><small>NORAD {member.norad_id??'代表轨道'} · {member.orbit.orbit_class}</small></span><em>›</em></button>);}return rows;})}</div>
  {detail&&<div className="satellite-detail"><div className="satellite-detail-head"><div><span className="satellite-kicker">SATELLITE PROFILE</span><h3>{detail.name}</h3></div><span className="satellite-category">{detail.purpose}</span></div><p className="satellite-summary">{detail.ai?.summary||detail.mission_summary}</p><div className="satellite-metrics"><span><b>{detail.position?.altitude_km?.toFixed(0)??'—'}</b> km 高度</span><span><b>{orbit?.inclination_deg?.toFixed(1)??'—'}°</b> 倾角</span><span><b>{orbit?.period_minutes?Math.round(orbit.period_minutes):'—'}</b> min 周期</span></div><div className="satellite-facts"><span>运营方</span><b>{detail.operator}</b><span>所属国家</span><b>{detail.country}</b><span>NORAD</span><b>{detail.norad_id??'星座条目'}</b><span>发射时间</span><b>{detail.launch_date||'—'}</b></div><div className="satellite-sources">{detail.sources?.slice(0,2).map(source=><a key={source.url} href={source.url} target="_blank" rel="noreferrer">{source.title} ↗</a>)}</div></div>}
 </section>;
}

export default function SatellitePanel({onTexture,satellites=[],selectedId='',detail=null,onSelect}:{onTexture:(texture:EarthTexture|null)=>void;satellites?:SatelliteSummary[];selectedId?:string;detail?:SatelliteDetail|null;onSelect?:(id:string)=>void}){
 return <div className="satellite-modules"><SatelliteObservationPanel onTexture={onTexture}/><SatelliteOrbitPanel satellites={satellites} selectedId={selectedId} detail={detail} onSelect={onSelect}/></div>;
}
