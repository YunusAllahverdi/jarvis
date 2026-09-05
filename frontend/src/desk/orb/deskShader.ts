/**
 * Küre kabuğunun GLSL kaynağı — tasarım dosyasından birebir taşındı.
 *
 * Neden yeniden yazılmadı: bu shader'ın görünüşü sayısal sabitlerin
 * birbirine oranından geliyor (fbm oktavları, şerit kalınlığı, ışık
 * noktalarının yeri). "Daha temiz" bir sürüm yazmak, tasarımın kabul
 * edilmiş görüntüsünü kaybetmek olurdu. Değişiklik gerekirse tasarımda
 * yapılıp buraya taşınmalı.
 *
 * Tek uniform üçlüsü vardır ve hepsi dışarıdan sürülür:
 *   t  — saniye cinsinden animasyon saati (donduğunda küre de durur)
 *   st — durum: 0 boşta, 1 dinliyor, 2 düşünüyor, 3 yanıtlıyor.
 *        Tam sayı DEĞİL: geçiş yumuşasın diye aradaki değerler de gelir.
 *   sz — normalleştirilmiş yarıçap; küçük kürede parlaklık artar, aksi
 *        hâlde 66 piksellik küre sönük bir leke gibi görünürdü.
 */

export const DESK_VERT = [
  'attribute vec2 p;varying vec2 uv;',
  'void main(){uv=p;gl_Position=vec4(p,0.0,1.0);}',
].join('\n');

export const DESK_FRAG = [
  'precision highp float;',
  'varying vec2 uv;',
  'uniform float t;uniform float st;uniform float sz;',
  'float h(vec3 p){p=fract(p*0.3183099+vec3(0.11,0.27,0.53));p*=17.0;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}',
  'float n3(vec3 x){vec3 i=floor(x);vec3 f=fract(x);f=f*f*(3.0-2.0*f);',
  ' float a=mix(mix(mix(h(i),h(i+vec3(1,0,0)),f.x),mix(h(i+vec3(0,1,0)),h(i+vec3(1,1,0)),f.x),f.y),',
  '  mix(mix(h(i+vec3(0,0,1)),h(i+vec3(1,0,1)),f.x),mix(h(i+vec3(0,1,1)),h(i+vec3(1,1,1)),f.x),f.y),f.z);return a;}',
  'float fbm(vec3 p){float s=0.0;float a=0.5;for(int i=0;i<4;i++){s+=a*n3(p);p*=2.03;p.xy+=vec2(1.7,-2.3);a*=0.5;}return s;}',
  'vec3 ramp(float x){x=clamp(x,0.0,1.0);',
  ' vec3 c0=vec3(0.10,0.30,0.90);vec3 c1=vec3(0.26,0.78,0.99);',
  ' vec3 c2=vec3(0.92,0.96,1.00);vec3 c3=vec3(0.99,0.76,0.36);',
  ' float k=x*3.0;vec3 c=mix(c0,c1,clamp(k,0.0,1.0));c=mix(c,c2,clamp(k-1.0,0.0,1.0));',
  ' c=mix(c,c3,clamp(k-2.0,0.0,1.0));return c;}',
  'void main(){',
  ' vec2 q=uv;float r=length(q);',
  ' if(r>1.005){gl_FragColor=vec4(0.0);return;}',
  ' float z=sqrt(max(0.0,1.0-min(r*r,1.0)));',
  ' float act=mix(0.7,2.0,clamp(st/3.0,0.0,1.0));',
  ' float gather=smoothstep(0.35,1.0,st)*(1.0-smoothstep(1.0,2.0,st));',
  ' float bright=0.95+0.65*smoothstep(2.1,3.0,st);',
  ' float complx=1.0+0.9*smoothstep(1.4,2.6,st);',
  ' vec2 rq=q*(0.72+0.44*(1.0-z));',
  ' vec3 p=vec3(rq*1.5,z*0.8-0.28);',
  ' float tt=t*0.13*act;',
  ' vec3 w1=vec3(fbm(p*1.2+vec3(0.0,0.6,tt)),fbm(p*1.2+vec3(5.2,1.3,tt*1.31)),fbm(p*1.0+vec3(2.7,8.3,tt*0.79)));',
  ' vec3 p2=p+(w1-0.5)*(1.2*complx);',
  ' float d=fbm(p2*2.2+vec3(0.0,0.0,tt*1.7));',
  ' float x=rq.x;',
  ' float syl=fbm(vec3(t*0.62,3.7,0.0))*1.75-0.34;',
  ' float talk=clamp(syl,0.0,1.0);talk=talk*talk*(3.0-2.0*talk);talk=mix(talk,0.5+0.5*sin(t*0.31+syl*2.0),0.35);',
  ' float voice=mix(0.22,1.0,talk)*mix(0.65,1.25,clamp(st/3.0,0.0,1.0));',
  ' float env=exp(-x*x*1.7)*(0.055+0.075*voice+0.02*complx);',
  ' float ph=t*(0.16+0.24*talk)*act;',
  ' float wv=env*(0.58*sin(x*3.4+ph+w1.x*2.2)+0.28*sin(x*6.1-ph*0.71+w1.y*2.8)+0.11*sin(x*10.4+ph*1.19+d*3.2));',
  ' float thick=(0.038+0.026*fbm(p2*1.5+vec3(tt*1.3,0.0,0.0)))*(0.78+0.34*talk);',
  ' float y=rq.y*(1.0+0.15*sin(t*0.09));',
  ' float ribbons=0.0;float hue=0.0;',
  ' for(int i=0;i<3;i++){',
  '  float fi=float(i);',
  '  float off=(fi-1.0)*0.030*(0.55+0.85*voice);',
  '  float wvi=wv*(1.0+0.22*fi)+off;',
  '  float dy=(y-wvi)/(thick*(1.0+0.35*fi));',
  '  float g=exp(-dy*dy);',
  '  ribbons+=g*(1.0-0.22*fi);',
  '  hue+=g*(0.04+0.15*fi+0.20*(x*0.5+0.5)+0.12*d);',
  ' }',
  ' float mask=mix(1.0,exp(-r*r*2.0),gather*0.9);',
  ' float energy=clamp(ribbons,0.0,1.1)*mask*(1.0-0.30*smoothstep(0.65,1.0,r));',
  ' float hueF=(ribbons>0.001)?hue/ribbons:0.5;',
  ' hueF=clamp(hueF+0.06*sin(t*0.05),0.0,1.0);',
  ' vec3 col=ramp(hueF)*energy*bright*(0.78+0.45*(1.0-sz));',
  ' col+=vec3(1.0,0.99,0.97)*pow(clamp(ribbons,0.0,1.0),4.0)*0.30*bright;',
  ' float fres=pow(1.0-z,3.0);',
  ' col+=vec3(0.055,0.065,0.085)*(0.35+0.65*z);',
  ' col+=vec3(0.72,0.80,0.96)*fres*(0.48+0.35*(1.0-sz));',
  ' vec2 sp=vec2(-0.33,0.40)+vec2(wv,d-0.5)*0.14;',
  ' float spec=exp(-pow(length(q-sp)*4.0,2.0));',
  ' col+=vec3(1.0)*spec*(0.78+0.30*energy);',
  ' float spec2=exp(-pow(length(q-sp*1.06)*11.0,2.0));',
  ' col+=vec3(1.0)*spec2*0.50;',
  ' float und=exp(-pow(length(q-vec2(0.02*sin(t*0.07),-0.60))*3.1,2.0));',
  ' col+=vec3(0.66,0.78,1.0)*und*(0.20+0.26*energy);',
  ' float a=smoothstep(1.0,0.982,r);',
  ' gl_FragColor=vec4(col,a);',
  '}',
].join('\n');
