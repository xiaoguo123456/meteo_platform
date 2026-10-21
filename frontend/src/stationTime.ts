// 站点预测曲线的时间工具，一律按北京时间计算，与浏览器所在时区无关。
const parts=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23'});
function beijing(s:string){const map=Object.fromEntries(parts.formatToParts(new Date(s)).map(p=>[p.type,p.value]));return {date:`${map.year}-${map.month}-${map.day}`,month:Number(map.month),day:Number(map.day),hour:Number(map.hour)%24};}
export const beijingDate=(s:string|null|undefined)=>s?beijing(s).date:'';
export const hourLabel=(s:string|null|undefined)=>{if(!s)return '—';const t=beijing(s);return `${t.month}/${t.day} ${String(t.hour).padStart(2,'0')}时`};
export function dayIndexes(times:(string|null)[],date:string){return times.flatMap((time,index)=>beijingDate(time)===date?[index]:[])}
export function nearestIndex(times:(string|null)[],target:string|null|undefined){const t=Date.parse(target||'');if(!Number.isFinite(t))return 0;return times.reduce((best,time,i)=>Math.abs(Date.parse(time||'')-t)<Math.abs(Date.parse(times[best]||'')-t)?i:best,0)}
export function dayBreaks(times:(string|null)[]){return times.flatMap((time,index)=>index>0&&time&&times[index-1]&&beijingDate(time)!==beijingDate(times[index-1])?[index]:[])}
export type AxisTick={index:number;label:string;minor:boolean};
export function axisTicks(times:(string|null)[]){const breaks=new Set(dayBreaks(times));return times.flatMap((time,index):AxisTick[]=>{if(!time)return [];const hour=beijing(time).hour;const edge=index===0||index===times.length-1;return edge||breaks.has(index)||hour%6===0?[{index,label:hourLabel(time),minor:!edge&&!breaks.has(index)&&hour%12!==0}]:[]})}
