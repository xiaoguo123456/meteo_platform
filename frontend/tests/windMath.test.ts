import assert from 'node:assert/strict';
import { sample, windColor, fieldColor, type Grid } from '../src/windMath';
const meta={width:360,height:181,lon0:-180,lat0:-90,dx:1,dy:1,valid_time:'',level:'',model:''};
const grid:Grid={meta,u:new Float32Array(360*181).fill(3),v:new Float32Array(360*181).fill(4)};
assert.deepEqual(sample(grid,180,90),[3,4,5]);
assert.deepEqual(sample(grid,-180,-90),[3,4,5]);
assert.deepEqual(sample(grid,540,12.5),[3,4,5]);
assert.equal(sample(grid,0,91),null);
for(let y=0;y<181;y++)for(let x=0;x<360;x++){grid.u[y*360+x]=-(y-90);grid.v[y*360+x]=x-180;}
assert.deepEqual(sample(grid,10.5,20.5)?.slice(0,2),[-20.5,10.5]);
let x=10,y=0;
for(let k=0;k<100;k++){const [u,v]=sample(grid,x,y)!;x+=u*.001;y+=v*.001;}
assert.ok(y>.9&&x<10,'旋涡轨迹应随当前位置转弯');
grid.u[90*360+180]=NaN;assert.equal(sample(grid,.5,.5),null);
assert.deepEqual(windColor(0),[32,20,110]);assert.deepEqual(windColor(50),[145,29,95]);
console.log('通过：恒定风、日期变更线、极点、双线性插值、旋涡推进、缺测和色标');

assert.deepEqual(fieldColor('temperature',-40),[75,54,160]);
assert.notDeepEqual(fieldColor('temperature',-20),fieldColor('temperature',20));
assert.deepEqual(fieldColor('humidity',100),[46,68,135]);
