const assert=require('node:assert/strict');
const path=process.argv[2];
function worker(){let result;global.self={postMessage:value=>{result=value;}};delete require.cache[require.resolve(path)];require(path);return data=>{self.onmessage({data});return result;};}
const grid={meta:{width:4,height:3,lon0:-180,lat0:-90,dx:90,dy:90,valid_time:'test',level:'10m',model:'test',field:'wind'},u:new Float32Array(12).fill(3),v:new Float32Array(12).fill(4)};
const frame={id:1,generation:1,width:100,height:80,radius:35,rotation:[-115,-12,0],coarse:false};
let run=worker();run({grid});const first=run(frame);const second=run({...frame,id:2});assert.deepEqual(second.pixels,first.pixels);assert.deepEqual(second.vectors,first.vectors);
const temperature={...grid,meta:{...grid.meta,field:'temperature'}};run({grid:temperature});const switched=run(frame);
run=worker();run({grid:temperature});const fresh=run(frame);assert.deepEqual(switched.pixels,fresh.pixels);
const rotated=run({...frame,rotation:[20,30,0]});run=worker();run({grid:temperature});assert.deepEqual(rotated.pixels,run({...frame,rotation:[20,30,0]}).pixels);
console.log('通过：投影缓存重复绘制、要素切换、旋转失效与全新计算逐像素一致');
