export type Viewport={width:number;height:number;radius:number;rotation:[number,number,number]};
export const TILE_SIZE=128;
export function geometry(model:string){return model==='grapes'?{width:2880,height:1440,lon0:-180,lat0:-89.9375,dx:.125,dy:.125}:{width:1440,height:721,lon0:-180,lat0:-90,dx:.25,dy:.25};}
export function visibleTiles(model:string,view:Viewport):number[]{
 const m=geometry(model),columns=Math.ceil(m.width/TILE_SIZE),radians=Math.PI/180;
 const lon=-view.rotation[0]*radians,lat=-view.rotation[1]*radians;
 const cap=Math.asin(Math.min(1,Math.hypot(view.width/2,view.height/2)/view.radius));
 const tiles:{id:number;distance:number}[]=[];
 for(let y=0;y<m.height;y+=TILE_SIZE)for(let x=0;x<m.width;x+=TILE_SIZE){
  const w=Math.min(TILE_SIZE,m.width-x),h=Math.min(TILE_SIZE,m.height-y);
  const a=(m.lon0+(x+(w-1)/2)*m.dx)*radians,b=(m.lat0+(y+(h-1)/2)*m.dy)*radians;
  const distance=Math.acos(Math.max(-1,Math.min(1,Math.sin(lat)*Math.sin(b)+Math.cos(lat)*Math.cos(b)*Math.cos(a-lon))));
  // 球面距离不大于经纬度平面的路径长度；外扩一格保证双线性插值接缝。
  const margin=Math.hypot(w*m.dx,h*m.dy)/2*radians+2*m.dx*radians;
  if(distance<=cap+margin)tiles.push({id:y/TILE_SIZE*columns+x/TILE_SIZE,distance});
 }
 return tiles.sort((a,b)=>a.distance-b.distance).map(t=>t.id);
}
