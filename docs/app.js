/* Stock Crawler dashboard — reads data/latest.json + data/history.json (written daily by the scanner). */
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const inr = x => x == null ? "–" : "₹" + Number(x).toLocaleString("en-IN", {maximumFractionDigits: x < 1000 ? 2 : 0});
const pct = (x, d = 0) => x == null ? "–" : (x * 100).toFixed(d) + "%";
const spct = (x, d = 1) => x == null ? "–" : (x > 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const fmtDate = s => s ? new Date(s + "T00:00:00").toLocaleDateString("en-IN", {day: "2-digit", month: "short"}) : "–";

let L = null, H = [], SET = {}, BE = 0.4, chart = null;

const STATUS = {
  1: {TARGET: "Hit target ✓", STOP: "Stopped out ✗", EXPIRED: "Time up", OPEN: "Open", PENDING: "Enters next open"},
  "-1": {TARGET: "Fell as warned ✓", STOP: "Rose instead ✗", EXPIRED: "Time up", OPEN: "Open", PENDING: "Starts next open"},
};

async function fetchData() {
  const bust = "?v=" + Date.now();
  const [l, h] = await Promise.all([
    fetch("data/latest.json" + bust, {cache: "no-store"}).then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }),
    fetch("data/history.json" + bust, {cache: "no-store"}).then(r => r.ok ? r.json() : []).catch(() => []),
  ]);
  return [l, h];
}

function renderAll() {
  SET = {}; L.meta.setups.forEach(s => SET[s.id] = s);
  BE = L.meta.config.breakeven;
  header(); cards(); renderBuys(); renderExits(); renderTrack(); renderHow();
  const onBuys = $("#tab-buys").classList.contains("on");
  const first = onBuys ? filteredBuys()[0] : L.exits[0];
  if (first && innerWidth > 900) showDetail(first, onBuys ? "#detail" : "#detail2");
}

let loading = false;
async function refresh(manual = false) {
  if (loading) return;
  loading = true; $("#refreshBtn").classList.add("spin");
  try {
    const [l, h] = await fetchData();
    const changed = !L || l.meta.generated !== L.meta.generated;
    const firstLoad = !L;
    if (changed) { L = l; H = h; renderAll(); }
    if (!firstLoad && changed) toast("New scan loaded — " + L.meta.as_of_label);
    else if (manual) toast("Already up to date");
    $("#lastCheck").textContent = "Last checked " + new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) +
      " · data from market close " + L.meta.as_of_label;
  } catch (e) {
    if (!L) $("#asof").textContent = "Couldn't load data: " + e.message + " (has the scanner run yet?)";
    else if (manual) toast("Couldn't refresh — check your connection");
  } finally {
    loading = false; $("#refreshBtn").classList.remove("spin");
  }
}

let toastT;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 2600);
}

function header() {
  const m = L.meta;
  $("#asof").textContent = `Market close ${m.as_of_label} · updated ${m.generated} · ${m.scanned} stocks scanned`;
  const r = $("#regime");
  if (m.regime === "up") { r.className = "pill up"; r.textContent = "Nifty above 200-day avg — dips usually get bought"; }
  else if (m.regime === "down") { r.className = "pill down"; r.textContent = "Nifty below 200-day avg — weak market, be picky"; }
  $("#demo").hidden = !m.demo;
}

function cards() {
  const t = L.track, good = L.buys.filter(b => b.prob >= BE).length;
  const live = t.live_only || {};
  const c = [
    ["Today's dip ideas", good, `above ${pct(BE)} break-even · ${L.buys.length} shown`],
    ["Hit-target rate", t.resolved ? pct(t.win_rate) : "–", t.resolved ? `${t.resolved} closed buy ideas` : "no closed ideas yet"],
    ["Avg result per idea", t.resolved ? spct(t.avg_ret) : "–", t.resolved ? `${pct(t.positive_rate)} ended in profit` : ""],
    ["Live (not replayed)", live.resolved ? pct(live.win_rate) : "–", live.resolved ? `${live.resolved} closed since launch` : `${live.open || 0} open, building up`],
    ["Open ideas", (t.open || 0), `being tracked now`],
  ];
  $("#cards").innerHTML = c.map(([k, v, s]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
}

/* ------------------------------------------------------------------ idea lists */
function filteredBuys() {
  const q = $("#q").value.trim().toLowerCase();
  return L.buys.filter(b =>
    (!$("#onlyGood").checked || b.prob >= BE) &&
    (!$("#onlyWatch").checked || b.watchlist) &&
    (!q || b.symbol.toLowerCase().includes(q) || (b.name || "").toLowerCase().includes(q)));
}

function newsChip(c) {
  if (c.news_flag === "risk") return `<span class="chip risk">⚠ bad-news risk</span>`;
  if (c.news_flag === "positive") return `<span class="chip pos">positive news</span>`;
  if (c.news_flag === "none") return `<span class="chip mute">news: neutral</span>`;
  if (c.news_flag === "quiet") return `<span class="chip mute">no news</span>`;
  return "";
}

function ideaHTML(c, i) {
  const s = SET[c.setup], dn = c.direction === -1;
  const cls = dn ? "dn" : c.prob >= BE ? "" : "weak";
  const tPct = c.target / c.close - 1, sPct = c.stop / c.close - 1;
  return `<div class="idea" data-i="${i}">
    <div class="rk">${i + 1}</div>
    <div><div class="sym">${esc(c.symbol)} ${c.watchlist ? '<span class="chip star">★ watchlist</span>' : ""}</div>
      <div class="nm">${esc(c.name)}${c.industry ? " · " + esc(c.industry) : ""}</div></div>
    <div class="pr"><div class="pct">${pct(c.prob)}</div><div class="cases">${c.base_n} past cases</div></div>
    <div class="bar"><i class="${cls}" style="width:${Math.min(100, c.prob * 100)}%"></i><em style="left:${BE * 100}%" title="break-even"></em></div>
    <div class="row2"><span class="chip">${esc(s.name)}</span>${newsChip(c)}</div>
    <div class="lv"><span>Close <b>${inr(c.close)}</b></span>
      <span>${dn ? "Fall to" : "Target"} <b>${inr(c.target)}</b> (${spct(tPct)})</span>
      <span>${dn ? "Wrong above" : "Stop"} <b>${inr(c.stop)}</b> (${spct(sPct)})</span></div>
  </div>`;
}

function bindList(el, arr, target) {
  el.querySelectorAll(".idea").forEach(d => d.onclick = () => {
    el.querySelectorAll(".idea").forEach(x => x.classList.remove("sel"));
    d.classList.add("sel");
    showDetail(arr[+d.dataset.i], target);
  });
}

function renderBuys() {
  const arr = filteredBuys(), el = $("#buyList");
  el.innerHTML = arr.length ? arr.map(ideaHTML).join("")
    : `<div class="card">No ideas match. ${L.buys.length ? "Try unticking the filters." : "No dip setups passed the filters today — that's normal on strong days."}</div>`;
  bindList(el, arr, "#detail");
}

function renderExits() {
  const el = $("#exitList");
  el.innerHTML = L.exits.length ? L.exits.map(ideaHTML).join("") : `<div class="card">No exit warnings today.</div>`;
  bindList(el, L.exits, "#detail2");
}

/* ------------------------------------------------------------------ detail + chart */
function showDetail(c, target) {
  const s = SET[c.setup], dn = c.direction === -1, cfg = L.meta.config;
  const regTxt = c.regime === "up" ? "while Nifty was above its 200-day average" : c.regime === "down" ? "while Nifty was below its 200-day average" : "";
  const own = c.own_n ? ` This stock's own history with this pattern: <b>${c.own_wins} of ${c.own_n}</b> worked.` : " No past cases on this stock itself, so the market-wide rate is used.";
  const also = (c.also || []).filter(x => SET[x]).map(x => SET[x].name);
  const html = `
    <div class="dh"><div><h2>${esc(c.symbol)}</h2><div class="nm">${esc(c.name)}</div></div>
      <div style="text-align:right"><div style="font-size:26px;font-weight:700">${pct(c.prob)}</div>
      <div class="nm">${dn ? "chance it falls to" : "chance it reaches"} the ${dn ? "level" : "target"} first</div></div></div>
    <div class="why"><b>${esc(s.name)}.</b> ${esc(s.explain)}
      ${also.length ? `<br><span class="nm">Also triggered: ${also.map(esc).join(", ")}</span>` : ""}</div>
    <div class="why">Across <b>${c.base_n}</b> similar past cases ${regTxt}, <b>${pct(c.base_rate)}</b>
      ${dn ? "fell to the level" : "hit the target"} before the ${dn ? "invalidation price" : "stop"} within ${cfg.horizon} trading days.${own}
      Break-even is ${pct(BE)} because a win (${cfg.target_atr}× ATR) is bigger than a loss (${cfg.stop_atr}× ATR).</div>
    <div class="levels">
      <div><div class="k">Signal close</div><div class="v">${inr(c.close)}</div></div>
      <div class="t"><div class="k">${dn ? "Fall to" : "Target"}</div><div class="v">${inr(c.target)}</div></div>
      <div class="st"><div class="k">${dn ? "Wrong above" : "Stop-loss"}</div><div class="v">${inr(c.stop)}</div></div>
    </div>
    <div class="nm">Levels are from today's close. Recompute from tomorrow's actual price: target ≈ entry ${dn ? "−" : "+"} ${cfg.target_atr} × ${inr(c.atr)}, stop ≈ entry ${dn ? "+" : "−"} ${cfg.stop_atr} × ${inr(c.atr)} (ATR). Give it up to ${cfg.horizon} trading days.</div>
    <div class="chart" id="chartBox"></div>
    <div class="legend"><span style="--c:#2f5bea">50-day avg</span><span style="--c:#b54708">200-day avg</span>
      <span style="--c:#0e9f6e">${dn ? "fall-to level" : "target"}</span><span style="--c:#d92d20">${dn ? "invalidation" : "stop"}</span></div>
    <h3>Recent headlines</h3>
    ${newsHTML(c)}`;
  let box;
  if (innerWidth <= 900) {
    const sh = $("#sheet"); sh.hidden = false;
    sh.innerHTML = `<button class="close" onclick="closeSheet()">← Back</button><div style="margin-top:12px">${html}</div>`;
    document.body.style.overflow = "hidden";
    box = $("#chartBox", sh);
  } else {
    $(target).innerHTML = html;
    box = $("#chartBox", $(target));
  }
  drawChart(box, c);
}
window.closeSheet = () => { $("#sheet").hidden = true; document.body.style.overflow = ""; };

function newsHTML(c) {
  if (!L.meta.news) return `<div class="nm">News check is off for this run.</div>`;
  if (!c.news || !c.news.length) return `<div class="nm">No headlines in the last week — the move looks price-driven, not news-driven.</div>`;
  const tone = {neg: '<span class="chip risk">negative</span>', pos: '<span class="chip pos">positive</span>', neutral: ""};
  return `<ul class="news">${c.news.map(n => `<li>${tone[n.tone] || ""} <a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>
    <div class="meta">${esc(n.source)} · ${fmtDate(n.date)}</div></li>`).join("")}</ul>`;
}

function drawChart(box, c) {
  if (chart) { try { chart.remove(); } catch (e) {} chart = null; }
  if (!window.LightweightCharts || !c.chart) { box.innerHTML = `<div class="nm">Chart library didn't load.</div>`; return; }
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const col = dark ? "#98a2b3" : "#667085", grid = dark ? "#222731" : "#eef0f3";
  chart = LightweightCharts.createChart(box, {
    autoSize: true, layout: {background: {color: "transparent"}, textColor: col, fontSize: 11},
    grid: {vertLines: {color: grid}, horzLines: {color: grid}},
    rightPriceScale: {borderVisible: false}, timeScale: {borderVisible: false},
    crosshair: {mode: 0},
  });
  const d = c.chart, n = d.t.length;
  const candles = chart.addCandlestickSeries({upColor: "#0e9f6e", downColor: "#d92d20", wickUpColor: "#0e9f6e",
    wickDownColor: "#d92d20", borderVisible: false});
  candles.setData(d.t.map((t, i) => ({time: t, open: d.o[i], high: d.h[i], low: d.l[i], close: d.c[i]})));
  const line = (arr, color) => { const s = chart.addLineSeries({color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
    s.setData(d.t.map((t, i) => arr[i] == null ? null : {time: t, value: arr[i]}).filter(Boolean)); };
  line(d.sma50, "#2f5bea"); line(d.sma200, "#b54708");
  const vol = chart.addHistogramSeries({priceScaleId: "", priceFormat: {type: "volume"}, lastValueVisible: false, priceLineVisible: false});
  vol.priceScale().applyOptions({scaleMargins: {top: 0.82, bottom: 0}});
  vol.setData(d.t.map((t, i) => ({time: t, value: d.v[i], color: d.c[i] >= d.o[i] ? "rgba(14,159,110,.35)" : "rgba(217,45,32,.35)"})));
  candles.createPriceLine({price: c.target, color: "#0e9f6e", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: c.direction === 1 ? "target" : "fall-to"});
  candles.createPriceLine({price: c.stop, color: "#d92d20", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: c.direction === 1 ? "stop" : "invalid"});
  candles.setMarkers([{time: d.t[n - 1], position: c.direction === 1 ? "belowBar" : "aboveBar",
    color: c.direction === 1 ? "#0e9f6e" : "#d92d20", shape: c.direction === 1 ? "arrowUp" : "arrowDown", text: "signal"}]);
  chart.timeScale().setVisibleLogicalRange({from: Math.max(0, n - 90), to: n + 3});
}

/* ------------------------------------------------------------------ track record */
function renderTrack() {
  const t = L.track, st = L.meta.setup_stats;
  const setRows = L.meta.setups.map(s => {
    const live = t.by_setup[s.id] || {}, bt = st[s.id] || {};
    const reg = bt[L.meta.regime] || {};
    return `<tr><td>${s.direction === 1 ? "▲" : "▼"} ${esc(s.name)}</td>
      <td class="num">${bt.all ? pct(bt.all.rate) : "–"}</td><td class="num">${bt.all ? bt.all.n : "–"}</td>
      <td class="num">${reg.rate != null ? pct(reg.rate) : "–"}</td>
      <td class="num">${live.resolved ? pct(live.win_rate) : "–"}</td><td class="num">${live.resolved || 0}</td></tr>`;
  }).join("");
  const cal = (t.calibration || []).map(b => `<tr><td>${b.band}</td><td class="num">${pct(b.avg_prob)}</td>
    <td class="num">${pct(b.win_rate)}</td><td class="num">${b.resolved}</td><td class="num ${b.avg_ret >= 0 ? "pos" : "neg"}">${spct(b.avg_ret)}</td></tr>`).join("");
  $("#trackTop").innerHTML = `<div class="grid2">
    <div class="box"><h4>Each pattern: history vs. this tracker</h4><div class="tablewrap" style="border:0">
      <table><tr><th>Pattern</th><th class="num">${L.meta.config.years}y hit</th><th class="num">cases</th>
      <th class="num">in today's market</th><th class="num">tracked hit</th><th class="num">closed</th></tr>${setRows}</table></div></div>
    <div class="box"><h4>Are the percentages honest?</h4>
      <p class="nm" style="margin:0 0 6px">If the % is well calibrated, ideas shown at ~60% should hit about 60% of the time.</p>
      ${cal ? `<table><tr><th>Shown as</th><th class="num">avg shown</th><th class="num">actual hit</th><th class="num">closed</th><th class="num">avg result</th></tr>${cal}</table>` : `<div class="nm">Needs a few closed ideas first.</div>`}
    </div></div>`;
  const draw = () => {
    const sf = $("#tStatus").value, df = +$("#tDir").value, live = $("#tLive").checked;
    const rows = H.filter(p => (df === 0 || p.direction === df) && (!live || !p.backfilled) &&
      (sf === "all" || (sf === "open" ? ["OPEN", "PENDING"].includes(p.status) : !["OPEN", "PENDING"].includes(p.status)))).slice(0, 600);
    $("#trackTable").innerHTML = `<tr><th>Signal</th><th>Stock</th><th>Pattern</th><th class="num">Shown %</th>
      <th class="num">Entry</th><th class="num">Target</th><th class="num">Stop</th><th>Outcome</th><th class="num">Result</th><th class="num">Days</th></tr>` +
      rows.map(p => `<tr><td>${fmtDate(p.date)}${p.backfilled ? ' <span class="chip mute" title="Replayed from history on first run">replay</span>' : ""}</td>
        <td><b>${esc(p.symbol)}</b></td><td>${esc(SET[p.setup]?.name || p.setup)}</td><td class="num">${pct(p.prob)}</td>
        <td class="num">${inr(p.entry)}</td><td class="num">${inr(p.target)}</td><td class="num">${inr(p.stop)}</td>
        <td class="st-${p.status}">${STATUS[p.direction][p.status] || p.status}</td>
        <td class="num ${(p.ret || 0) >= 0 ? "pos" : "neg"}">${p.ret == null ? "–" : spct(p.ret)}</td>
        <td class="num">${p.days ?? "–"}</td></tr>`).join("");
  };
  ["#tStatus", "#tDir", "#tLive"].forEach(s => $(s).onchange = draw);
  draw();
}

function renderHow() {
  const c = L.meta.config;
  $("#how").innerHTML = `
  <h3>What it does every evening</h3>
  <p>After NSE closes, the scanner downloads daily prices for ${L.meta.universe === "nifty500" ? "the Nifty 500 plus your watchlist" : "your watchlist"}
   (${L.meta.scanned} stocks today), skips illiquid ones (under ₹${c.min_turnover_cr} crore traded a day), and looks for the patterns below.</p>
  <ul>${L.meta.setups.map(s => `<li><b>${s.direction === 1 ? "▲" : "▼"} ${esc(s.name)}</b> — ${esc(s.explain)}</li>`).join("")}</ul>
  <h3>Where the percentage comes from</h3>
  <p>For every pattern, it replays the last ${c.years} years on all scanned stocks: buy at the next morning's open, target = entry + ${c.target_atr}× ATR,
   stop = entry − ${c.stop_atr}× ATR (ATR is the stock's normal daily range), maximum ${c.horizon} trading days. The % is how often the target came
   before the stop — split by whether Nifty was in an uptrend, and blended with that stock's own record of the same pattern.</p>
  <p>Because a win is ${c.target_atr}× and a loss is ${c.stop_atr}×, you only need to be right about <b>${pct(c.breakeven)}</b> of the time to break even (before brokerage and taxes).</p>
  <h3>The news check</h3>
  <p>For the top ideas it reads the last ${7} days of Google News headlines. Words like fraud, raid, downgrade, results miss, resignation or SEBI action
   flag it as <span class="chip risk">⚠ bad-news risk</span> and push it down the list — a fall caused by real bad news is less likely to be temporary.
   Always open the headlines yourself before buying.</p>
  <h3>How to use it with Zerodha</h3>
  <ol><li>Read the evening alert / this page after 6 PM IST.</li>
   <li>Next morning, if the stock opens near the signal close, buy in Kite (CNC / delivery).</li>
   <li>Immediately set a GTT OCO with the target and stop recalculated from your fill price.</li>
   <li>If neither is hit within ${c.horizon} trading days, exit — the edge has expired.</li>
   <li>Keep each trade small (risking 1–2% of capital at the stop), so a losing streak doesn't hurt.</li></ol>
  <h3>Honest limits</h3>
  <p>Past patterns don't guarantee anything — markets change, and dips in a falling market often keep falling. "Replay" rows in the track record were
   generated on the first run using history, so treat the <b>Live</b> number as the real test. This is a tool to shortlist stocks, not advice.</p>`;
}

/* ------------------------------------------------------------------ wiring */
$("#tabs").onclick = e => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x === b));
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("on", x.id === "tab-" + b.dataset.tab));
  if (innerWidth > 900) {
    if (b.dataset.tab === "buys" && filteredBuys()[0]) showDetail(filteredBuys()[0], "#detail");
    if (b.dataset.tab === "exits" && L.exits[0]) showDetail(L.exits[0], "#detail2");
  }
};
["#q", "#onlyGood", "#onlyWatch"].forEach(s => $(s).addEventListener("input", renderBuys));

/* ------------------------------------------------------------------ PWA: refresh, offline, install, push */
$("#refreshBtn").onclick = () => refresh(true);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });
setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 15 * 60 * 1000);
const netState = () => { $("#offline").hidden = navigator.onLine; };
addEventListener("online", () => { netState(); refresh(); });
addEventListener("offline", netState);
netState();

const store = {
  get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} },
};
const isStandalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

function installUI() {
  $("#installState").textContent = isStandalone ? "✓ Running as an installed app." : "";
  if (isIOS && !isStandalone && store.get("hideInstall") !== "1") {
    const b = $("#installHint");
    b.innerHTML = `<span>📲 Install: tap <b>Share</b> → <b>Add to Home Screen</b> to use this as an app with notifications.</span><button aria-label="Dismiss">✕</button>`;
    b.hidden = false;
    b.querySelector("button").onclick = () => { b.hidden = true; store.set("hideInstall", "1"); };
  }
}
let deferredPrompt = null;
addEventListener("beforeinstallprompt", e => { e.preventDefault(); deferredPrompt = e; $("#installBtn").hidden = false; });
$("#installBtn").onclick = async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt(); await deferredPrompt.userChoice; deferredPrompt = null; $("#installBtn").hidden = true;
};

function b64ToBytes(b64) {
  const pad = "=".repeat((4 - b64.length % 4) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, c => c.charCodeAt(0));
}
function showPushCode(sub) {
  $("#pushCode").hidden = false;
  $("#pushJson").value = JSON.stringify(sub);
  $("#pushState").textContent = "✓ Notifications are on for this device.";
  $("#pushBtn").textContent = "Show my device code";
}
async function pushUI() {
  const st = $("#pushState"), btn = $("#pushBtn");
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    btn.disabled = true;
    st.textContent = isIOS && !isStandalone ? "Install to Home Screen first, then open the app from there."
      : "This browser doesn't support push notifications.";
    return;
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) showPushCode(sub);
  btn.onclick = async () => {
    const existing = await reg.pushManager.getSubscription();
    if (existing) return showPushCode(existing);
    const key = L && L.meta.vapid_public;
    if (!key) { st.textContent = "Push keys aren't set up yet — see README step 7 (VAPID keys)."; return; }
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { st.textContent = "Permission was not given. You can allow it in your phone's settings."; return; }
    try {
      showPushCode(await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: b64ToBytes(key)}));
    } catch (e) { st.textContent = "Couldn't subscribe: " + e.message; }
  };
  $("#copyPush").onclick = async () => {
    try { await navigator.clipboard.writeText($("#pushJson").value); toast("Copied"); }
    catch (e) { $("#pushJson").select(); document.execCommand("copy"); toast("Copied"); }
  };
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(e => console.warn("SW failed", e));
  navigator.serviceWorker.addEventListener("message", e => { if (e.data?.type === "refresh") refresh(); });
}
installUI();
refresh().then(pushUI);
