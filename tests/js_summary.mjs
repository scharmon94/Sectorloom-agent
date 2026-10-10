import {readFileSync} from 'fs';
import {parseIBT, buildSession} from './js_parser.mjs';
const buf=readFileSync(process.argv[2]);
const ab=buf.buffer.slice(buf.byteOffset,buf.byteOffset+buf.byteLength);
const s=buildSession(parseIBT(ab),{file:'synthetic.ibt',date:'2026-10-01T19:30:00'});
const pick=[0,250,500,750,999];
const sum=a=>{let t=0;for(let i=0;i<a.length;i++)t+=a[i];return +t.toFixed(4);};
console.log(JSON.stringify({
  track:s.track, car:s.car, driver:s.driver, sessionType:s.sessionType,
  trackKey:s.trackKey, bestId:s.bestId,
  cond:s.cond,
  laps:s.laps.map(l=>({num:l.num,time:l.time==null?null:+l.time.toFixed(6),pit:l.pit,off:l.off,
    complete:l.complete,clean:l.clean,stint:l.stint,best:l.best,
    fuel:l.fuel==null?null:+l.fuel.toFixed(6),
    sec:l.sec?l.sec.map(v=>v==null?null:+v.toFixed(5)):null,
    g:l.g?{t:pick.map(i=>+l.g.t[i].toFixed(4)),spd:pick.map(i=>+l.g.spd[i].toFixed(4)),
           thr:pick.map(i=>+l.g.thr[i].toFixed(4)),brk:pick.map(i=>+l.g.brk[i].toFixed(4)),
           gear:pick.map(i=>+l.g.gear[i].toFixed(4)),
           longg:l.g.longg?pick.map(i=>+l.g.longg[i].toFixed(4)):null,
           slip:l.g.slip?pick.map(i=>+l.g.slip[i].toFixed(5)):null,
           slipa:l.g.slipa?pick.map(i=>+l.g.slipa[i].toFixed(4)):null,
           yawr:l.g.yawr?pick.map(i=>+l.g.yawr[i].toFixed(5)):null,
           abs:l.g.abs?sum(l.g.abs):null,
           slipsum:l.g.slip?sum(l.g.slip):null,
           x:l.g.x?pick.map(i=>+l.g.x[i].toFixed(2)):null,
           tsum:sum(l.g.t),spdsum:sum(l.g.spd)}:null})),
  stints:s.stints.map(st=>({no:st.no,firstLap:st.firstLap,lastLap:st.lastLap,total:st.total,
    cleanN:st.cleanN,best:st.best==null?null:+st.best.toFixed(6),
    avg:st.avg==null?null:+st.avg.toFixed(6),sd:st.sd==null?null:+st.sd.toFixed(6),
    fuel:st.fuel==null?null:+st.fuel.toFixed(6)})),
  fuelMax:s.fuelMax==null?null:+s.fuelMax.toFixed(6),
  sectors:s.sectors||null, entry:s.entry||null, sub:s.sub||null, aids:s.aids||null,
  tyres:s.tyres?{n:s.tyres.length,first:s.tyres[0],last:s.tyres[s.tyres.length-1]}:null,
  map:s.map?{n:s.map.x.length,x0:s.map.x[0],y0:s.map.y[0],x50:s.map.x[50]}:null,
  setupKeys:Object.keys(s.setup||{})
},null,1));
