/** 官方无标注全球影像；由后端单机缓存，浏览器也按 HTTP 缓存复用。 */
export type EarthTexture={width:number;height:number;pixels:Uint8ClampedArray};
export const ESRI_CREDIT='Esri, Vantor, Earthstar Geographics, GIS User Community';
export const ESRI_IMAGE_URL='/api/basemap/world-imagery';
let texture:Promise<EarthTexture>|null=null;
export function loadEarthTexture():Promise<EarthTexture>{
 if(!texture)texture=(async()=>{
  const response=await fetch(ESRI_IMAGE_URL);
  if(!response.ok)throw new Error(`Esri 底图加载失败：${response.status}`);
  const bitmap=await createImageBitmap(await response.blob());
  const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
  const ctx=canvas.getContext('2d',{willReadFrequently:true})!;ctx.drawImage(bitmap,0,0);bitmap.close();
  return {width:canvas.width,height:canvas.height,pixels:ctx.getImageData(0,0,canvas.width,canvas.height).data};
 })().catch(error=>{texture=null;throw error;});
 return texture;
}
export function textureColor(texture:EarthTexture,lon:number,lat:number):number[]{
 const x=((lon+180)%360+360)%360/360*texture.width;
 const y=Math.min(texture.height-1,Math.max(0,(90-lat)/180*(texture.height-1)));
 const ix=Math.floor(x),iy=Math.floor(y),fx=x-ix,fy=y-iy;
 const offsets=[iy*texture.width+ix,iy*texture.width+(ix+1)%texture.width,Math.min(iy+1,texture.height-1)*texture.width+ix,Math.min(iy+1,texture.height-1)*texture.width+(ix+1)%texture.width];
 const weights=[(1-fx)*(1-fy),fx*(1-fy),(1-fx)*fy,fx*fy];
 return [0,1,2].map(channel=>offsets.reduce((sum,index,k)=>sum+texture.pixels[index*4+channel]*weights[k],0));
}
