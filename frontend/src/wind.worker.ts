import { geoOrthographic } from 'd3-geo';
import { sample, fieldColor, type Grid } from './windMath';
import { textureColor, type EarthTexture } from './basemap';
let grid:Grid|null=null,texture:EarthTexture|null=null,satellite:EarthTexture|null=null;
// 云量像卫星云图：晴空透出真彩色底图（略压暗以衬托云），云量越大越接近不透明的白，薄云带一点灰。
const cloudColor=(base:number[],cover:number)=>{
 // 透明度随云量略呈加速增长：中等云量保持半透明以显出层次，满云量也留一点底图纹理。
 const amount=Math.max(0,Math.min(1,(cover-5)/90)),alpha=Math.pow(amount,1.15)*.86;
 const white=[206+46*amount,215+38*amount,224+30*amount];
 return base.map((value,i)=>Math.round(value*.8*(1-alpha)+white[i]*alpha));
};
// 按省填色时只画底图与风矢量，格点色块由省份填色代替。
let colorize=true;
let geometryKey='';
let geometryCache:({ll:[number,number];px:number;py:number;base:number[];east?:[number,number]|null;north?:[number,number]|null}|undefined)[]=[];
self.onmessage=({data})=>{
 if('satellite' in data){satellite=data.satellite;return;}
 if('grid' in data){grid=data.grid;return;}
 if('colorize' in data){colorize=data.colorize;return;}
 if(data.texture){texture=data.texture;geometryKey='';return;}
 const started=performance.now();
 const {id,generation,width,height,rotation,radius,coarse}=data;
 const projection=geoOrthographic().rotate(rotation).translate([width/2,height/2]).scale(radius);
 const pixels=new Uint8ClampedArray(width*height*4);
 const vectors=grid&&!coarse&&grid.meta.field==='wind'?new Float32Array(width*height*3):null;vectors?.fill(NaN);
 const stride=coarse?6:2;
 const key=JSON.stringify([width,height,rotation,radius,stride]);
 if(key!==geometryKey){geometryKey=key;geometryCache=[];}
 const columns=Math.ceil(width/stride);
 for(let y=0;y<height;y+=stride)for(let x=0;x<width;x+=stride){
  const slot=(y/stride)*columns+x/stride;
  let point=geometryCache[slot];
  if(!point){
   const distance=Math.hypot(x-width/2,y-height/2);if(distance>radius+stride)continue;
   const factor=Math.min(1,(radius-.1)/Math.max(.1,distance));
   const px=width/2+(x-width/2)*factor,py=height/2+(y-height/2)*factor;
   const ll=projection.invert!([px,py]);if(!ll)continue;
   point={ll,px,py,base:texture?textureColor(texture,ll[0],ll[1]):[216,229,228]};geometryCache[slot]=point;
  }
  const {ll,px,py}=point;
  let color=point.base;
  if(satellite&&Math.abs(ll[1])<85.051129&&Math.cos(ll[1]*Math.PI/180)*Math.cos((ll[0]-140.7)*Math.PI/180)>6378/42164){
   const sx=Math.min(satellite.width-1,Math.floor(((ll[0]+180)%360+360)%360/360*satellite.width));
   const sy=Math.max(0,Math.min(satellite.height-1,Math.floor((1-Math.asinh(Math.tan(ll[1]*Math.PI/180))/Math.PI)/2*satellite.height)));
   const offset=(sy*satellite.width+sx)*4;
   if(satellite.pixels[offset+3])color=Array.from(satellite.pixels.subarray(offset,offset+3));
  }
  const weather=grid?sample(grid,ll[0],ll[1]):null;
  let vx=NaN,vy=NaN,speed=NaN;
  if(weather&&grid){
   const [u,v,s]=weather;speed=s;
   const field=grid.meta.field||'wind';
   const tint=fieldColor(field,field==='wind'?s:u);
   const opacity=texture?.pixels?(field==='wind'?.72:.66):1;
   if(colorize&&field==='cloud'&&texture?.pixels)color=cloudColor(color,u);
   else if(colorize)color=color.map((base,i)=>Math.round(base*(1-opacity)+tint[i]*opacity));
   if(vectors){
    const cos=Math.max(.02,Math.cos(ll[1]*Math.PI/180)),step=.001;
    const east=point.east??(point.east=projection([ll[0]+step,ll[1]])),north=point.north??(point.north=projection([ll[0],ll[1]+step]));
    if(east&&north){vx=((east[0]-px)/step*u/cos+(north[0]-px)/step*v)*.045;vy=((east[1]-py)/step*u/cos+(north[1]-py)/step*v)*.045;}
   }
  }
  for(let yy=y;yy<Math.min(y+stride,height);yy++)for(let xx=x;xx<Math.min(x+stride,width);xx++){
   const n=yy*width+xx;
   if(vectors&&Math.hypot(xx-width/2,yy-height/2)<radius-1)vectors.set([vx,vy,speed],n*3);
   pixels.set([...color,255],n*4);
  }
 }
 const transfer:Transferable[]=[pixels.buffer];if(vectors)transfer.push(vectors.buffer);
 self.postMessage({id,generation,width,height,rotation,radius,coarse,pixels,vectors,elapsed:performance.now()-started,field:grid?.meta.field,hasBasemap:!!texture,meta:grid?.meta},{transfer});
};
