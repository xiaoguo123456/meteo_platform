import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { geoArea } from 'd3-geo';
// 环绕方向错了，d3 会把省份的补集（几乎整个地球，约 4π 球面度）当成填色区域。
const shapes=JSON.parse(readFileSync(new URL('../../backend/app/data/province_shapes.json',import.meta.url),'utf8'));
assert.equal(shapes.features.length,34);
let total=0;
for(const feature of shapes.features){
 const area=geoArea(feature);total+=area;
 assert.ok(area>0&&area<0.06,`${feature.properties.name} 填色面积异常：${area}`);
}
// 中国陆地约 960 万平方公里，按地球半径 6371 km 约 0.236 球面度。
assert.ok(Math.abs(total-0.236)<0.01,`省份总面积 ${total}`);
console.log('通过：34 个省份环绕方向正确，填色面积与国土面积一致');
