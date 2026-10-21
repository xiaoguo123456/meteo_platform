// 一键导出动图：把地球三层画布合成到导出画布，叠加标题、时间、色标与水印，用 MediaRecorder 录成视频。
export type ExportFormat='portrait'|'landscape';
export type Overlay={title:string;subtitle:string;time:string;run:string;legend:{colors:number[][];min:number;max:number;ticks:string[]};credit:string};
export const SIZES:Record<ExportFormat,{width:number;height:number}>={portrait:{width:1080,height:1440},landscape:{width:1920,height:1080}};
const FONT='"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif';
// 优先 MP4，小红书、公众号都能直接发；Firefox 不支持录 MP4 时退回 WebM。
export function pickMime(supported:(type:string)=>boolean=type=>typeof MediaRecorder!=='undefined'&&MediaRecorder.isTypeSupported(type)):{mime:string;ext:'mp4'|'webm'}|null{
 for(const mime of ['video/mp4;codecs=avc1.42E01E','video/mp4','video/webm;codecs=vp9','video/webm'])if(supported(mime))return {mime,ext:mime.startsWith('video/mp4')?'mp4':'webm'};
 return null;
}
// 地球所在的正方形区域：放大后地球超出视口时取视口内最大的正方形，保证圆盘居中。
export function globeCrop(width:number,height:number,radius:number){
 const side=Math.min(width,height,radius*2.16);
 return {x:(width-side)/2,y:(height-side)/2,side};
}
// 导出画布的版式：竖版地球在标题与色标之间，横版地球靠左、文字在右。
export function layout(format:ExportFormat){
 const {width,height}=SIZES[format];
 return format==='portrait'
  ?{width,height,globe:{x:40,y:230,side:1000},text:{x:72,y:96},legend:{x:72,y:1262,width:936}}
  :{width,height,globe:{x:60,y:40,side:1000},text:{x:1140,y:150},legend:{x:1140,y:820,width:700}};
}
export function renderFrame(ctx:CanvasRenderingContext2D,format:ExportFormat,source:HTMLElement,overlay:Overlay){
 const plan=layout(format);
 ctx.fillStyle='#eef3f3';ctx.fillRect(0,0,plan.width,plan.height);
 const canvases=[...source.querySelectorAll('canvas')];
 const box=source.getBoundingClientRect(),radius=Number(source.dataset.radius)||Math.min(box.width,box.height)*.46;
 const crop=globeCrop(box.width,box.height,radius);
 for(const canvas of canvases){const scale=canvas.width/Math.max(1,box.width);ctx.drawImage(canvas,crop.x*scale,crop.y*scale,crop.side*scale,crop.side*scale,plan.globe.x,plan.globe.y,plan.globe.side,plan.globe.side);}
 const {x,y}=plan.text,big=format==='portrait'?56:64;
 ctx.fillStyle='#17393f';ctx.font=`600 ${big}px ${FONT}`;ctx.fillText(overlay.title,x,y);
 ctx.fillStyle='#3d5a60';ctx.font=`400 ${big*.5}px ${FONT}`;ctx.fillText(overlay.subtitle,x,y+big*.95);
 ctx.fillStyle='#12656b';ctx.font=`600 ${big*.78}px ${FONT}`;
 const timeY=format==='portrait'?y:y+big*2.6;ctx.textAlign=format==='portrait'?'right':'left';ctx.fillText(overlay.time,format==='portrait'?plan.width-x:x,timeY);
 ctx.fillStyle='#5a7277';ctx.font=`400 ${big*.4}px ${FONT}`;ctx.fillText(overlay.run,format==='portrait'?plan.width-x:x,timeY+big*.8);ctx.textAlign='left';
 const {legend}=overlay,bar=plan.legend,gradient=ctx.createLinearGradient(bar.x,0,bar.x+bar.width,0);
 for(const [value,...rgb] of legend.colors)gradient.addColorStop(Math.max(0,Math.min(1,(value-legend.min)/(legend.max-legend.min))),`rgb(${rgb.join(',')})`);
 ctx.fillStyle=gradient;ctx.fillRect(bar.x,bar.y,bar.width,14);
 ctx.fillStyle='#3d5a60';ctx.font=`400 22px ${FONT}`;
 legend.ticks.forEach((tick,i)=>{ctx.textAlign=i===0?'left':i===legend.ticks.length-1?'right':'center';ctx.fillText(tick,bar.x+bar.width*i/(legend.ticks.length-1),bar.y+44);});
 ctx.textAlign='left';ctx.fillStyle='#7a9095';ctx.font=`400 20px ${FONT}`;ctx.fillText(overlay.credit,bar.x,bar.y+80);
 ctx.textAlign='right';ctx.fillStyle='#12656b';ctx.font=`600 24px ${FONT}`;// 水印单独占底部一行，与数据来源错开，避免长来源文字压到水印。
 ctx.fillText('晴川观象 · meteo.weishenai.cn',format==='portrait'?plan.width-72:plan.width-80,plan.height-36);ctx.textAlign='left';
}
export function createRecorder(format:ExportFormat,source:HTMLElement,overlay:()=>Overlay,onHidden?:(hidden:boolean)=>void){
 const type=pickMime();if(!type)throw new Error('当前浏览器不支持录制视频');
 const plan=layout(format),canvas=document.createElement('canvas');canvas.width=plan.width;canvas.height=plan.height;
 const ctx=canvas.getContext('2d')!;renderFrame(ctx,format,source,overlay());
 const recorder=new MediaRecorder(canvas.captureStream(30),{mimeType:type.mime,videoBitsPerSecond:8_000_000});
 const chunks:Blob[]=[];recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
 // 页面切到后台时浏览器停发动画帧，继续录会得到定格或过短的视频：隐藏期间暂停，回来后接着录。
 // 时长按实际录进去的时间计，而不是墙钟时间。
 let frame=0,running=true,held=false,recorded=0,last=performance.now();
 const waiters:{target:number;resolve:()=>void}[]=[];
 const sync=()=>{const want=!held&&!document.hidden;if(want&&recorder.state==='paused')recorder.resume();if(!want&&recorder.state==='recording')recorder.pause();};
 const visibility=()=>{sync();onHidden?.(document.hidden);last=performance.now();};
 document.addEventListener('visibilitychange',visibility);
 const tick=()=>{if(!running)return;const now=performance.now();if(recorder.state==='recording')recorded+=now-last;last=now;
  renderFrame(ctx,format,source,overlay());
  for(const w of waiters.splice(0))if(recorded>=w.target)w.resolve();else waiters.push(w);
  frame=requestAnimationFrame(tick);};
 recorder.start(250);sync();tick();
 const close=()=>{running=false;cancelAnimationFrame(frame);document.removeEventListener('visibilitychange',visibility);};
 const finish=()=>new Promise<Blob>(resolve=>{recorder.onstop=()=>resolve(new Blob(chunks,{type:type.mime.split(';')[0]}));close();if(recorder.state!=='inactive')recorder.stop();});
 return {ext:type.ext,
  // 等待下一帧加载时暂停录制，成片里不出现卡顿与空白。
  pause:()=>{held=true;sync();},
  resume:()=>{held=false;sync();last=performance.now();},
  // 再录 ms 毫秒（按实际录入时长）后返回。
  record:(ms:number)=>new Promise<void>(resolve=>waiters.push({target:recorded+ms,resolve})),
  stop:finish,
  cancel:()=>{close();for(const w of waiters.splice(0))w.resolve();recorder.ondataavailable=null;if(recorder.state!=='inactive')recorder.stop();}};
}
