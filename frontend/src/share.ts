// 首页分享链接：#home?m=模型&f=要素&t=预报时刻&r=视野中心经,纬&z=缩放&p=点击经,纬&s=省份代码&c=1（四模型对比）&v=p（按省填色）。
// 只记预报时刻、不记起报批次：批次只保留两份，过期链接按最近时刻打开。
export type ShareState={model?:string;field?:string;time?:string;center?:[number,number];zoom?:number;point?:[number,number];province?:string;compare?:boolean;byProvince?:boolean};
export const MODELS=['gfs','grapes','ifs','aifs'];
const pair=(value:string|null,lonLimit:number,latLimit:number):[number,number]|undefined=>{
 const parts=value?.split(',').map(Number);
 if(!parts||parts.length!==2||!parts.every(Number.isFinite))return;
 const [lon,lat]=parts;return Math.abs(lon)<=lonLimit&&Math.abs(lat)<=latLimit?[lon,lat]:undefined;
};
export function parseShare(hash:string,fieldIds:string[]):ShareState{
 if(!hash.startsWith('#home?'))return {};
 const q=new URLSearchParams(hash.slice(6)),state:ShareState={};
 const model=q.get('m'),field=q.get('f'),time=q.get('t'),zoom=Number(q.get('z')),province=q.get('s');
 if(model&&MODELS.includes(model))state.model=model;
 if(field&&fieldIds.includes(field))state.field=field;
 if(time&&!Number.isNaN(Date.parse(time)))state.time=time;
 state.center=pair(q.get('r'),180,85);
 if(q.get('z')&&Number.isFinite(zoom))state.zoom=Math.max(.65,Math.min(3,zoom));
 state.point=pair(q.get('p'),180,90);
 if(province&&/^\d{6}$/.test(province)&&state.point)state.province=province;
 if(q.get('c')==='1'&&state.point)state.compare=true;
 if(q.get('v')==='p')state.byProvince=true;
 return state;
}
export function buildShare(state:ShareState):string{
 const q=new URLSearchParams();
 if(state.model)q.set('m',state.model);
 if(state.field)q.set('f',state.field);
 if(state.time)q.set('t',state.time);
 if(state.center)q.set('r',state.center.map(v=>v.toFixed(2)).join(','));
 if(state.zoom!=null)q.set('z',state.zoom.toFixed(2));
 if(state.byProvince)q.set('v','p');
 if(state.point){q.set('p',state.point.map(v=>v.toFixed(3)).join(','));if(state.province)q.set('s',state.province);if(state.compare)q.set('c','1');}
 return `#home?${q.toString().replace(/%2C/g,',').replace(/%3A/g,':')}`;
}
// 分享的时刻不在当前批次时取最近一帧，并告知调用方是否精确命中。
export function nearestTime(times:string[],time:string):{index:number;exact:boolean}{
 const target=Date.parse(time);let index=0;
 times.forEach((t,i)=>{if(Math.abs(Date.parse(t)-target)<Math.abs(Date.parse(times[index])-target))index=i;});
 return {index,exact:times[index]===time};
}
