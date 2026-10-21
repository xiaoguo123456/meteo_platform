export type GridMeta = { complete?:boolean; requestedAt?:number; waitMs?:number; width:number; height:number; lon0:number; lat0:number; dx:number; dy:number; run_time?:string; valid_time:string; level:string; model:string; field?:string; units?:string; interval_start?:string|null };
export type Grid = { meta:GridMeta; u:Float32Array; v:Float32Array; tiles?:Record<number,{width:number;u:Float32Array;v:Float32Array}> };
export function sample(grid:Grid, lon:number, lat:number): [number,number,number] | null {
  const m=grid.meta;
  if(lat<m.lat0 || lat>m.lat0+(m.height-1)*m.dy) return null;
  const x=((lon-m.lon0)%360+360)%360/m.dx, y=(lat-m.lat0)/m.dy;
  const i=Math.floor(x), j=Math.min(m.height-2,Math.floor(y)), fx=x-i, fy=y-j;
  const indices=[j*m.width+i,j*m.width+(i+1)%m.width,(j+1)*m.width+i,(j+1)*m.width+(i+1)%m.width];
  const weights=[(1-fx)*(1-fy),fx*(1-fy),(1-fx)*fy,fx*fy];
  let u=0,v=0;
  for(let k=0;k<4;k++){let a:number,b:number;
   if(grid.tiles){const row=Math.floor(indices[k]/m.width),col=indices[k]%m.width,tile=grid.tiles[Math.floor(row/128)*Math.ceil(m.width/128)+Math.floor(col/128)];if(!tile)return null;const index=(row%128)*tile.width+col%128;a=tile.u[index];b=tile.v[index];}
   else {a=grid.u[indices[k]];b=grid.v[indices[k]];}if(!Number.isFinite(a)||!Number.isFinite(b))return null;u+=a*weights[k];v+=b*weights[k];}
  return [u,v,Math.hypot(u,v)];
}
const stops=[[0,32,20,110],[3,27,39,145],[7,21,90,132],[12,24,137,105],[18,83,163,63],[25,185,179,46],[35,212,86,37],[50,145,29,95]];
export function windColor(speed:number):number[]{
  const b=stops.findIndex(s=>s[0]>speed), hi=b<0?stops.length-1:Math.max(1,b), a=stops[hi-1],z=stops[hi];
  const f=Math.min(1,Math.max(0,(speed-a[0])/(z[0]-a[0])));
  return [1,2,3].map(i=>Math.round(a[i]+(z[i]-a[i])*f));
}

export const fields:Record<string,{label:string; min:number; max:number; unit:string; colors:number[][]}> = {
 wind:{label:'风场',min:0,max:50,unit:'m/s',colors:stops},
 temperature:{label:'温度',min:-40,max:40,unit:'°C',colors:[[-40,75,54,160],[-20,53,130,204],[0,172,222,218],[20,248,207,103],[40,191,49,54]]},
 pressure:{label:'气压',min:960,max:1040,unit:'hPa',colors:[[960,81,63,163],[980,56,140,197],[1000,159,216,200],[1020,246,212,121],[1040,199,74,49]]},
 humidity:{label:'湿度',min:0,max:100,unit:'%',colors:[[0,231,217,177],[25,201,218,178],[50,111,191,166],[75,44,143,160],[100,46,68,135]]},
 precipitation:{label:'降水',min:0,max:50,unit:'mm',colors:[[0,232,240,239],[1,143,214,198],[5,62,169,177],[10,65,112,186],[25,123,66,166],[50,182,47,93]]},
 // 晴空偏深、阴天趋白，接近卫星云图观感。
 cloud:{label:'云量',min:0,max:100,unit:'%',colors:[[0,31,58,82],[30,86,116,138],[60,164,181,193],[85,222,229,233],[100,248,250,251]]}
};
export function fieldColor(field:string,value:number){
 const colors=fields[field].colors;
 const i=colors.findIndex(s=>s[0]>value),hi=i<0?colors.length-1:Math.max(1,i),a=colors[hi-1],b=colors[hi];
 const f=Math.max(0,Math.min(1,(value-a[0])/(b[0]-a[0])));
 return [1,2,3].map(k=>Math.round(a[k]+(b[k]-a[k])*f));
}
