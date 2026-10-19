// Prueba de humo del frontend en Node + jsdom (sin navegador). Uso: npm i jsdom@24 && node tests/smoke_frontend.js demo/site
// ECharts se sustituye por un doble de prueba que registra las opciones y ejecuta los formateadores de tooltip.
const {JSDOM}=require('jsdom'),fs=require('fs'),path=require('path');
const root=process.argv[2];
let html=fs.readFileSync(path.join(root,'index.html'),'utf8').replace(/<script src="http[^"]+"><\/script>/g,'').replace('<script src="assets/app.js"></script>','');
const dom=new JSDOM(html,{runScripts:'outside-only',pretendToBeVisual:true,url:'http://localhost/'});
const w=dom.window; const errors=[]; const opts={};
w.console.error=(...a)=>errors.push(a.join(' ')); w.onerror=(m)=>errors.push(String(m));
w.matchMedia=()=>({matches:false,addEventListener(){}}); w.Element.prototype.scrollIntoView=()=>{};
w.fetch=async(u)=>{const p=path.join(root,u.split('?')[0]);return{ok:fs.existsSync(p),status:fs.existsSync(p)?200:404,json:async()=>JSON.parse(fs.readFileSync(p,'utf8'))}};
const inst=new Map();
w.echarts={registerMap(){},getInstanceByDom:(el)=>inst.get(el),init:(el)=>{const c={setOption(o){ // force formatter execution
  opts[el.id||'x']=o; if(o.tooltip&&typeof o.tooltip.formatter==='function'&&o.series&&o.series[0]){try{const s=o.series.find(x=>x.name==='Precio')||o.series[0];o.tooltip.formatter(o.tooltip.trigger==='item'?{data:s.data&&s.data[0],name:'n'}:[{seriesName:s.name,dataIndex:0,value:1,data:[0,0,0.5]}])}catch(e){errors.push('formatter '+el.id+': '+e.message)}}
  if(o.series) o.series.forEach(s=>{ if(typeof s.symbolSize==='function'&&s.data[0]) s.symbolSize(0,{data:s.data[0]}); });
},clear(){},resize(){}};inst.set(el,c);return c}};
w.eval(fs.readFileSync(path.join(root,'assets/app.js'),'utf8'));
setTimeout(async()=>{
  const d=w.document;
  for(const t of ['exec','monitor','risk','trends','alerts','procure','news','sources']){ d.querySelector(`#tabs button[data-tab="${t}"]`).click(); await new Promise(r=>setTimeout(r,50)); }
  d.querySelector('#tabs button[data-tab="monitor"]').click();
  const card=d.querySelector('.card'); card.click();
  d.querySelector('input[data-cmp]').click(); d.querySelector('#btn-compare').click();
  for(const p of ['7','30','90','1095']){ const s=d.querySelector('#f-period'); s.value=p; s.dispatchEvent(new w.Event('change')); }
  d.querySelector('#tabs button[data-tab="procure"]').click(); const pr=d.querySelector('#sim-price'); pr.value='300'; pr.dispatchEvent(new w.Event('input',{bubbles:true}));
  d.querySelector('#tabs button[data-tab="alerts"]').click(); const th=d.querySelector('#th-zscore'); th.value='1'; th.dispatchEvent(new w.Event('input',{bubbles:true}));
  d.querySelector('[data-ack]')?.click();
  console.log('headline:',d.querySelector('#exec-headline').textContent);
  console.log('sync:',d.querySelector('#sync-text').textContent);
  console.log('cards:',d.querySelectorAll('.card').length,'alerts:',d.querySelectorAll('.alert').length,'events:',d.querySelectorAll('.event').length,'news:',d.querySelectorAll('.news').length);
  console.log('sim:',d.querySelector('#sim-out .big').textContent.trim(),'|',d.querySelector('#sim-scen').textContent.slice(0,120));
  console.log('basket:',d.querySelector('#basket-out').textContent.slice(0,140));
  console.log('demo banner hidden:',d.querySelector('#demo-banner').hidden);
  const real=errors.filter(e=>!e.startsWith('formatter ch-corr'));
  console.log('ERRORS:',real.length?real:'none'); process.exit(real.length?1:0);
},1500);
