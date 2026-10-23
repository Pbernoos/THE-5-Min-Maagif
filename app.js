"use strict";
const $ = id => document.getElementById(id);
const MODEL = "browser-candle-baseline-v1", KEY = "maagif-shadow-v1";
const ORACLE = "https://data.chain.link/streams/btc-usd-twap-60s-streams";
const MAX_RECORDS = 512, STALE = 20;
const REFERENCE_KEY="maagif-reference-v1", TWAP_TOPIC="crypto_prices_twap_sixty";
const now = () => Date.now() / 1000;
const windowAt = t => Math.floor(t / 300) * 300;
const finite = x => typeof x === "number" && Number.isFinite(x);
const text = (id, value) => { $(id).textContent = value; };
const pct = x => finite(x) ? `${(100*x).toFixed(1)}%` : "—";
const DISPLAY_ZONE = "Asia/Tehran";
const localTime = (t,seconds=false) => new Date(t*1000).toLocaleTimeString("en-GB", {
  timeZone:DISPLAY_ZONE,hourCycle:"h23",hour:"2-digit",minute:"2-digit",...(seconds?{second:"2-digit"}:{})});
function localDate(t) {
  const parts=Object.fromEntries(new Intl.DateTimeFormat("en-GB",{timeZone:DISPLAY_ZONE,
    year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date(t*1000)).map(p=>[p.type,p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}
const money = x => finite(x) ? new Intl.NumberFormat("en-US", {style:"currency",currency:"USD"}).format(x) : "—";
const slug = t => `btc-updown-5m-${t}`;
const state = {paused:false,busy:false,timer:null,price:null,books:null,draft:null,lastResolve:0,
  storageError:null,firstWindow:null,records:[],lastCurrent:null,lastCurrentAt:0,lastDraftAt:0,
  chart:null,chartRange:60,chartRendered:null,
  oracle:{socket:null,heartbeat:null,retry:null,attempts:0,lastSnapshot:0,connectedAt:0,
    latest:null,reference:null,status:"Connecting to Polymarket TWAP…",notice:null,inputWindow:null}};

function validReference(r) {
  return r && Number.isInteger(r.ts)&&r.ts>0&&r.ts%300===0&&finite(r.price)&&r.price>0&&
    finite(r.captured_at)&&r.captured_at>=r.ts&&
    ["manual","polymarket-twap-boundary"].includes(r.source);
}
function loadReference() {
  try {
    const raw=localStorage.getItem(REFERENCE_KEY);
    if (!raw) return;
    const r=JSON.parse(raw);
    if(!validReference(r)) throw Error("Invalid saved reference");
    if(r.ts===windowAt(now())) state.oracle.reference=r;
  } catch(e) {state.oracle.notice="Saved reference unavailable; paste this window’s price to beat or wait for the next opening.";}
}
function saveReference(r) {
  if(!validReference(r)||r.ts!==windowAt(now())) return false;
  state.oracle.reference=r;
  try {localStorage.setItem(REFERENCE_KEY,JSON.stringify(r));}
  catch(e){state.oracle.notice="Reference works in this tab but could not be saved. Forecast journal was not changed.";}
  return true;
}
function parseReferenceInput(raw) {
  const s=String(raw).trim().replace(/^\$\s*/,"");
  if(!/^(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,18})?$/.test(s)) return null;
  const price=Number(s.replaceAll(",",""));
  return finite(price)&&price>0?price:null;
}
function setManualReference(raw,expectedWindow) {
  const ts=windowAt(now()),o=state.oracle,price=parseReferenceInput(raw);
  if(expectedWindow!==ts) {o.notice="The window changed. Copy the NEW window’s price to beat before applying it.";return false;}
  if(o.reference?.ts===ts&&o.reference.source==="polymarket-twap-boundary") {
    o.notice="An exact opening value is already available from the Polymarket TWAP feed.";return false;
  }
  if(price===null) {o.notice="Enter a positive USD price, for example 81,500.25. Percentages and odds are not the price to beat.";return false;}
  o.notice="Manually copied reference; not independently verified. Confirm it matches the linked current Polymarket window.";
  return saveReference({ts,price,source:"manual",captured_at:now(),input_text:String(raw).trim()});
}
function parseOracleMessage(m,received=now()) {
  if(!m||m.topic!==TWAP_TOPIC||!["subscribe","update"].includes(m.type)) return [];
  const p=m.payload;
  if(!p||p.symbol!=="btc/usd"||p.window_s!==60) return [];
  const rows=m.type==="subscribe"?p.data:[p];
  if(!Array.isArray(rows)||rows.length>1200) return [];
  return rows.filter(r=>r&&finite(r.value)&&r.value>0&&Number.isInteger(r.timestamp)&&
    r.timestamp%1000===0&&r.timestamp/1000<=received+2&&r.timestamp/1000>=received-600)
    .map(r=>({price:r.value,exchange_ts:r.timestamp/1000,received_at:received,
      full_accuracy_value:typeof r.full_accuracy_value==="string"&&/^\d{1,80}$/.test(r.full_accuracy_value)?r.full_accuracy_value:null}))
    .sort((a,b)=>a.exchange_ts-b.exchange_ts);
}
function ingestOracleMessage(m,received=now()) {
  const points=parseOracleMessage(m,received),o=state.oracle,ts=windowAt(received);
  if(!points.length) return false;
  o.attempts=0;o.lastSnapshot=received;
  for(const p of points) {
    if(p.exchange_ts===ts) {
      const previous=o.reference;
      if(previous?.ts===ts&&previous.source==="manual") {
        o.notice=Math.abs(previous.price-p.price)>.005?
          "The automatic opening value differs from the pasted price. Using the exact Polymarket TWAP boundary value.":
          "The pasted price agrees to the nearest cent with the automatic opening value. Using the exact feed value.";
      }
      saveReference({ts,price:p.price,source:"polymarket-twap-boundary",captured_at:received,
        full_accuracy_value:p.full_accuracy_value});
    }
    if(!o.latest||p.exchange_ts>=o.latest.exchange_ts) o.latest=p;
  }
  o.status="Polymarket BTC/USD · 60-second TWAP";
  return true;
}
function oracleMarketMatches(ts) {
  const m=state.lastCurrent,c=m?.raw?.cryptoMarketConfig;
  return Boolean(m&&m.ts===ts&&m.raw.slug===slug(ts)&&m.source===ORACLE&&
    Date.parse(m.raw.eventStartTime)/1000===ts&&Date.parse(m.raw.endDate)/1000===ts+300&&
    c?.asset==="btc"&&c.duration==="5m"&&c.twapEnabled===true&&c.twapLookbackSeconds===60);
}
function oracleComparison(t=now()) {
  const o=state.oracle,ts=windowAt(t),r=o.reference,p=o.latest;
  const reference=r&&validReference(r)&&r.ts===ts?r:null;
  const fresh=!state.paused&&o.socket?.readyState===1&&p&&p.exchange_ts>=ts&&
    p.exchange_ts<=t+2&&t-p.exchange_ts<=STALE&&t-p.received_at<=STALE;
  if(!reference||!fresh||!oracleMarketMatches(ts)) return {reference,latest:fresh?p:null,direction:null,delta:null};
  const delta=p.price-reference.price;
  // Pasted display prices may be rounded to cents. Do not invent precision at equality.
  const roundedTie=reference.source==="manual"&&Math.abs(delta)<.005;
  return {reference,latest:p,delta,direction:roundedTie?"rounded-tie":delta>=0?"up":"down"};
}
function oracleSubscription(action="subscribe") {
  return JSON.stringify({action,subscriptions:[{topic:TWAP_TOPIC,type:"update",filters:JSON.stringify({symbol:"btc/usd"})}]});
}
function stopOracle() {
  const o=state.oracle;
  clearInterval(o.heartbeat);clearTimeout(o.retry);o.heartbeat=null;o.retry=null;
  const socket=o.socket;o.socket=null;
  if(socket) {socket.onclose=null;socket.onerror=null;socket.onmessage=null;socket.close();}
}
function startOracle() {
  const o=state.oracle;
  if(state.paused||o.socket) return;
  if(typeof WebSocket==="undefined") {o.status="WebSocket unavailable in this browser";return;}
  clearTimeout(o.retry);o.retry=null;o.status="Connecting to Polymarket TWAP…";
  let socket;
  const reconnect=()=>{
    if(o.socket!==socket) return;
    stopOracle();o.status="TWAP connection unavailable — retrying; stale comparisons are hidden";
    const delay=Math.min(30000,1000*2**Math.min(o.attempts++,5));
    if(!state.paused) o.retry=setTimeout(startOracle,delay);
    renderOracle();
  };
  try {socket=new WebSocket("wss://ws-live-data.polymarket.com");o.socket=socket;o.connectedAt=now();}
  catch(e){o.status="Unable to open the public TWAP connection";o.retry=setTimeout(startOracle,10000);return;}
  socket.onopen=()=>{
    if(o.socket!==socket||state.paused) return;
    socket.send(oracleSubscription());o.connectedAt=now();
    let pulses=0;
    o.heartbeat=setInterval(()=>{
      if(o.socket!==socket||state.paused) return;
      if(socket.readyState!==1) {reconnect();return;}
      if(now()-Math.max(o.lastSnapshot,o.connectedAt)>30) {reconnect();return;}
      try {
        socket.send("PING");
        // This topic supplied snapshots but no push ticks in live checks. Refresh the
        // public subscription every 10s; no proxy, login, or alternate price source.
        if(++pulses%2===0) {socket.send(oracleSubscription("unsubscribe"));socket.send(oracleSubscription());}
      } catch(e){reconnect();}
    },5000);
  };
  socket.onmessage=event=>{
    if(o.socket!==socket||state.paused||typeof event.data!=="string"||event.data.length>300000) return;
    try {if(ingestOracleMessage(JSON.parse(event.data))) renderOracle();} catch(e){/* Ignore acknowledgements and malformed messages. */}
  };
  socket.onerror=reconnect;socket.onclose=reconnect;
  o.retry=setTimeout(()=>{if(o.socket===socket&&socket.readyState===0) reconnect();},12000);
}
function renderOracle() {
  const t=now(),ts=windowAt(t),o=state.oracle,c=oracleComparison(t);
  if(o.inputWindow!==ts) {
    const previous=o.inputWindow;
    o.inputWindow=ts;$("reference-input").value="";
    if(previous!==null) o.notice=c.reference?"New five-minute window: reference updated for the linked market.":"New five-minute window: the previous reference no longer applies. Waiting for its exact opening value.";
  }
  const automatic=c.reference?.source==="polymarket-twap-boundary";
  text("reference-window",`${localDate(ts)} · ${localTime(ts)}–${localTime(ts+300)} Tehran`);
  text("price-to-beat",c.reference?money(c.reference.price):"—");
  text("reference-source",c.reference?automatic?"Exact opening timestamp · Polymarket 60s TWAP feed":"MANUAL · copied from Polymarket; not independently verified":
    "Opening value missing. Paste this window’s price to beat below, or keep this tab open for the next boundary.");
  text("twap-price",c.latest?money(c.latest.price):"—");
  text("twap-status",state.paused?"Paused":c.latest?`Polymarket 60s TWAP · ${Math.max(0,Math.floor(t-c.latest.exchange_ts))}s old · snapshots refreshed every 10s`:o.status+" · waiting for a fresh current-window value");
  const label=c.direction==="rounded-tie"?"AT REFERENCE":c.direction?c.direction.toUpperCase():"WAITING";
  text("reference-direction",label);
  $("reference-direction").setAttribute("data-direction",["up","down"].includes(c.direction)?c.direction:"neutral");
  text("reference-delta",c.delta===null?"—":`${c.delta>=0?"+":"−"}${money(Math.abs(c.delta))} vs price to beat`);
  text("reference-detail",c.direction==="rounded-tie"?"Too close to a manually copied, potentially rounded reference to assign a reliable side.":
    c.direction?`Current TWAP is ${c.direction==="up"?c.delta===0?"equal to":"above":"below"} this window’s reference. Live position only, NOT a prediction or an official result.`:
      oracleMarketMatches(ts)?"Both a current-window reference and a fresh matching TWAP value are required. Coinbase is never used for this comparison.":
        "Waiting for matching current-window market metadata: exact time range, BTC/USD, Chainlink source and 60s TWAP configuration. No side is assigned without it.");
  text("reference-notice",o.notice||"");$("reference-notice").hidden=!o.notice;
  $("reference-input").disabled=automatic;$("apply-reference").disabled=automatic||state.paused;
}

function validRecord(r) {
  return r && Number.isInteger(r.ts) && r.ts>0 && r.ts%300===0 && r.model===MODEL &&
    finite(r.p_up) && r.p_up>=0 && r.p_up<=1 && finite(r.issued_at) && finite(r.stored_at) &&
    r.ts-20<=r.issued_at && r.issued_at<=r.stored_at && r.stored_at<r.ts &&
    finite(r.feature_cutoff) && r.feature_cutoff<=r.ts-60 &&
    (r.up===null || r.up===0 || r.up===1);
}
function loadJournal() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return;
    const j = JSON.parse(raw);
    if (!Array.isArray(j.records) || j.records.length>MAX_RECORDS || !j.records.every(validRecord) ||
        new Set(j.records.map(r=>r.ts)).size!==j.records.length || !Number.isInteger(j.firstWindow) || j.firstWindow%300!==0) throw Error("Journal validation failed; existing data was not changed.");
    state.records=j.records; state.firstWindow=j.firstWindow;
  } catch(e) { state.storageError=`Local storage unavailable: ${e.message}. Export any existing records; capture is paused.`; }
}
function persist() {
  if (state.storageError) return false;
  try {
    localStorage.setItem(KEY,JSON.stringify({schema:1,model:MODEL,firstWindow:state.firstWindow,records:state.records}));
    return true;
  } catch(e) { state.storageError=`Storage write failed: ${e.message}. New forecast capture paused; nothing auto-deleted.`; return false; }
}
async function getJSON(url) {
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),8000);
  try {
    const r=await fetch(url,{signal:controller.signal,mode:"cors",credentials:"omit",cache:"no-store",referrerPolicy:"no-referrer"});
    if (!r.ok) throw Error(`Public API returned HTTP ${r.status}`);
    return await r.json();
  } finally { clearTimeout(timer); }
}
function array(x) { return typeof x==="string" ? JSON.parse(x) : x; }
function parseMarket(data, ts) {
  if (!Array.isArray(data)) throw Error("Invalid market response");
  const event=data.find(e=>e.slug===slug(ts));
  const m=event?.markets?.find(m=>m.slug===slug(ts));
  if (!m) throw Error("Market is not published or is unavailable");
  const names=array(m.outcomes).map(s=>String(s).trim().toLowerCase());
  const ids=array(m.clobTokenIds);
  if (names.length!==2 || new Set(names).size!==2 || !names.includes("up") || !names.includes("down") ||
      ids.length!==2 || !ids.every(x=>/^\d{1,128}$/.test(String(x)))) throw Error("Invalid Up/Down market mapping");
  const prices=array(m.outcomePrices || "[]").map(Number);
  return {raw:m,ts,tokens:Object.fromEntries(names.map((n,i)=>[n,String(ids[i])])),
    prices:Object.fromEntries(names.map((n,i)=>[n,prices[i]])),
    source:m.resolutionSource || event.resolutionSource || ""};
}
async function market(ts) {
  return parseMarket(await getJSON(`https://gamma-api.polymarket.com/events?slug=${slug(ts)}`),ts);
}
function parseBook(b,received) {
  function levels(side) {
    if (!Array.isArray(b[side])) throw Error("Invalid book levels");
    return b[side].map(r=>({price:Number(r.price),size:Number(r.size)})).filter(r=>finite(r.price)&&r.price>=0&&r.price<=1&&finite(r.size)&&r.size>0);
  }
  const bids=levels("bids").sort((a,b)=>b.price-a.price).slice(0,20);
  const asks=levels("asks").sort((a,b)=>a.price-b.price).slice(0,20);
  const bid=bids[0]?.price,ask=asks[0]?.price;
  if (finite(bid)&&finite(ask)&&bid>ask) throw Error("Crossed market book");
  return {bid,ask,bids,asks,received_at:received,exchange_ts:b.timestamp ? Number(b.timestamp)/1000 : null};
}
async function booksFor(m) {
  const result=await Promise.allSettled(["up","down"].map(async side=>
    [side,parseBook(await getJSON(`https://clob.polymarket.com/book?token_id=${m.tokens[side]}`),now())]));
  return Object.fromEntries(result.filter(r=>r.status==="fulfilled").map(r=>r.value));
}
function parseCandles(data,ts,cutoff=ts-60) {
  if (!Array.isArray(data)) throw Error("Invalid candle response");
  const candles=data.map(r=>({ts:Number(r[0]),low:Number(r[1]),high:Number(r[2]),open:Number(r[3]),close:Number(r[4]),volume:Number(r[5])}))
    .filter(c=>c.ts>=cutoff-120*60 && c.ts+60<=cutoff).sort((a,b)=>a.ts-b.ts);
  if (candles.length!==120 || candles.at(-1).ts+60!==cutoff ||
      candles.some((c,i)=>!Number.isInteger(c.ts)||c.ts%60!==0||![c.open,c.close,c.high,c.low,c.volume].every(finite)||c.low<=0||c.high<c.low||c.volume<0||c.open<c.low||c.open>c.high||c.close<c.low||c.close>c.high||(i&&c.ts-candles[i-1].ts!==60))) throw Error("Missing, duplicate or invalid historical candles; no forecast made");
  return candles;
}
async function candlesFor(ts,cutoff=ts-60) {
  const start=new Date((cutoff-120*60)*1000).toISOString(),end=new Date(cutoff*1000).toISOString();
  return parseCandles(await getJSON(`https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),ts,cutoff);
}
const mean = a => a.reduce((s,x)=>s+x,0)/a.length;
function baseline(candles) {
  const prices=candles.map(c=>c.close),returns=prices.slice(1).map((x,i)=>Math.log(x/prices[i]));
  const mu=mean(returns),sd=Math.sqrt(mean(returns.map(x=>(x-mu)**2)));
  const ema=n=>prices.reduce((v,x)=>v+(2/(n+1))*(x-v),prices[0]);
  const momentum=sd>0 ? Math.log(prices.at(-1)/prices.at(-4))/(sd*Math.sqrt(3)) : 0;
  const trend=sd>0 ? Math.log(ema(9)/ema(21))/sd : 0;
  const changes=prices.slice(-14).map((x,i)=>x-prices[prices.length-15+i]);
  const gain=mean(changes.map(x=>Math.max(0,x))),loss=mean(changes.map(x=>Math.max(0,-x)));
  const rsi=gain+loss ? 100*gain/(gain+loss) : 50;
  const score=.5*Math.tanh(momentum)+.3*Math.tanh(trend)+.2*((rsi-50)/50);
  return {p_up:.5+.15*Math.tanh(score),momentum,trend,rsi};
}
async function prepare(ts) {
  const cutoff=Math.min(ts-60,Math.floor(now()/60)*60-60);
  const history=await candlesFor(ts,cutoff);
  const result=baseline(history),captured=now();
  state.draft={...result,ts,captured_at:captured,feature_cutoff:cutoff,candles:history};
  state.chart={candles:history,received_at:captured};
  state.lastDraftAt=captured;
}
async function freeze(ts) {
  if (state.storageError || state.records.some(r=>r.ts===ts) || !(0<ts-now()&&ts-now()<=20)) return;
  if (state.records.length>=MAX_RECORDS) { state.storageError="Local journal reached 512 forecasts. Capture paused; export your data. No records deleted."; return; }
  // Fresh fetch AFTER entering the eligible pre-start interval. Drafts are never backfilled.
  const [history,context]=await Promise.all([candlesFor(ts),market(ts).then(async m=>({market:m.raw,books:await booksFor(m)})).catch(e=>({issue:e.message,books:{}}))]);
  const model=baseline(history),issued=now();
  if (state.paused) return;
  if (!(ts-20<=issued && issued<ts)) throw Error("Collection crossed boundary; late forecast was not saved");
  const stored=now();
  if (stored>=ts) return;
  const up=context.books.up;
  const record={model:MODEL,ts,issued_at:issued,stored_at:stored,feature_cutoff:ts-60,p_up:model.p_up,
    market_p_up:up&&finite(up.bid)&&finite(up.ask) ? (up.bid+up.ask)/2 : null,
    candles:history,context,up:null,resolved_at:null};
  state.records.push(record);
  if (!persist()) state.records.pop(); // This uncommitted record was never a saved forecast.
  state.draft={...model,ts,captured_at:issued,feature_cutoff:ts-60};
}
async function resolve() {
  if (state.storageError || now()-state.lastResolve<30) return;
  state.lastResolve=now();
  const pending=state.records.filter(r=>r.up===null&&r.ts+360<=now());
  // Round-robin pending labels so an old unavailable market cannot starve new ones.
  const batch=pending.slice(state.resolveOffset||0,(state.resolveOffset||0)+2);
  state.resolveOffset=pending.length ? ((state.resolveOffset||0)+2)%pending.length : 0;
  for (const r of batch) {
    const m=await market(r.ts);
    if (m.raw.closed===true && String(m.raw.umaResolutionStatus).toLowerCase()==="resolved" && m.source===ORACLE &&
        [m.prices.up,m.prices.down].sort().join(",")==="0,1") {
      const old={up:r.up,resolved_at:r.resolved_at,resolution:r.resolution};
      r.up=m.prices.up;r.resolved_at=now();r.resolution=m.raw;
      if (!persist()) Object.assign(r,old);
    }
  }
}
function chartGeometry(candles,count) {
  const rows=candles.slice(-count);
  if (rows.length<2 || rows.some(c=>!finite(c.close)||c.close<=0||!finite(c.ts))) return null;
  const values=rows.map(c=>c.close),min=Math.min(...values),max=Math.max(...values);
  const pad=(max-min)*.1 || Math.max(max*.001,.01),low=min-pad,high=max+pad;
  const points=rows.map((c,i)=>[16+694*i/(rows.length-1),280-260*(c.close-low)/(high-low)]);
  const line=points.map(([x,y],i)=>`${i?"L":"M"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  return {line,area:`${line} L710,280 L16,280 Z`,low,high,mid:(low+high)/2,
    change:values.at(-1)/values[0]-1,close:values.at(-1),first:rows[0].ts+60,last:rows.at(-1).ts+60,count:rows.length};
}
function renderChart() {
  const chart=state.chart,fresh=!state.paused&&chart&&now()-chart.received_at<=150;
  const g=fresh?chartGeometry(chart.candles,state.chartRange):null;
  $("chart-empty").hidden=Boolean(g);
  if (!g) {
    text("chart-empty",state.paused?"Chart paused":chart?"Historical candles are stale — waiting for a fresh update":"Waiting for real Coinbase candles…");
    for (const id of ["price-path","chart-area"]) $(id).setAttribute("d","");
    for (const id of ["chart-high","chart-mid","chart-low","chart-close","chart-start","chart-end","chart-change"]) text(id,"—");
    text("chart-description","No fresh historical candles available. No simulated chart is displayed.");
    state.chartRendered=null;return;
  }
  const signature=`${chart.received_at}:${state.chartRange}`;
  if (signature===state.chartRendered) return;
  state.chartRendered=signature;
  $("price-path").setAttribute("d",g.line);$("chart-area").setAttribute("d",g.area);
  for(const key of ["high","mid","low","close"]) text(`chart-${key}`,money(g[key]));
  text("chart-start",`${localTime(g.first)} Tehran`);text("chart-end",`${localTime(g.last)} Tehran`);
  text("chart-change",`${g.change>=0?"+":""}${(g.change*100).toFixed(2)}%`);
  $("chart-change").setAttribute("class",g.change>0?"positive":g.change<0?"negative":"neutral");
  text("chart-change-note",`${g.count} completed 1m closes · not the live window return`);
  text("chart-status",`Last candle closed ${localTime(g.last)} Tehran · newest minute omitted`);
  text("chart-description",`${g.count} real Coinbase minute closes from ${localTime(g.first)} to ${localTime(g.last)} Tehran time. Last close ${money(g.close)}. Range change ${(g.change*100).toFixed(2)} percent. Not the official settlement feed.`);
}
function renderJournal() {
  const rows=state.records.slice().sort((a,b)=>b.ts-a.ts).slice(0,10);
  const body=$("journal-rows");
  body.replaceChildren();
  $("journal-empty").hidden=rows.length>0;
  for(const r of rows) {
    const tr=document.createElement("tr"),resolved=r.up!==null&&r.ts+300<=now();
    const cells=[`${localDate(r.ts)} ${localTime(r.ts)}`,
      r.p_up===.5?"NEUTRAL · tie scored Up":r.p_up>.5?"UP":"DOWN",pct(r.p_up),
      `${(r.ts-r.stored_at).toFixed(1)}s`,resolved?(r.up===1?"UP":"DOWN"):r.ts>now()?"Not started":"Pending official label"];
    for(const value of cells){const td=document.createElement("td");td.textContent=value;tr.appendChild(td);}
    body.appendChild(tr);
  }
}
function pairedMarketScores(resolved) {
  const pairs=resolved.filter(r=>{
    const b=r.context?.books?.up;
    return finite(r.market_p_up)&&r.market_p_up>=0&&r.market_p_up<=1&&b&&
      finite(b.bid)&&finite(b.ask)&&0<=b.bid&&b.bid<=b.ask&&b.ask<=1&&
      Math.abs((b.bid+b.ask)/2-r.market_p_up)<1e-9&&
      finite(b.received_at)&&b.received_at<=r.issued_at&&r.issued_at-b.received_at<=STALE&&
      finite(b.exchange_ts)&&b.exchange_ts<=r.issued_at&&r.issued_at-b.exchange_ts<=STALE;
  });
  return pairs.length?{n:pairs.length,model:mean(pairs.map(r=>(r.p_up-r.up)**2)),
    market:mean(pairs.map(r=>(r.market_p_up-r.up)**2))}:null;
}
function render() {
  const t=now(),ts=windowAt(t),remaining=ts+300-t;
  text("countdown",`${String(Math.floor(remaining/60)).padStart(2,"0")}:${String(Math.floor(remaining%60)).padStart(2,"0")}`);
  text("window-range",`${localTime(ts)}–${localTime(ts+300)}`);
  text("local-clock",`${localDate(t)} · ${localTime(t,true)} Tehran`);
  $("window-progress").value=300-remaining;
  $("market-link").href=`https://polymarket.com/event/${slug(ts)}`;
  text("market-link",slug(ts));
  const freshPrice=!state.paused && state.price && t-state.price.received_at<=STALE && t-state.price.exchange_ts<=STALE && state.price.exchange_ts<=t+5;
  text("price",freshPrice?money(state.price.price):"—");
  text("price-age",freshPrice?`Coinbase · received ${Math.floor(t-state.price.received_at)}s ago`:"Stale / paused / unavailable");
  for (const side of ["up","down"]) {
    const b=state.books?.ts===ts?state.books[side]:null;
    const fresh=!state.paused&&b&&t-b.received_at<=STALE&&(b.exchange_ts===null||(finite(b.exchange_ts)&&t-b.exchange_ts<=STALE&&b.exchange_ts<=t+5));
    text(`${side}-quote`,fresh&&finite(b.bid)&&finite(b.ask)?`${b.bid.toFixed(3)} / ${b.ask.toFixed(3)}`:"—");
    text(`${side}-spread`,fresh&&finite(b.bid)&&finite(b.ask)?`Spread ${(b.ask-b.bid).toFixed(3)} · indicative only`:"No fresh two-sided book");
    const midpoint=fresh&&finite(b.bid)&&finite(b.ask)?(b.bid+b.ask)/2:null;
    text(`${side}-mid`,pct(midpoint));
    $(`${side}-meter`).hidden=midpoint===null;
    if(midpoint!==null) $(`${side}-meter`).value=midpoint;
  }
  const d=state.draft,good=!state.paused&&d&&d.ts===ts+300&&t-d.captured_at<=75;
  text("draft-direction",good?(d.p_up>.5?"UP":d.p_up<.5?"DOWN":"NEUTRAL"):"WAITING");
  text("draft-p",good?pct(d.p_up):"—");
  $("draft-direction").setAttribute("data-direction",good?(d.p_up>.5?"up":d.p_up<.5?"down":"neutral"):"neutral");
  $("draft-meter").hidden=!good;
  if(good) $("draft-meter").value=d.p_up;
  text("target",`Target: ${localDate(ts+300)} · ${localTime(ts+300)}–${localTime(ts+600)} Tehran. Next complete five-minute market window, not a rolling five minutes from now. Draft can change until saved before start.`);
  text("draft-detail",good?`Experimental direction estimate for the target below, based only on completed candles. It can be wrong; no validated accuracy is available for this browser model.`:"Waiting for fresh, completed candles. No direction is invented when data is missing or stale.");
  const frozen=state.records.find(r=>r.ts===ts);
  text("frozen-direction",frozen?(frozen.p_up>=.5?"UP":"DOWN"):"NO FORECAST");
  $("frozen-direction").setAttribute("data-direction",frozen?(frozen.p_up>=.5?"up":"down"):"neutral");
  text("frozen-detail",frozen?`${pct(frozen.p_up)} heuristic P(Up), saved ${(ts-frozen.stored_at).toFixed(1)}s before start. It cannot update after start. Not calibrated.`:"No saved pre-start forecast for this window. Later observations are never backfilled.");
  const done=state.records.filter(r=>r.up!==null&&r.ts+300<=t),n=done.length;
  const eligible=state.records.filter(r=>r.ts+300<=t).length;
  const expected=state.firstWindow===null?0:Math.max(0,(ts-state.firstWindow)/300);
  const correct=done.filter(r=>(r.p_up>=.5)===Boolean(r.up)).length;
  const brier=n?mean(done.map(r=>(r.p_up-r.up)**2)):null;
  const paired=pairedMarketScores(done);
  text("market-comparison",paired?`Same ${paired.n} resolved windows with fresh pre-start quotes: model Brier ${paired.model.toFixed(4)} vs market midpoint ${paired.market.toFixed(4)}. Lower is better; this descriptive comparison does not prove a predictive edge.`:"No paired market comparison yet: needs official outcomes and timestamped fresh pre-start quotes. Missing or stale quotes are excluded, not guessed.");
  text("scores",n?`${n} officially resolved forecasts · accuracy ${pct(correct/n)} · Brier ${brier.toFixed(4)} (neutral 0.2500) · always-Up accuracy ${pct(mean(done.map(r=>r.up)))}`:"No scored outcomes yet. No accuracy or predictive advantage is claimed.");
  text("coverage",`${state.records.length} forecasts stored · ${eligible} eligible / ${expected} elapsed closed windows · coverage ${expected?pct(eligible/expected):"—"} · ${eligible-n} pending official labels. Startup partial windows and offline gaps count against coverage. Scores are provisional.`);
  text("journal-status",state.storageError?"STORAGE PAUSED":state.paused?"TAB PAUSED":"BROWSER-LOCAL");
  if (state.storageError) {$("error").hidden=false;text("error",state.storageError);}
  text("connection",state.paused?"PAUSED":freshPrice?"LIVE PUBLIC DATA":"WAITING FOR DATA");
  $("connection").setAttribute("data-status",state.paused?"paused":freshPrice?"live":"waiting");
  renderChart();renderJournal();renderOracle();
}
async function tick() {
  if (state.busy||state.paused) return;
  state.busy=true;
  const issues=[];
  try {
    const ts=windowAt(now()),target=ts+300;
    if (state.firstWindow===null&&!state.storageError) {state.firstWindow=ts;persist();}
    // Freeze first: live display fetches must not consume the short pre-start interval.
    if (target-now()<=20) try {await freeze(target);} catch(e) {issues.push(`Pre-start: ${e.message}`);}
    const results=await Promise.allSettled([
      getJSON("https://api.exchange.coinbase.com/products/BTC-USD/ticker").then(r=>{
        const price=Number(r.price),exchange_ts=Date.parse(r.time)/1000;
        if (!finite(price)||price<=0||!finite(exchange_ts)) throw Error("Invalid price timestamp");
        state.price={price,exchange_ts,received_at:now()};
      }),
      (async()=>{
        if (!state.lastCurrent||state.lastCurrent.ts!==ts||now()-state.lastCurrentAt>30) {
          state.lastCurrent=await market(ts);state.lastCurrentAt=now();
        }
        state.books={ts,...await booksFor(state.lastCurrent)};
      })(),
      (async()=>{if (!state.draft||state.draft.ts!==target||now()-state.lastDraftAt>60) await prepare(target);})(),
      resolve()
    ]);
    for (const r of results) if(r.status==="rejected") issues.push(r.reason.message);
    $("error").hidden=!issues.length&&!state.storageError;
    text("error",state.storageError||issues.join(" · "));
    text("observed",`Last update ${localTime(now(),true)} Tehran · direct public APIs`);
  } finally {
    state.busy=false;render();clearTimeout(state.timer);
    if(!state.paused) state.timer=setTimeout(tick,windowAt(now())+300-now()<=25?1000:10000);
  }
}
$("refresh").addEventListener("click",()=>{if(!state.paused)tick();});
$("apply-reference").addEventListener("click",()=>{setManualReference($("reference-input").value,state.oracle.inputWindow);renderOracle();});
$("reference-input").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();setManualReference($("reference-input").value,state.oracle.inputWindow);renderOracle();}});
$("pause").addEventListener("click",()=>{
  state.paused=!state.paused;clearTimeout(state.timer);
  if(state.paused) stopOracle();else startOracle();
  text("pause",state.paused?"Resume this tab":"Pause this tab");render();if(!state.paused)tick();
});
$("export").addEventListener("click",()=>{
  const blob=new Blob([JSON.stringify({schema:1,model:MODEL,display_timezone:DISPLAY_ZONE,timestamp_format:"Unix seconds; timezone-independent",exported_at:now(),firstWindow:state.firstWindow,records:state.records},null,2)],{type:"application/json"});
  const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;
  a.download=`maagif-shadow-${localDate(now())}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!state.paused)tick();});
for(const button of document.querySelectorAll("[data-range]")) {
  button.addEventListener("click",()=>{
    const range=Number(button.getAttribute("data-range"));
    if(![15,60,120].includes(range)) return;
    state.chartRange=range;
    for(const other of document.querySelectorAll("[data-range]")) {
      const active=other===button;
      other.setAttribute("aria-pressed",String(active));other.classList.toggle("active",active);
    }
    renderChart();
  });
}
loadJournal();loadReference();startOracle();render();setInterval(render,1000);tick();