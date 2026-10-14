import type { Grid } from './windMath';
export function decodeFrame(buffer:ArrayBuffer):Grid{
 const size=new DataView(buffer).getUint32(0,true);
 const meta=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,4,size)));
 const count=meta.width*meta.height,offset=4+size,channels=meta.channels??2;
 let values:Float32Array;
 if(meta.encoding==='palette-u16-le'||meta.encoding==='palette-delta-u16-le'){
  const palette=new Float32Array(buffer,offset,meta.palette_size);
  const start=offset+meta.palette_size*4;
  if(buffer.byteLength!==start+count*channels*2)throw new Error('预报数据长度不完整');
  const indices=new Uint16Array(buffer,start,count*channels);
  if(meta.encoding==='palette-delta-u16-le')for(let i=0;i<indices.length;i++)if(i%meta.width)indices[i]=(indices[i]+indices[i-1])&65535;
  values=new Float32Array(indices.length);
  for(let i=0;i<indices.length;i++){if(indices[i]>=palette.length)throw new Error('预报编码损坏');values[i]=palette[indices[i]];}
 }else{
  if(buffer.byteLength!==offset+count*channels*4)throw new Error('预报数据长度不完整');
  values=new Float32Array(buffer,offset,count*channels);
 }
 return {meta,u:values.subarray(0,count),v:channels===2?values.subarray(count):new Float32Array(count)};
}

import { geometry, visibleTiles, TILE_SIZE, type Viewport } from './viewTiles';
type Entry={promise:Promise<Grid>;controller:AbortController;pending:boolean;background:boolean};
const tileCache=new Map<string,Grid>(),frames=new Map<string,Entry>();
let cachedBytes=0;
const budget=192*1024*1024;
function remember(key:string,tile:Grid){
 if(tileCache.has(key))return;tileCache.set(key,tile);cachedBytes+=tile.u.byteLength+tile.v.byteLength;
 while(cachedBytes>budget){const first=tileCache.keys().next().value!;const item=tileCache.get(first)!;cachedBytes-=item.u.byteLength+item.v.byteLength;tileCache.delete(first);}
}
export function cancelPendingFrames(){
 for(const [key,entry] of frames)if(entry.pending){entry.controller.abort();frames.delete(key);}
}
export function loadFrame(model:string,field:string,run:string,time:string,view:Viewport,background=false,onProgress?:(grid:Grid)=>void):Promise<Grid>{
 const ids=visibleTiles(model,view),prefix=[model,field,run,time].join('/'),key=prefix+'/'+[...ids].sort((a,b)=>a-b).join(',');
 if(!background)for(const [url,entry] of frames)if(url!==key&&entry.pending&&!entry.background){entry.controller.abort();frames.delete(url);}
 const existing=frames.get(key);if(existing){existing.background=background;frames.delete(key);frames.set(key,existing);return existing.promise;}
 const controller=new AbortController(),entry:Entry={controller,pending:true,background,promise:Promise.resolve(null as unknown as Grid)};
 entry.promise=(async()=>{
  const sparse:Grid={meta:{...geometry(model),valid_time:time,model,field,level:''},u:new Float32Array(),v:new Float32Array(),tiles:{}};
  const add=(tile:Grid)=>{const m=tile.meta as Grid['meta']&{tile_x:number;tile_y:number;full_width:number;full_height:number};sparse.meta={...m,width:m.full_width,height:m.full_height};const id=m.tile_y/TILE_SIZE*Math.ceil(m.full_width/TILE_SIZE)+m.tile_x/TILE_SIZE;sparse.tiles![id]={width:m.width,u:tile.u,v:tile.v};remember(prefix+'/'+id,tile);};
  const missing:number[]=[];for(const id of ids){const tile=tileCache.get(prefix+'/'+id);if(tile)add(tile);else missing.push(id);}
  if(missing.length){
   const query=new URLSearchParams({field,run_time:run,valid_time:time,tiles:missing.join(','),version:'4'});
   let response:Response|undefined;
   for(let attempt=0;attempt<2;attempt++){
    try{
     response=await fetch(`/api/tiles/${model}?${query}`,{signal:controller.signal,priority:background?'low':'high'} as RequestInit);
     if(controller.signal.aborted)throw new DOMException('请求已取消','AbortError');
     if(response.ok)break;
     const body=await response.text();let detail='';try{detail=JSON.parse(body).detail||'';}catch{}
     throw new Error(detail||`预报数据块读取失败（HTTP ${response.status}）`);
    }catch(error){if(controller.signal.aborted||attempt)throw error;}
   }
   if(!response?.ok)throw new Error('预报数据块暂时不可用');
   const reader=response.body!.getReader();let pending=new Uint8Array(0),last=0,received=0;
   try{while(true){
    const result=await reader.read();if(result.done)break;
    const combined=new Uint8Array(pending.length+result.value.length);combined.set(pending);combined.set(result.value,pending.length);pending=combined;
    while(pending.length>=4){
     const length=new DataView(pending.buffer,pending.byteOffset,4).getUint32(0,true);if(pending.length<length+4)break;
     const compressed=pending.slice(4,4+length);pending=pending.slice(4+length);
     const decoded=await new Response(new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
     if(controller.signal.aborted)throw new DOMException('请求已取消','AbortError');add(decodeFrame(decoded));received++;
     if(onProgress&&performance.now()-last>250){onProgress({...sparse,meta:{...sparse.meta,complete:false},tiles:{...sparse.tiles}});last=performance.now();}
    }
   }}finally{reader.releaseLock();}
   if(pending.length||received!==missing.length)throw new Error('预报数据块传输不完整');
  }
  entry.pending=false;
  while(frames.size>8){const first=[...frames].find(([url,e])=>url!==key&&!e.pending);if(!first)break;frames.delete(first[0]);}
  return {...sparse,meta:{...sparse.meta,complete:true}};
 })();frames.set(key,entry);entry.promise.catch(()=>{if(frames.get(key)===entry)frames.delete(key);});return entry.promise;
}
