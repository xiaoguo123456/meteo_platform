// 四模型对比：各模型起报时刻与时间间隔不同（如 IFS 3 小时一帧），按实际时刻对齐。
export type SeriesPoint={time:string;value:number|null};
export type ModelSeries={model:string;points:SeriesPoint[]};
const HOUR=3600000;
// 取离目标时刻最近、且相差不超过容差的有效值；超出容差视为该模型此刻无数据。
export function valueAt(points:SeriesPoint[],time:number,tolerance=1.5*HOUR):number|null{
 let best:SeriesPoint|null=null,distance=Infinity;
 for(const p of points){if(p.value==null)continue;const d=Math.abs(Date.parse(p.time)-time);if(d<distance){distance=d;best=p;}}
 return best&&distance<=tolerance?best.value:null;
}
// 从各模型共同起点开始的若干小时内，四模型数值相差最大的时刻；只比较各模型都恰有该时刻的帧
// （四模型都落在整点 UTC 上），避免拿 5 时与 6 时的值相减；至少两个模型有值才计算。
export function largestSpread(series:ModelSeries[],hours=24):{spread:number;time:string;models:number}|null{
 const usable=series.filter(s=>s.points.some(p=>p.value!=null));
 if(usable.length<2)return null;
 const start=Math.max(...usable.map(s=>Date.parse(s.points.find(p=>p.value!=null)!.time))),end=start+hours*HOUR;
 const times=[...new Set(usable.flatMap(s=>s.points.map(p=>p.time)))].filter(t=>{const v=Date.parse(t);return v>=start&&v<=end;}).sort();
 let result:{spread:number;time:string;models:number}|null=null;
 for(const time of times){
  const values=usable.map(s=>valueAt(s.points,Date.parse(time),0)).filter((v):v is number=>v!=null);
  if(values.length<2)continue;
  const spread=Math.max(...values)-Math.min(...values);
  if(!result||spread>result.spread)result={spread,time,models:values.length};
 }
 return result;
}
