/* PixelKit sprites v1.4 - parametric 24x24 pixel emoji, form-shaded (mode 'legacy' = v1.3 checker band).
   Usage:
     PixelKit.drawSprite(canvas, 'catvader')        // content: dither shade + ink outline
     PixelKit.drawSprite(canvas, 'gear', 'b')       // schematic: outline only, no shade
     PixelKit.drawSprite(canvas, 'gear', 'legacy')  // v1.3 checker band
     PixelKit.drawSprite(canvas, 'doc', null, true) // dark surface: light outline
   Display at whole multiples: 24 / 48 / 72 px, image-rendering: pixelated.
   Canon: https://claude.ai/code/artifact/3e5ebd2a-a56c-4d89-8cb3-23b283fb316b */
(function(root){
const SPRCOL={v:'#8256b8',r:'#c04f31',o:'#d96a1e',y:'#e0a90f',g:'#2f8f63',b:'#3a6cbf',l:'#b9b9b4',w:'#ffffff',k:'#191a1c'};
function sR(ctx,x,y,w,h,c){ctx.fillStyle=c;ctx.fillRect(x,y,w,h)}
function sE(ctx,cx,cy,rx,ry,c){ctx.fillStyle=c;
  for(let y=Math.ceil(cy-ry);y<=Math.floor(cy+ry);y++){
    const t=(y-cy)/ry,hw=rx*Math.sqrt(Math.max(0,1-t*t));
    const x1=Math.round(cx-hw),x2=Math.round(cx+hw);
    if(x2>=x1)ctx.fillRect(x1,y,x2-x1+1,1)}}
function cEll(ctx,cx,cy,rx,ry){
  for(let y=Math.ceil(cy-ry);y<=Math.floor(cy+ry);y++){
    const t=(y-cy)/ry,hw=rx*Math.sqrt(Math.max(0,1-t*t));
    const x1=Math.round(cx-hw),x2=Math.round(cx+hw);
    if(x2>=x1)ctx.clearRect(x1,y,x2-x1+1,1)}}
function sPoly(ctx,pts,c){ctx.fillStyle=c;
  for(let y=0;y<24;y++)for(let x=0;x<24;x++){
    let ins=false;
    for(let i=0,j=pts.length-1;i<pts.length;j=i++){
      const xi=pts[i][0],yi=pts[i][1],xj=pts[j][0],yj=pts[j][1];
      if((yi>y+.5)!==(yj>y+.5)&&x+.5<(xj-xi)*(y+.5-yi)/(yj-yi)+xi)ins=!ins}
    if(ins)ctx.fillRect(x,y,1,1)}}
const C24=SPRCOL;
const DRAW24={
 doc(x){sR(x,5,2,14,20,C24.w);x.clearRect(16,2,3,3);
  sR(x,8,8,8,2,C24.b);sR(x,8,12,9,2,C24.b);sR(x,8,16,7,2,C24.b)},
 check(x){sR(x,3,3,18,18,C24.g);
  [[3,3],[20,3],[3,20],[20,20]].forEach(p=>x.clearRect(p[0],p[1],1,1));
  [[6,13],[7,14],[8,15],[9,16],[11,15],[12,14],[13,13],[14,12],[15,11],[16,10],[17,9]]
    .forEach(p=>sR(x,p[0],p[1]-1,2,3,C24.w));
  sR(x,10,16,2,3,C24.w)},
 cross(x){for(let i=0;i<10;i++){sR(x,6+i,6+i,3,3,C24.r);sR(x,15-i,6+i,3,3,C24.r)}},
 part(x){for(let px=4;px<20;px++)for(let py=4;py<20;py++)
   if((px+py)%2===0)sR(x,px,py,1,1,C24.g)},
 alert(x){for(let y=3;y<=20;y++){const hw=1+Math.round((y-3)*.5);
   sR(x,12-hw,y,hw*2,1,C24.y)}
  sR(x,11,8,2,6,C24.k);sR(x,11,16,2,2,C24.k)},
 star(x){const pts=[];
  for(let i=0;i<10;i++){const a=-Math.PI/2+i*Math.PI/5,r=i%2?4.6:10;
    pts.push([12+r*Math.cos(a),11.6+r*Math.sin(a)])}
  sPoly(x,pts,C24.y)},
 flame(x){sE(x,12,15,7,7,C24.o);
  for(let i=0;i<7;i++){const w=1+Math.round(i*.9);sR(x,12-Math.floor(w/2),3+i,w,1,C24.o)}
  sR(x,17,6,2,2,C24.o);sR(x,18,8,2,3,C24.o);
  sE(x,12,16,5,5.4,C24.r);
  for(let i=0;i<4;i++){const w=1+i;sR(x,12-Math.floor(w/2),8+i,w,1,C24.r)}
  sE(x,12,17,3,3.6,C24.y)},
 gear(x){sE(x,12,12,8,8,C24.l);
  sR(x,10,1,4,3,C24.l);sR(x,10,20,4,3,C24.l);sR(x,1,10,3,4,C24.l);sR(x,20,10,3,4,C24.l);
  sR(x,4,4,3,3,C24.l);sR(x,17,4,3,3,C24.l);sR(x,4,17,3,3,C24.l);sR(x,17,17,3,3,C24.l);
  cEll(x,12,12,3.2,3.2)},
 chart(x){sR(x,3,3,2,16,C24.k);sR(x,3,19,18,2,C24.k);
  sR(x,8,13,3,6,C24.v);sR(x,13,9,3,10,C24.b);sR(x,18,5,3,14,C24.g)},
 calc(x){sR(x,4,2,16,20,C24.v);sR(x,6,4,12,4,C24.w);
  for(let r=0;r<3;r++)for(let c=0;c<3;c++)
    sR(x,6+c*4,10+r*4,3,3,(r===2&&c===2)?C24.o:C24.w)},
 mail(x){sR(x,3,5,18,14,C24.w);
  for(let i=0;i<8;i++){sR(x,4+i,6+i,2,2,C24.b);sR(x,18-i,6+i,2,2,C24.b)}},
 clock(x){sE(x,12,12,9.4,9.4,C24.w);
  sR(x,11,6,2,7,C24.k);sR(x,12,11,5,2,C24.k);sR(x,11,11,2,2,C24.k)},
 person(x){sE(x,12,5,3.2,3.8,C24.w);
  for(let y=10;y<=21;y++){const w=6+Math.round((y-10)*(10/11));
    sR(x,12-Math.floor(w/2),y,w,1,C24.w)}
  for(let y=19;y<=21;y++){const hw=1+(3-(21-y));x.clearRect(12-hw,y,hw*2,1)}},
 catvader(x){const v=C24.v;
  for(let i=0;i<5;i++){sR(x,4,3+i,1+i,1,v);sR(x,19-i,3+i,1+i,1,v)}
  sR(x,3,8,18,9,v);sR(x,4,17,16,2,v);
  x.clearRect(7,17,2,2);x.clearRect(15,17,2,2);
  sR(x,6,19,3,2,v);sR(x,11,19,2,2,v);sR(x,15,19,3,2,v);
  sR(x,6,10,3,3,C24.w);sR(x,15,10,3,3,C24.w)},
 press(x){sR(x,7,2,10,5,C24.w);sR(x,3,7,18,8,C24.l);
  sR(x,18,8,2,2,C24.g);sR(x,7,15,10,6,C24.w);sR(x,9,17,6,2,C24.b)},
 link(x){sR(x,4,6,9,6,C24.b);x.clearRect(6,8,5,2);
  sR(x,11,12,9,6,C24.b);x.clearRect(13,14,5,2)},
 books(x){sR(x,4,5,4,14,C24.b);sR(x,9,7,4,12,C24.g);sR(x,14,9,4,10,C24.v);
  sR(x,3,19,18,2,C24.k);
  sR(x,5,9,2,2,C24.w);sR(x,10,11,2,2,C24.w);sR(x,15,12,2,2,C24.w)},
 money(x){sR(x,3,7,18,10,C24.g);sE(x,12,12,3.4,3,C24.w);
  sR(x,5,9,2,2,C24.w);sR(x,17,13,2,2,C24.w)},
 box(x){sR(x,4,5,16,14,C24.o);sR(x,11,5,2,5,'#a24e12');
  sR(x,4,10,16,1,'#a24e12');sR(x,6,14,5,3,C24.w)},
 truck(x){sR(x,3,8,12,8,C24.b);sR(x,15,10,5,6,C24.l);sR(x,16,11,3,3,C24.w);
  sE(x,7,18,2.4,2.4,C24.k);sE(x,17,18,2.4,2.4,C24.k)},
 phone(x){sR(x,8,3,8,18,C24.w);sR(x,10,5,4,1,C24.k);sR(x,11,18,2,2,C24.b)},
 bulb(x){sE(x,12,8,5.8,6.2,C24.y);sR(x,9,5,2,2,C24.w);
  sR(x,10,15,4,3,C24.l);sR(x,11,18,2,2,C24.l)},
 key(x){sE(x,8,8,4.4,4.4,C24.y);cEll(x,8,8,2,2);
  sR(x,12,7,9,2,C24.y);sR(x,16,9,2,3,C24.y);sR(x,19,9,2,2,C24.y)},
 heart(x){sE(x,8,9,4.6,4.4,C24.r);sE(x,16,9,4.6,4.4,C24.r);
  for(let y=10;y<=19;y++){const w=Math.max(0,19-(y-10)*2);
    if(w>0)sR(x,12-Math.floor(w/2),y,w,1,C24.r)}
  sR(x,6,6,2,2,C24.w)}
};
function shadePass(ctx,S){
  const img=ctx.getImageData(0,0,S,S),d=img.data;
  for(let y=0;y<S;y++)for(let x=0;x<S;x++){
    const i=(y*S+x)*4;
    if(d[i+3]===0)continue;
    if(d[i]===255&&d[i+1]===255&&d[i+2]===255)continue;
    if(d[i]===25&&d[i+1]===26&&d[i+2]===28)continue;
    if(y>=S*.55&&(x+y)%2===0){d[i]*=.72;d[i+1]*=.72;d[i+2]*=.72}}
  ctx.putImageData(img,0,0)}
function outlinePass(ctx,S,col){
  const img=ctx.getImageData(0,0,S,S),d=img.data;
  const a=(x,y)=>(x<0||y<0||x>=S||y>=S)?0:d[(y*S+x)*4+3];
  const mark=[];
  for(let y=0;y<S;y++)for(let x=0;x<S;x++){
    const i=(y*S+x)*4;
    if(d[i+3]===0)continue;
    if(a(x-1,y)===0||a(x+1,y)===0||a(x,y-1)===0||a(x,y+1)===0)mark.push(i)}
  const oc=col||[25,26,28];mark.forEach(i=>{d[i]=oc[0];d[i+1]=oc[1];d[i+2]=oc[2];d[i+3]=255});
  ctx.putImageData(img,0,0)}
/* v1.4 form shading (chosen 2026-09-05, lab variant D): 4-tone ramps with hue shift,
   1px shade ring along bottom/right edges, dithered second ring, one light pixel top-left, ink outline. */
function rgb2hsl(r,g,b){r/=255;g/=255;b/=255;const M=Math.max(r,g,b),m=Math.min(r,g,b);let h=0,s=0;const l=(M+m)/2;
  if(M!==m){const d=M-m;s=l>.5?d/(2-M-m):d/(M+m);switch(M){case r:h=(g-b)/d+(g<b?6:0);break;case g:h=(b-r)/d+2;break;default:h=(r-g)/d+4}h/=6}return [h*360,s,l]}
function hsl2rgb(h,s,l){h=((h%360)+360)%360/360;const f=(p,q,t)=>{if(t<0)t+=1;if(t>1)t-=1;if(t<1/6)return p+(q-p)*6*t;if(t<1/2)return q;if(t<2/3)return p+(q-p)*(2/3-t)*6;return p};
  if(s===0){const v=Math.round(l*255);return [v,v,v]}const q=l<.5?l*(1+s):l+s-l*s,p=2*l-q;return [Math.round(f(p,q,h+1/3)*255),Math.round(f(p,q,h)*255),Math.round(f(p,q,h-1/3)*255)]}
const clamp01=(v,a,b)=>Math.max(a,Math.min(b,v));
const RAMP={};
function ramp(rgb){const k=rgb.join(',');if(RAMP[k])return RAMP[k];const [h,s,l]=rgb2hsl(rgb[0],rgb[1],rgb[2]);const gray=s<.12;
  RAMP[k]={light:hsl2rgb(gray?h:h-4,gray?s:clamp01(s-.06,0,1),clamp01(l+.10,0,.96)),
           shade:hsl2rgb(gray?h:h+10,gray?s:clamp01(s+.06,0,1),clamp01(l-.14,.06,1)),
           line:hsl2rgb(gray?h:h+16,gray?s:clamp01(s+.08,0,1),clamp01(l-.30,.05,1))};return RAMP[k]}
function formPass(ctx,S){
  const img=ctx.getImageData(0,0,S,S),d=img.data;
  const a=(x,y)=>(x<0||y<0||x>=S||y>=S)?0:d[(y*S+x)*4+3];
  const src=new Uint8ClampedArray(d);
  const dd=[],dr=[];
  for(let y=0;y<S;y++){dd.push([]);dr.push([]);for(let x=0;x<S;x++){
    if(!a(x,y)){dd[y].push(0);dr[y].push(0);continue}
    let k=1;while(a(x,y+k))k++;dd[y].push(k);k=1;while(a(x+k,y))k++;dr[y].push(k)}}
  for(let y=0;y<S;y++)for(let x=0;x<S;x++){
    const i=(y*S+x)*4;if(!src[i+3])continue;
    const p=[src[i],src[i+1],src[i+2]];
    if(p[0]>=250&&p[1]>=250&&p[2]>=250)continue;
    if(p[0]===25&&p[1]===26&&p[2]===28)continue;
    const edge=!a(x-1,y)||!a(x+1,y)||!a(x,y-1)||!a(x,y+1);
    const dist=Math.min(dd[y][x],dr[y][x]);
    let out=null;
    if(dist<=1)out=ramp(p).shade;else if(dist===2&&(x+y)%2===0)out=ramp(p).shade;
    if(!edge&&!a(x-1,y-1)&&!a(x,y-1)&&!a(x-1,y)&&dist>2)out=ramp(p).light;
    if(out){d[i]=out[0];d[i+1]=out[1];d[i+2]=out[2]}}
  ctx.putImageData(img,0,0)}
function drawSprite(c,name,mode,dark){
  const S=24;c.width=S;c.height=S;
  const ctx=c.getContext('2d');
  (DRAW24[name]||DRAW24.doc)(ctx);
  if(name==='part')return;
  if(mode==='legacy')shadePass(ctx,S);
  else if(mode!=='b')formPass(ctx,S);
  outlinePass(ctx,S,dark?[236,236,234]:[25,26,28]);
}
root.PixelKit=Object.assign(root.PixelKit||{},{drawSprite,DRAW24,SPRCOL,shadePass,formPass,ramp,outlinePass,names:Object.keys(DRAW24).filter(n=>n!=='part')});
})(typeof window!=='undefined'?window:globalThis);
