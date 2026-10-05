const $ = id => document.getElementById(id);
const DAY = 86400000;
const ranges = {'1d':'1 ngày','1w':'1 tuần','1m':'1 tháng','3m':'3 tháng','6m':'6 tháng','1y':'1 năm'};
const colors = {domestic:'#e5b964',gold:'#8daeff',fx:'#83ccb8'};
const kinds = {snapshot:'Bản ghi khi thu thập',close:'Giá đóng cửa',source_day:'Mốc ngày tổng hợp từ nguồn',source_month:'Mốc tháng tổng hợp từ nguồn',intraday:'Giá trong ngày từ nguồn'};
let payload, range = '1m', goldType = '985';
const formats = {domestic:new Intl.NumberFormat('vi-VN',{maximumFractionDigits:0}),gold:new Intl.NumberFormat('vi-VN',{minimumFractionDigits:2,maximumFractionDigits:2}),fx:new Intl.NumberFormat('vi-VN',{maximumFractionDigits:2})};
const fmt = (value,id) => Number.isFinite(value) ? formats[id].format(value) : '—';
const dateLabel = date => date.split('-').reverse().join('/');
const vnDay = date => new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
const collectedLabel = date => new Date(date).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit',year:'numeric'});
const escape = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function cutoff(end,key){
  const date=new Date(end+'T00:00:00Z');
  if(key==='1w')date.setUTCDate(date.getUTCDate()-6);
  else if(key!=='1d'){
    const day=date.getUTCDate(), months={'1m':1,'3m':3,'6m':6,'1y':12}[key];
    date.setUTCDate(1);date.setUTCMonth(date.getUTCMonth()-months);
    const last=new Date(Date.UTC(date.getUTCFullYear(),date.getUTCMonth()+1,0)).getUTCDate();date.setUTCDate(Math.min(day,last));
  }
  return date.toISOString().slice(0,10);
}
function selectedPoints(m){
  const end=vnDay(new Date()),start=cutoff(end,range);
  if(range==='1d'){
    // The last available session is explicit; never invent today's prices on a closed market.
    const session=m.latest?.date || end;
    const intraday=(m.intraday||[]).filter(p=>p.date===session);
    const points=intraday.length ? intraday : (m.latest?[m.latest]:[]);
    const last=points.at(-1);
    if(m.latest && last && m.latest.time && new Date(m.latest.time)>new Date(last.time)) points.push(m.latest);
    return {points,session,start:session,end:session};
  }
  const daily=m.history||[], firstDaily=daily[0]?.date||end;
  const monthly=(m.monthly||[]).filter(p=>p.date<firstDaily && ['3m','6m','1y'].includes(range));
  const points=[...monthly,...daily].filter(p=>p.date>=start&&p.date<=end).sort((a,b)=>a.date.localeCompare(b.date));
  return {points,start,end};
}
function priceMarkup(value,id,unit){return `${fmt(value,id)}<span>${unit}</span>`;}
function renderMarket(id,m){
  const unit=id==='domestic'?'VND / chỉ':id==='gold'?'USD / ounce troy':'VND';
  $(id+'-price').innerHTML=priceMarkup(m.latest?.value,id,unit);
  if(id==='domestic')$('domestic-buy').textContent=fmt(m.latest?.buy,id);
  const chosen=selectedPoints(m),p=chosen.points;
  const change=$(id+'-change');
  if(p.length>=2){
    const delta=p.at(-1).value-p[0].value,pct=delta/p[0].value*100;
    change.className='period-change '+(delta>0?'up':delta<0?'down':'neutral');
    change.innerHTML=`${delta>0?'+':''}${new Intl.NumberFormat('vi-VN',{maximumFractionDigits:2,minimumFractionDigits:2}).format(pct)}%<small>trong ${ranges[range]}</small>`;
  }else{change.className='period-change neutral';change.innerHTML='—<small>Chưa đủ mốc so sánh</small>';}
  renderChart(id,p,chosen);
  const summary=$(id+'-summary');
  if(p.length){
    const values=p.map(x=>x.value), low=Math.min(...values),high=Math.max(...values);
    const mixed=p.some(x=>x.kind==='source_month');
    const note=range==='1d'?`${p.length} bản ghi · ${dateLabel(chosen.session)}`:mixed?'Mốc tháng + mốc ngày từ nguồn':`${p.length} mốc · ${dateLabel(p[0].date)} – ${dateLabel(p.at(-1).date)}`;
    summary.innerHTML=`<span>${id==='domestic'?'Bán thấp nhất':'Thấp nhất'}<b>${fmt(low,id)}</b></span><span>${id==='domestic'?'Bán cao nhất':'Cao nhất'}<b>${fmt(high,id)}</b></span><span>${escape(note)}</span>`;
  }else summary.textContent='Chưa có dữ liệu trong khoảng thời gian này.';
  const freshnessTime=id==='domestic'?m.latest?.time:m.lastSuccessAt;
  const outdated=freshnessTime && Date.now()-new Date(freshnessTime)>36*3600000;
  const status=m.status==='error'?'Nguồn tạm lỗi · ':m.status==='partial'?'Lịch sử chưa đầy đủ · ':outdated?'Dữ liệu cũ · ':'';
  const time=id==='domestic'?m.latest?.time:m.latest?.collectedAt;
  $(id+'-status').textContent=status+(time?`${id==='domestic'?'Nguồn':'Ghi nhận'}: ${collectedLabel(time)}`:'Chưa có bản ghi');
  return p;
}
function renderChart(id,points,chosen){
  const host=$(id+'-chart');host.replaceChildren();
  host.onpointermove=null;host.onpointerleave=null;host.onkeydown=null;
  if(!points.length){host.innerHTML='<div class="empty"><div><strong>Chưa có dữ liệu</strong>Nguồn chưa cung cấp bản ghi trong khoảng đã chọn.</div></div>';return;}
  const w=Math.max(host.clientWidth,260),h=host.clientHeight,left=10,right=w<500?68:84,top=16,bottom=34,plotW=w-left-right,plotH=h-top-bottom;
  const isDay=range==='1d';
  const times=points.map(p=>new Date(isDay?(p.time||p.date+'T12:00:00+07:00'):p.date+'T00:00:00Z').getTime());
  let minTime=isDay?Math.min(...times):new Date(chosen.start+'T00:00:00Z').getTime(), maxTime=isDay?Math.max(...times):new Date(chosen.end+'T00:00:00Z').getTime();
  if(minTime===maxTime){minTime-=3600000;maxTime+=3600000;}
  const values=points.flatMap(p=>id==='domestic'?[p.value,p.buy]:[p.value]).filter(Number.isFinite);
  const min=Math.min(...values),max=Math.max(...values),pad=Math.max((max-min)*.18,max*.0015),lo=min-pad,hi=max+pad;
  const x=t=>left+(t-minTime)/(maxTime-minTime)*plotW,y=v=>top+(hi-v)/(hi-lo)*plotH;
  let svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${escape(id==='domestic'?'Vàng '+goldType:id==='gold'?'Vàng quốc tế':'USD/VND')}, ${points.length} mốc dữ liệu, ${ranges[range]}"><defs><linearGradient id="fill-${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${colors[id]}" stop-opacity=".15"/><stop offset="100%" stop-color="${colors[id]}" stop-opacity="0"/></linearGradient></defs>`;
  for(let i=0;i<4;i++){
    const v=lo+(hi-lo)*i/3,yy=y(v);
    const label=id==='domestic'?new Intl.NumberFormat('vi-VN',{maximumFractionDigits:2}).format(v/1e6)+' tr':new Intl.NumberFormat('vi-VN',{maximumFractionDigits:id==='gold'?0:0}).format(v);
    svg+=`<line x1="${left}" x2="${w-right}" y1="${yy}" y2="${yy}" stroke="#354043" stroke-dasharray="3 5"/><text x="${w-right+12}" y="${yy+4}">${label}</text>`;
  }
  const line=(field,color,dashed=false)=>{
    let segments=[],segment=[];
    points.forEach((p,i)=>{
      const gap=i>0?(times[i]-times[i-1])/DAY:0;
      const monthly=p.kind==='source_month'||points[i-1]?.kind==='source_month';
      if(!Number.isFinite(p[field])||(i>0&&!isDay&&gap>(monthly?45:4))){if(segment.length)segments.push(segment);segment=[];}
      if(Number.isFinite(p[field]))segment.push([x(times[i]),y(p[field])]);
    });
    if(segment.length)segments.push(segment);
    return segments.map(coords=>{
      const d=coords.map((c,i)=>(i?'L':'M')+c.join(',')).join(' ');
      let part='';
      if(!dashed&&coords.length>1)part=`<path d="${d} L${coords.at(-1)[0]},${top+plotH} L${coords[0][0]},${top+plotH} Z" fill="url(#fill-${id})"/>`;
      part+=`<path d="${d}" stroke="${color}" stroke-width="${dashed?1.7:2.3}" fill="none" ${dashed?'stroke-dasharray="5 4"':''} stroke-linejoin="round"/>`;
      if(coords.length<3)part+=coords.map(c=>`<circle cx="${c[0]}" cy="${c[1]}" r="4" fill="${color}"/>`).join('');
      return part;
    }).join('');
  };
  svg+=line('value',colors[id]);if(id==='domestic')svg+=line('buy','#a69877',true);
  const tickCount=w<450?3:5;
  for(let i=0;i<tickCount;i++){
    const t=minTime+(maxTime-minTime)*i/(tickCount-1),date=new Date(t);
    const text=isDay?date.toLocaleTimeString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit'}):date.toLocaleDateString('vi-VN',{timeZone:'UTC',day:'2-digit',month:'2-digit'});
    svg+=`<text x="${x(t)}" y="${h-9}" text-anchor="${i===0?'start':i===tickCount-1?'end':'middle'}">${text}</text>`;
  }
  if(points.length===1)svg+=`<text x="${left+plotW/2}" y="${top+24}" text-anchor="middle">Một lần ghi nhận trong ngày</text>`;
  svg+=`<g class="cursor" visibility="hidden"><line y1="${top}" y2="${top+plotH}" stroke="#99a6a6" stroke-dasharray="3 4"/><circle r="4" fill="${colors[id]}" stroke="#172123" stroke-width="2"/></g></svg><div class="tooltip" hidden role="status" aria-live="polite"></div>`;
  host.innerHTML=svg;
  const tip=host.querySelector('.tooltip'),cursor=host.querySelector('.cursor');let current=points.length-1;
  const show=i=>{
    current=Math.max(0,Math.min(points.length-1,i));const p=points[current],xx=x(times[current]),yy=y(p.value);
    cursor.setAttribute('visibility','visible');cursor.querySelector('line').setAttribute('x1',xx);cursor.querySelector('line').setAttribute('x2',xx);cursor.querySelector('circle').setAttribute('cx',xx);cursor.querySelector('circle').setAttribute('cy',yy);
    const time=isDay&&p.time?' · '+new Date(p.time).toLocaleTimeString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit'}):'';
    tip.innerHTML=`<strong>${dateLabel(p.date)}${time}</strong>${id==='domestic'?'Bán: ':''}${fmt(p.value,id)}${id==='domestic'?'<br>Mua: '+fmt(p.buy,id):''}<small>${escape(kinds[p.kind]||'Giá từ nguồn')}</small>`;
    tip.hidden=false;tip.style.left=Math.max(0,Math.min(xx+12,w-tip.offsetWidth))+'px';tip.style.top=Math.max(0,Math.min(yy-70,h-tip.offsetHeight-30))+'px';
  };
  host.onpointermove=e=>{const px=e.clientX-host.getBoundingClientRect().left;let best=0;times.forEach((t,i)=>{if(Math.abs(x(t)-px)<Math.abs(x(times[best])-px))best=i;});show(best);};
  host.onpointerleave=()=>{tip.hidden=true;cursor.setAttribute('visibility','hidden');};
  host.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End','Escape'].includes(e.key)){e.preventDefault();if(e.key==='Escape'){host.onpointerleave();return;}show(e.key==='Home'?0:e.key==='End'?points.length-1:current+(e.key==='ArrowRight'?1:-1));}};
}
function renderTables(all){
  $('table-content').innerHTML=Object.entries(all).map(([id,points])=>`<table><caption>${id==='domestic'?'Mi Hồng '+goldType:id==='gold'?'Vàng quốc tế':'USD/VND'} · ${ranges[range]} · ${id==='domestic'?'VND/chỉ':id==='gold'?'USD/ounce troy':'VND/USD'}</caption><thead><tr><th scope="col">Ngày</th>${id==='domestic'?'<th scope="col">Mua vào</th>':''}<th scope="col">${id==='domestic'?'Bán ra':'Giá'}</th><th scope="col">Loại bản ghi</th></tr></thead><tbody>${[...points].reverse().map(p=>`<tr><td>${dateLabel(p.date)}${range==='1d'&&p.time?' '+new Date(p.time).toLocaleTimeString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit'}):''}</td>${id==='domestic'?'<td>'+fmt(p.buy,id)+'</td>':''}<td>${fmt(p.value,id)}</td><td>${escape(kinds[p.kind]||'Giá từ nguồn')}</td></tr>`).join('')||'<tr><td colspan="4">Chưa có dữ liệu.</td></tr>'}</tbody></table>`).join('');
}
function render(){
  if(!payload)return;
  const all={};for(const id of ['domestic','gold','fx'])all[id]=renderMarket(id,payload.markets[id==='domestic'?goldType:id]||{});renderTables(all);
}
async function load(){
  try{
    const response=await fetch('./data/market.json',{cache:'no-cache'});if(!response.ok)throw Error('HTTP '+response.status);
    payload=await response.json();if(payload.schemaVersion!==1||!payload.markets)throw Error('Invalid data');
    $('last-update').textContent=payload.updatedAt?'Ghi nhận: '+collectedLabel(payload.updatedAt):'Chưa có dữ liệu';
    const failed=Object.values(payload.markets).filter(m=>m.status!=='ok');
    const stale=!payload.updatedAt||Date.now()-new Date(payload.updatedAt)>36*3600000;
    if(failed.length||stale){$('load-error').hidden=false;$('load-error').textContent=failed.length?'Một số nguồn chưa cập nhật đầy đủ. Trang đang giữ dữ liệu thành công gần nhất; xem thời điểm ở từng biểu đồ.':'Dữ liệu đã quá 36 giờ. Lịch cập nhật có thể đang chậm; xem thời điểm ghi nhận ở từng biểu đồ.';}
    render();
  }catch{ $('load-error').hidden=false;$('load-error').textContent='Không tải được dữ liệu. Hãy tải lại trang hoặc kiểm tra lần cập nhật GitHub Actions gần nhất.';$('last-update').textContent='Chưa tải được dữ liệu';for(const id of ['domestic','gold','fx'])$(id+'-status').textContent='Chưa tải được dữ liệu'; }
}
document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{range=button.dataset.range;document.querySelectorAll('[data-range]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));render();}));
$('gold-type').addEventListener('change',event=>{goldType=event.target.value;render();});
let resizeTimer;new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(render,100);}).observe(document.querySelector('main'));
load();
