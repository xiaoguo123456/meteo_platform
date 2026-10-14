import assert from 'node:assert/strict';
import { visibleTiles,geometry } from '../src/viewTiles';
import { geoOrthographic } from 'd3-geo';
import {sample,type Grid} from '../src/windMath';
for(const model of ['gfs','grapes'])for(const rotation of [[-115,-12,0],[-180,70,0],[40,-80,0]] as [number,number,number][])for(const zoom of [1,3]){
 const view={width:1000,height:700,radius:322*zoom,rotation};const ids=new Set(visibleTiles(model,view)),m=geometry(model);
 const p=geoOrthographic().rotate(rotation).translate([500,350]).scale(view.radius);
 for(let y=5;y<700;y+=17)for(let x=5;x<1000;x+=17){
  if(Math.hypot(x-500,y-350)>view.radius-1)continue;
  const ll=p.invert!([x,y])!;const col=Math.floor(((ll[0]+180)%360+360)%360/m.dx),row=Math.floor((ll[1]-m.lat0)/m.dy);
  if(row<0||row>=m.height)continue;
  assert.ok(ids.has(Math.floor(row/128)*Math.ceil(m.width/128)+Math.floor(col/128)),'不能漏掉视野内原始网格');
 }
}
const m={...geometry('gfs'),model:'gfs',level:'80m',valid_time:''};
const grid:Grid={meta:m,u:new Float32Array(),v:new Float32Array(),tiles:{}};
for(let row=0;row<6;row++)for(let col=0;col<12;col++){const width=Math.min(128,1440-col*128),height=Math.min(128,721-row*128);grid.tiles![row*12+col]={width,u:new Float32Array(width*height).fill(3),v:new Float32Array(width*height).fill(4)};}
for(const lon of [-180,180,-148.1,179.99])for(const lat of [-90,90,-58.1])assert.deepEqual(sample(grid,lon,lat),[3,4,5]);
const near=visibleTiles('grapes',{width:1000,height:700,radius:966,rotation:[-115,-12,0]});
const globe=visibleTiles('grapes',{width:1000,height:700,radius:322,rotation:[-115,-12,0]});
assert.ok(near.length<globe.length/2);
console.log('通过：视野覆盖、日期变更线、极区、分块接缝；GRAPES 半球/局部块数',globe.length,near.length);
