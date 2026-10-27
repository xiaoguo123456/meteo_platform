import {useEffect,useMemo,useRef,useState} from 'react';
import type {KeyboardEvent,PointerEvent} from 'react';
import './price.css';
import {fetchJson} from './net';

type Slot={start:number;end:number;label:string;day_ahead:number|null;real_time:number|null};
type Province={area_code:string;name:string;basis:'end'|'start';points:number;resolution:number[];fetched_at:string;slots:Slot[]};
type Average={area_code:string;area_name:string;day_ahead:number|null;real_time:number|null;solar_mechanism_price:number|null;wind_mechanism_price:number|null};
type Day={date:string;is_today:boolean;provinces:Province[];averages:Average[]};
type Status={state:'valid'|'expired'|'missing'|'error'|'unchecked';message:string;checked_at:string|null;token_updated_at:string|null;issued_at:string|null;estimated_expire_at:string|null;last_data_at:string|null;next_run_at:string|null};
type DateItem={date:string;has_curve:boolean;has_average:boolean};

const COLORS={day_ahead:'#27787b',real_time:'#c6904c'};
const STATE_TEXT:Record<Status['state'],string>={valid:'数据源正常',expired:'token 已失效',missing:'未配置 token',error:'上游请求异常',unchecked:'待检查'};
const price=(v:number|null|undefined)=>v==null?'—':v.toFixed(1);
const clock=(iso:string|null|undefined)=>iso?new Intl.DateTimeFormat('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Shanghai'}).format(new Date(iso)):'—';
const dayName=(s:string)=>new Intl.DateTimeFormat('zh-CN',{month:'numeric',day:'numeric',weekday:'short',timeZone:'Asia/Shanghai'}).format(new Date(`${s}T00:00:00+08:00`));
// 按时段时长加权：重庆等省份 5 分钟和 15 分钟的点混在一起，简单平均会偏向 5 分钟时段。
const mean=(slots:Slot[],key:'day_ahead'|'real_time')=>{let sum=0,weight=0;for(const s of slots){const v=s[key];if(v==null)continue;sum+=v*(s.end-s.start);weight+=s.end-s.start;}return weight?sum/weight:null;};
const DEFAULT_AREA='320000000000';

function niceTicks(lo:number,hi:number,count=5){
  // 全天同一个价（如黑龙江整天 0 元）时没有跨度，按 100 元撑开纵轴。
  if(hi-lo<1e-6)hi=lo+100;
  const raw=(hi-lo)/count,unit=10**Math.floor(Math.log10(Math.max(raw,1e-6)));
  const step=[1,2,2.5,5,10].map(m=>m*unit).find(s=>s>=raw)??unit*10;
  // 首尾刻度向外取整，保证曲线完整落在刻度范围内。
  const ticks=[];for(let v=Math.floor(lo/step)*step;;v+=step){ticks.push(Math.round(v*100)/100);if(v>=hi-step*.001)break;}
  return ticks;
}

function PriceChart({province}:{province:Province}){
  const slots=province.slots;
  const [hover,setHover]=useState<number|null>(null);
  useEffect(()=>setHover(null),[province.area_code]);
  const values=slots.flatMap(s=>[s.day_ahead,s.real_time]).filter((v):v is number=>v!=null);
  if(!values.length)return <div className="price-chart-empty">这一天没有价格数据</div>;
  const ticks=niceTicks(Math.min(0,...values),Math.max(...values));
  const lo=ticks[0],hi=ticks[ticks.length-1],range=Math.max(hi-lo,1e-6);
  // 横轴按时段结束时刻 0–24 时摆放，不同省份点数不同也能对齐。
  const x=(end:number)=>end/1440*100,y=(v:number)=>100-(v-lo)/range*100;
  const path=(key:'day_ahead'|'real_time')=>{let d='',open=false;for(const s of slots){const v=s[key];if(v==null){open=false;continue;}d+=`${open?'L':'M'}${x(s.end).toFixed(2)},${y(v).toFixed(2)} `;open=true;}return d.trim();};
  const pick=(event:PointerEvent<HTMLDivElement>)=>{const rect=event.currentTarget.getBoundingClientRect();const minute=(event.clientX-rect.left)/rect.width*1440;let best=0;slots.forEach((s,i)=>{if(Math.abs(s.end-minute)<Math.abs(slots[best].end-minute))best=i;});setHover(best);};
  const active=hover==null?null:slots[hover];
  return <div className="price-chart">
    <div className="price-chart-y">{ticks.map(t=><span key={t} style={{top:`${y(t)}%`}}>{t}</span>)}</div>
    <div className="price-chart-plot" onPointerMove={pick} onPointerDown={pick} onPointerLeave={()=>setHover(null)}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label={`${province.name}出清电价曲线`}>
        {ticks.map(t=><path key={t} d={`M0 ${y(t)}H100`} className={t===0?'price-zero':'price-grid'} vectorEffect="non-scaling-stroke"/>)}
        <path d={path('day_ahead')} stroke={COLORS.day_ahead} className="price-line" vectorEffect="non-scaling-stroke"/>
        <path d={path('real_time')} stroke={COLORS.real_time} className="price-line" vectorEffect="non-scaling-stroke"/>
      </svg>
      {active&&<>
        <span className="price-guide" style={{left:`${x(active.end)}%`}}/>
        <div className="price-tip" style={{left:`${x(active.end)}%`,transform:`translateX(${x(active.end)>75?'-100%':x(active.end)<25?'0':'-50%'})`}}>
          <strong>{String(Math.floor(active.start/60)).padStart(2,'0')}:{String(active.start%60).padStart(2,'0')}–{active.label}</strong>
          <span><i style={{background:COLORS.day_ahead}}/>日前 {price(active.day_ahead)}</span>
          <span><i style={{background:COLORS.real_time}}/>实时 {price(active.real_time)}</span>
        </div>
      </>}
    </div>
    <div className="price-chart-x">{[0,3,6,9,12,15,18,21,24].map(h=><span key={h} className={h%6?'minor':''} style={{left:`${h/24*100}%`}}>{String(h).padStart(2,'0')}:00</span>)}</div>
  </div>;
}

function Stats({province}:{province:Province}){
  const known=province.slots.filter(s=>s.day_ahead!=null);
  const max=known.reduce<Slot|null>((a,s)=>!a||s.day_ahead!>a.day_ahead!?s:a,null);
  const min=known.reduce<Slot|null>((a,s)=>!a||s.day_ahead!<a.day_ahead!?s:a,null);
  const negative=known.filter(s=>s.day_ahead!<0).reduce((a,s)=>a+s.end-s.start,0)/60;
  const rtCount=province.slots.filter(s=>s.real_time!=null).length;
  return <dl className="price-stats">
    <div><dt>日前均价</dt><dd>{price(mean(province.slots,'day_ahead'))}</dd></div>
    <div><dt>实时均价</dt><dd>{price(mean(province.slots,'real_time'))}{rtCount>0&&rtCount<province.points&&<small>{rtCount}/{province.points} 点</small>}</dd></div>
    <div><dt>日前最高</dt><dd>{price(max?.day_ahead)}<small>{max?.label}</small></dd></div>
    <div><dt>日前最低</dt><dd className={min&&min.day_ahead!<0?'negative':''}>{price(min?.day_ahead)}<small>{min?.label}</small></dd></div>
    <div><dt>日前负价时长</dt><dd>{negative%1?negative.toFixed(2):negative}<small>小时</small></dd></div>
  </dl>;
}

const beijingToday=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date());
const dateTags=(d:DateItem,today:string)=>[d.date===today?'今天':d.date>today?'次日':'',!d.has_curve&&d.has_average?'仅均价':''].filter(Boolean);
const Chevron=({dir}:{dir:'left'|'right'|'down'})=><svg viewBox="0 0 16 16" aria-hidden="true"><path d={dir==='down'?'M4 6l4 4 4-4':dir==='left'?'M10 4L6 8l4 4':'M6 4l4 4-4 4'}/></svg>;

function DatePicker({options,value,onChange}:{options:DateItem[];value:string;onChange:(date:string)=>void}){
  const [open,setOpen]=useState(false),[active,setActive]=useState(0);
  const root=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null);
  const today=beijingToday(),index=options.findIndex(o=>o.date===value),current=options[index];
  useEffect(()=>{if(!open)return;setActive(Math.max(0,index));
    const close=(event:globalThis.PointerEvent)=>{if(!root.current?.contains(event.target as Node))setOpen(false);};
    addEventListener('pointerdown',close);return()=>removeEventListener('pointerdown',close);},[open]);
  useEffect(()=>{if(open)root.current?.querySelector('.price-date-option.active')?.scrollIntoView({block:'nearest'});},[open,active]);
  const pick=(i:number)=>{onChange(options[i].date);setOpen(false);trigger.current?.focus();};
  const keys=(event:KeyboardEvent)=>{
    if(!open){if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();setOpen(true);}return;}
    if(event.key==='Escape'){setOpen(false);trigger.current?.focus();}
    else if(event.key==='ArrowDown'){event.preventDefault();setActive(i=>Math.min(options.length-1,i+1));}
    else if(event.key==='ArrowUp'){event.preventDefault();setActive(i=>Math.max(0,i-1));}
    else if(event.key==='Enter'||event.key===' '){event.preventDefault();pick(active);}
  };
  // 列表按日期倒序：往前一天是下一项，往后一天是上一项。
  return <div className="price-date" ref={root} onKeyDown={keys}>
    <button className="price-date-step" disabled={index<0||index>=options.length-1} onClick={()=>onChange(options[index+1].date)} aria-label="前一天"><Chevron dir="left"/></button>
    <button ref={trigger} className="price-date-current" aria-haspopup="listbox" aria-expanded={open} aria-label="选择日期" onClick={()=>setOpen(o=>!o)}>
      <strong>{dayName(value)}</strong>
      {current&&dateTags(current,today).map(t=><span key={t} className="price-date-tag">{t}</span>)}
      <Chevron dir="down"/>
    </button>
    <button className="price-date-step" disabled={index<=0} onClick={()=>onChange(options[index-1].date)} aria-label="后一天"><Chevron dir="right"/></button>
    {open&&<ul className="price-date-menu" role="listbox" aria-label="已保存的日期">
      {options.map((o,i)=><li key={o.date} role="option" aria-selected={o.date===value} className={`price-date-option${i===active?' active':''}${o.date===value?' selected':''}`} onPointerEnter={()=>setActive(i)} onClick={()=>pick(i)}>
        <span>{dayName(o.date)}</span>{dateTags(o,today).map(t=><span key={t} className="price-date-tag">{t}</span>)}
      </li>)}
    </ul>}
  </div>;
}

export default function PricePage(){
  const [status,setStatus]=useState<Status|null>(null),[dates,setDates]=useState<DateItem[]>([]),[date,setDate]=useState(''),[day,setDay]=useState<Day|null>(null);
  const [area,setArea]=useState(''),[error,setError]=useState(''),[loading,setLoading]=useState(true),[tick,setTick]=useState(0);
  useEffect(()=>{const timer=setInterval(()=>setTick(t=>t+1),5*60000);return()=>clearInterval(timer);},[]);
  useEffect(()=>{const abort=new AbortController();
    fetchJson<Status>('/api/price/status',{signal:abort.signal}).then(setStatus).catch(()=>{});
    fetchJson<{items:DateItem[]}>('/api/price/dates',{signal:abort.signal}).then(v=>setDates(v.items)).catch(()=>{});
    return()=>abort.abort();},[tick]);
  useEffect(()=>{const abort=new AbortController();setLoading(true);setError('');
    fetchJson<Day>('/api/price/day'+(date?`?date=${date}`:''),{signal:abort.signal}).then(v=>{setDay(v);setArea(a=>[a,DEFAULT_AREA].find(c=>v.provinces.some(p=>p.area_code===c))??v.provinces[0]?.area_code??'');})
      .catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();},[date,tick]);
  const province=day?.provinces.find(p=>p.area_code===area);
  const curveCodes=useMemo(()=>new Set(day?.provinces.map(p=>p.area_code)),[day]);
  const top=Math.max(...(day?.averages??[]).map(a=>Math.abs(a.day_ahead??0)),1);
  const options=dates.some(d=>d.date===day?.date)||!day?dates:[{date:day.date,has_curve:false,has_average:false},...dates];

  return <main className="price-page">
    <header className="price-heading">
      <div>
        <div className="price-eyebrow">电力现货</div>
        <h1>现货出清电价</h1>
        <p>日前与实时出清价，单位元/MWh。全天定时拉取，按日保存。</p>
      </div>
      <div className="price-heading-side">
        {status&&<div className={`price-token price-token-${status.state}`} title={status.message||undefined}>
          <span className="price-token-dot"/>
          <div><strong>{STATE_TEXT[status.state]}</strong>
            <small>{status.state==='valid'?<>预计 {clock(status.estimated_expire_at)} 失效 · 最近数据 {clock(status.last_data_at)}</>:
              status.state==='expired'?<>{clock(status.checked_at)} 检测到失效，需要更新 token</>:
              status.state==='missing'?<>需要写入 token 后才能拉取</>:<>{status.message||'等待首次拉取'}</>}</small></div>
        </div>}
        {day&&<DatePicker options={options} value={day.date} onChange={setDate}/>}
      </div>
    </header>

    {error?<div className="price-empty">{error}</div>:!day&&loading?<div className="price-empty">读取中…</div>:day&&<>
      {day.provinces.length?<section className="price-card">
        <div className="price-tabs" role="tablist">{day.provinces.map(p=><button key={p.area_code} role="tab" aria-selected={p.area_code===area} className={p.area_code===area?'active':''} onClick={()=>setArea(p.area_code)}>
          <strong>{p.name}</strong><span>{price(mean(p.slots,'day_ahead')??mean(p.slots,'real_time'))}</span></button>)}</div>
        {province&&<>
          <Stats province={province}/>
          <div className="price-legend"><span><i style={{background:COLORS.day_ahead}}/>日前</span><span><i style={{background:COLORS.real_time}}/>实时</span>
            <em>{province.points} 点，{province.resolution.join('/')} 分钟一个点 · 原始时刻为时段{province.basis==='start'?'开始，已换算为结束':'结束'} · 拉取于 {clock(province.fetched_at)}</em></div>
          <PriceChart province={province}/>
          {day.is_today&&<p className="price-note">当天实时价可能含预出清值，以晚间最后一次拉取为准。</p>}
        </>}
      </section>:<div className="price-empty">{day.is_today
        ?<>{dayName(day.date)}还没有分时曲线。{status?.state!=='valid'?'token 失效或未配置，暂时无法拉取。':'等待下一次拉取。'}</>
        :<>{dayName(day.date)}没有分时曲线：明细接口只能查当天，这一天没有在当天拉到。{day.averages.length>0&&'下面是各省日均价。'}</>}</div>}

      {day.averages.length>0&&<section className="price-card">
        <div className="price-section-head"><h2>各省日均价</h2><span>{dayName(day.date)} · 按日前均价排序</span></div>
        <div className="price-table-wrap"><table className="price-table">
          <thead><tr><th>地区</th><th className="bar-col">日前均价</th><th>实时均价</th><th>光伏机制价</th><th>风电机制价</th></tr></thead>
          <tbody>{day.averages.map(a=><tr key={a.area_code} className={curveCodes.has(a.area_code)?'has-curve':''}>
            <td>{a.area_name}</td>
            <td className="bar-col"><div><span className="price-bar"><i className={(a.day_ahead??0)<0?'negative':''} style={{width:`${Math.abs(a.day_ahead??0)/top*100}%`}}/></span><b>{price(a.day_ahead)}</b></div></td>
            <td>{price(a.real_time)}</td><td>{price(a.solar_mechanism_price)}</td><td>{price(a.wind_mechanism_price)}</td></tr>)}</tbody>
        </table></div>
      </section>}
    </>}
    <p className="price-source">数据来自第三方小程序的非公开接口，未经官方核验，仅供参考。</p>
  </main>;
}
