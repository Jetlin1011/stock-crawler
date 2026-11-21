/* Stock Crawler app — reads data/latest.json, data/history.json and (lazily) data/charts.json. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const inr = x => x == null ? "–" : "₹" + Number(x).toLocaleString("en-IN", {maximumFractionDigits: x < 1000 ? 2 : 0});
const pct = (x, d = 0) => x == null ? "–" : (x * 100).toFixed(d) + "%";
const spct = (x, d = 1) => { if (x == null) return "–"; const s = Math.abs(x * 100).toFixed(d); return (+s === 0 ? "" : x > 0 ? "+" : "−") + s + "%"; };
const sign = x => x == null ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "";
const day = s => s ? new Date(s + "T00:00:00").toLocaleDateString("en-IN", {weekday: "short", day: "numeric", month: "short"}) : "–";
const short = s => s ? new Date(s + "T00:00:00").toLocaleDateString("en-IN", {day: "numeric", month: "short"}) : "–";
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

let L = null, H = [], CH = null, chartObjs = [];
const BY = {};                                    // symbol -> row (any list)

/* ------------------------------------------------------------------ data */
async function fetchJSON(path) {
  const r = await fetch(path + "?v=" + Date.now(), {cache: "no-store"});
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
async function charts() {
  if (!CH) CH = await fetchJSON("data/charts.json").catch(() => ({}));
  return CH;
}

let loading = false;
async function refresh(manual = false) {
  if (loading) return;
  loading = true; $("#refreshBtn").classList.add("spin");
  try {
    const l = await fetchJSON("data/latest.json");
    const changed = !L || l.meta.generated !== L.meta.generated;
    const first = !L;
    if (changed) {
      L = l; CH = null;
      H = await fetchJSON("data/history.json").catch(() => []);
      renderAll();
    }
    if (!first && changed) toast("New scan loaded");
    else if (manual) toast("Already up to date");
    $("#lastCheck").textContent = `Last checked ${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}. Results update once a day after market close.`;
  } catch (e) {
    if (!L) $("#brief").innerHTML = `<h1>Couldn't load the scan</h1><div class="facts">${esc(e.message)}. If this is a new install, the first scan may still be running.</div>`;
    else if (manual) toast("Couldn't refresh. Check your connection.");
  } finally {
    loading = false; $("#refreshBtn").classList.remove("spin");
  }
}

function renderAll() {
  for (const k of ["setups", "watch", "leaders", "mine"]) for (const r of L[k] || []) BY[r.symbol] = Object.assign(BY[r.symbol] || {}, r);
  for (const r of L.setups) BY[r.symbol] = r;
  brief(); today(); leaders(); sectors(); accuracy(); aiCheck(); record(); how();
  if ($("#tab-sectors").classList.contains("on")) marketCharts();
}

/* ------------------------------------------------------------------ helpers */
function nextSession(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  do d.setDate(d.getDate() + 1); while (d.getDay() === 0 || d.getDay() === 6);
  return d.toLocaleDateString("en-IN", {weekday: "long"});
}
function spark(vals, w = 88, h = 30) {
  const v = (vals || []).filter(x => x != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), rng = hi - lo || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1) * (w - 2) + 1).toFixed(1)},${(h - 2 - (x - lo) / rng * (h - 4)).toFixed(1)}`);
  const col = v[v.length - 1] >= v[0] ? "var(--up)" : "var(--down)";
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts.join(" ")}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
}
function stateTag(s) {
  const cls = {"Dip setup": "buy", "Pulling back": "watch", "Near 52-week high": "pen", "Stretched": "weak"}[s] || "";
  return `<span class="tag ${cls}">${esc(s)}</span>`;
}
const AI = {
  GO: {c: "buy", t: "AI: no bad news"}, CAUTION: {c: "watch", t: "AI: read the news first"},
  SKIP: {c: "weak", t: "AI: skip"}};
function aiTag(r) {
  const a = r.agent || (r.pick || {}).agent, x = a && AI[a.verdict];
  return x ? `<span class="tag ${x.c}">${x.t}</span>` : "";
}
const isSkip = r => (r.agent || {}).verdict === "SKIP";
function newsTag(r) {
  if (r.news_flag === "risk") return `<span class="tag weak">Bad-news risk</span>`;
  if (r.news_flag === "positive") return `<span class="tag buy">Positive news</span>`;
  return "";
}

/* ------------------------------------------------------------------ today */
function brief() {
  const m = L.meta, mk = L.market, n = L.setups.filter(r => !isSkip(r)).length, w = L.watch.length;
  const nx = nextSession(m.as_of);
  let head;
  if (mk.regime !== "up") head = "Market in a downtrend. No dip buys until Nifty is back above its 200-day average.";
  else if (n) head = `Uptrend. ${n} leader dip${n > 1 ? "s" : ""} to buy at ${nx}'s open.`;
  else head = `Uptrend, nothing to buy yet. ${w} leader${w === 1 ? " is" : "s are"} dipping.`;
  const hot = (L.sectors || [])[0];
  const b = mk.b50 ?? 0, bp = mk.b50_prev;
  const bTrend = bp == null ? "" : b > bp + 0.02 ? ", rising" : b < bp - 0.02 ? ", falling" : ", steady";
  $("#brief").innerHTML = `
    <div class="date">Market close ${esc(m.as_of_label)}${m.data?.source?.includes("NSE") ? ", NSE official prices" : ""}</div>
    <h1>${esc(head)}</h1>
    <div class="facts">
      ${mk.nifty_close ? `<span>Nifty <b>${Number(mk.nifty_close).toLocaleString("en-IN", {maximumFractionDigits: 0})}</b> <span class="${sign(mk.nifty_r1)}">${spct(mk.nifty_r1)}</span> today</span>` : ""}
      <span><b>${mk.adv}</b> stocks up, <b>${mk.dec}</b> down</span>
      <span><b>${mk.leaders}</b> momentum leaders</span>
      ${hot ? `<span>Hottest sector: <b>${esc(hot.name)}</b> ${spct(hot.r21)} this month</span>` : ""}
    </div>
    <div class="meter" role="img" aria-label="${pct(b)} of stocks above their 50-day average"><i style="left:calc(${Math.round(b * 100)}% - 2px)"></i></div>
    <div class="meter-l"><span>Weak market</span><span>${pct(b)} of stocks above 50-day avg${bTrend}</span><span>Strong</span></div>`;
  const notes = [];
  if (m.demo) notes.push("Demo data: synthetic prices for testing the layout.");
  if (m.data?.stale) notes.push(`Prices are from ${day(m.as_of)}. ${day(m.data.expected)} hasn't been published yet (or was a holiday); results may change at the next scan.`);
  $("#notice").hidden = !notes.length;
  $("#notice").textContent = notes.join(" ");
}

function rowSetup(r) {
  const a = r.agent;
  return `<button class="row${isSkip(r) ? " skipped" : ""}" data-sym="${esc(r.symbol)}" data-kind="setup">
    <div><div class="sym">${esc(r.symbol)} ${r.watchlist ? '<span class="tag pen">Watchlist</span>' : ""}</div><div class="nm">${esc(r.name)}</div></div>
    ${spark(r.spark)}
    <div><div class="num">${pct(r.prob)}</div><div class="sub">won before, avg ${spct(r.ev)}</div></div>
    <div class="meta"><span>Close <b>${inr(r.close)}</b></span><span>Sell once it closes above <b>${inr(r.sma5)}</b> (5-day avg)</span>
      <span>Down <b class="neg">${spct(r.r5)}</b> in 5 days</span>${aiTag(r) || newsTag(r)}</div>
    ${a && a.verdict !== "GO" && a.summary ? `<div class="ai-line">${esc(a.summary)}</div>` : ""}
  </button>`;
}
function rowWatch(r) {
  const fill = Math.max(0, Math.min(1, (20 - (r.rsi2 ?? 20)) / 15));
  return `<button class="row" data-sym="${esc(r.symbol)}">
    <div><div class="sym">${esc(r.symbol)}</div><div class="nm">${esc(r.name)}</div></div>
    ${spark(r.spark)}
    <div><div class="num ${sign(r.r5)}">${spct(r.r5)}</div><div class="sub">5 days</div></div>
    <div class="meta"><span class="gauge" title="2-day RSI ${r.rsi2}; a setup needs below 5"><span><i style="width:${fill * 100}%"></i></span> ${fill >= .9 ? "Very close to a setup" : fill >= .5 ? "Getting close" : "Starting to dip"}</span>
      <span>Rank in strength <b>top ${Math.max(1, Math.round((1 - (r.mom_pct ?? 0)) * 100))}%</b></span>${newsTag(r)}</div>
  </button>`;
}
function rowMine(r) {
  const cls = {Strong: "buy", Mixed: "watch", Weak: "weak"}[r.health];
  const why = r.health === "Strong" ? "Above its 50-day average and in the stronger half of the market"
    : r.health === "Weak" ? "Below its 200-day average or among the weakest stocks. If you hold it, review it."
    : "Trend is mixed";
  return `<button class="row" data-sym="${esc(r.symbol)}">
    <div><div class="sym">${esc(r.symbol)} <span class="tag ${cls}">${esc(r.health)}</span></div><div class="nm">${esc(why)}</div></div>
    ${spark(r.spark)}
    <div><div class="num ${sign(r.r21)}">${spct(r.r21)}</div><div class="sub">1 month</div></div>
  </button>`;
}
function today() {
  const n = L.setups.length, r = L.meta.rules;
  $("#buyLede").textContent = n
    ? `Buy near the open, then sell at the first close above the 5-day average, or after ${r.max_hold} trading days at the latest. % = how often this exact pattern ended in profit after costs.`
    : L.market.regime === "up"
      ? "No leader had a sharp enough dip today. Most days look like this; the rule waits for the right moment."
      : "The rule is switched off while Nifty is below its 200-day average. In past downtrends, dips kept falling.";
  const order = [...L.setups].sort((x, y) => isSkip(x) - isSkip(y));
  $("#setups").innerHTML = n ? order.map(rowSetup).join("") : `<div class="empty">Nothing to buy today.</div>`;
  const ag = L.meta.agents;
  $("#aiLede").hidden = !(n && ag && ag.analysts && ag.analysts.length);
  if (ag && ag.analysts) $("#aiLede").textContent = `The AI news check (${ag.analysts.join(" + ")}) read each pick's headlines. It never changes the rule's prices; it only flags dips caused by real bad news about the company. Skipped picks are still tracked on the Accuracy tab.`;
  $("#watch").innerHTML = L.watch.length ? L.watch.slice(0, 12).map(rowWatch).join("") : `<div class="empty">No leaders are dipping right now.</div>`;
  $("#mine").innerHTML = L.mine.length ? L.mine.map(rowMine).join("")
    : `<div class="empty">Add NSE symbols to <code>watchlist.txt</code> in your GitHub repo to track them here.</div>`;
}

/* ------------------------------------------------------------------ leaders */
let lSort = {k: "rank", dir: 1}, lFilter = "All";
function leaders() {
  const states = ["All", ...new Set(L.leaders.map(r => r.state))];
  $("#stateFilters").innerHTML = states.map(s => `<button class="chip ${s === lFilter ? "on" : ""}" data-s="${esc(s)}">${esc(s)}${s === "All" ? "" : " " + L.leaders.filter(r => r.state === s).length}</button>`).join("");
  $$("#stateFilters .chip").forEach(b => b.onclick = () => { lFilter = b.dataset.s; leaders(); });
  const cols = [["rank", "#", 1], ["symbol", "Stock", 0], ["spark", "3 months", 0], ["r21", "1M", 1], ["r63", "3M", 1], ["r126", "6M", 1],
                ["from_high", "From high", 1], ["state", "Now", 0]];
  let rows = L.leaders.filter(r => lFilter === "All" || r.state === lFilter);
  rows.sort((a, b) => { const x = a[lSort.k], y = b[lSort.k]; return (x > y ? 1 : x < y ? -1 : 0) * lSort.dir; });
  $("#leaderTable").innerHTML = `<thead><tr>${cols.map(([k, t, n]) => `<th class="${n ? "n" : ""}" data-k="${k}" ${lSort.k === k ? `aria-sort="${lSort.dir > 0 ? "ascending" : "descending"}"` : ""}>${t}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr data-sym="${esc(r.symbol)}"><td class="n">${r.rank}</td><td><b>${esc(r.symbol)}</b><div class="muted" style="font-size:12px">${esc((r.industry || "").slice(0, 28))}</div></td>
      <td>${spark(r.spark, 72, 22)}</td><td class="n ${sign(r.r21)}">${spct(r.r21)}</td><td class="n ${sign(r.r63)}">${spct(r.r63)}</td>
      <td class="n ${sign(r.r126)}">${spct(r.r126, 0)}</td><td class="n">${spct(r.from_high)}</td><td>${stateTag(r.state)}</td></tr>`).join("")}</tbody>`;
  $$("#leaderTable th").forEach(th => th.onclick = () => {
    const k = th.dataset.k; if (k === "spark") return;
    lSort = {k, dir: lSort.k === k ? -lSort.dir : (k === "rank" || k === "symbol" || k === "state" ? 1 : -1)}; leaders();
  });
  leaderMap();
}
function leaderMap() {
  const box = $("#leaderMap"), W = box.clientWidth || 640, Hh = 300, pad = {l: 40, r: 14, t: 12, b: 26};
  const pts = L.leaders.filter(r => r.r21 != null && r.r5 != null);
  if (!pts.length) { box.innerHTML = ""; return; }
  const xs = pts.map(r => r.r21), ys = pts.map(r => r.r5);
  const xmax = Math.max(0.05, ...xs.map(Math.abs)) * 1.1, ymax = Math.max(0.03, ...ys.map(Math.abs)) * 1.15;
  const X = v => pad.l + (v + xmax) / (2 * xmax) * (W - pad.l - pad.r), Y = v => pad.t + (ymax - v) / (2 * ymax) * (Hh - pad.t - pad.b);
  const col = s => ({"Dip setup": css("--up"), "Pulling back": css("--watch"), "Near 52-week high": css("--pen"), "Stretched": css("--down")}[s] || css("--ink2"));
  const pri = r => r.state === "Dip setup" ? 0 : r.state === "Pulling back" ? 1 : 2;
  const cand = [...pts].sort((a, b) => pri(a) - pri(b) || a.rank - b.rank).slice(0, W < 500 ? 8 : 14);
  const placed = [], labels = {};
  for (const r of cand) {
    const x = X(r.r21), y = Y(r.r5), w = r.symbol.length * 6.6 + 4;
    const right = x + 8 + w < W - 2;
    const box = right ? [x + 7, y - 7, x + 8 + w, y + 6] : [x - 8 - w, y - 7, x - 7, y + 6];
    if (placed.some(b => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
    placed.push(box); labels[r.symbol] = right ? `x="${x + 8}" text-anchor="start"` : `x="${x - 8}" text-anchor="end"`;
  }
  box.innerHTML = `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Scatter of leaders by 1-month and 5-day returns">
    <rect x="${X(0)}" y="${Y(0)}" width="${X(xmax) - X(0)}" height="${Y(-ymax) - Y(0)}" fill="${css("--watch-soft")}" opacity=".7"/>
    <text x="${X(xmax) - 4}" y="${Y(-ymax) - 6}" text-anchor="end">Dip zone</text>
    <line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="${css("--rule")}"/>
    <line x1="${X(0)}" x2="${X(0)}" y1="${pad.t}" y2="${Hh - pad.b}" stroke="${css("--rule")}"/>
    <text x="${pad.l - 6}" y="${Y(ymax * .8)}" text-anchor="end">${spct(ymax * .8, 0)}</text>
    <text x="${pad.l - 6}" y="${Y(-ymax * .8)}" text-anchor="end">${spct(-ymax * .8, 0)}</text>
    <text x="${X(-xmax * .8)}" y="${Hh - 8}" text-anchor="middle">${spct(-xmax * .8, 0)}</text>
    <text x="${X(xmax * .8)}" y="${Hh - 8}" text-anchor="middle">${spct(xmax * .8, 0)}</text>
    ${pts.map(r => `<g data-sym="${esc(r.symbol)}"><circle cx="${X(r.r21)}" cy="${Y(r.r5)}" r="${r.state === "Dip setup" ? 7 : 5}" fill="${col(r.state)}" fill-opacity=".85" stroke="${css("--sheet")}" stroke-width="1.5"><title>${esc(r.symbol)}: 1M ${spct(r.r21)}, 5D ${spct(r.r5)}</title></circle>
      ${labels[r.symbol] ? `<text class="lbl" ${labels[r.symbol]} y="${Y(r.r5) + 4}">${esc(r.symbol)}</text>` : ""}</g>`).join("")}
  </svg>`;
  $$("#leaderMap g[data-sym]").forEach(g => g.onclick = () => openStock(g.dataset.sym));
}

/* ------------------------------------------------------------------ sectors + market */
let sKey = "r21", sSel = null;
const SCALE = {r1: .02, r5: .05, r21: .10, r63: .20};
function heatColor(v, k) {
  const t = Math.max(-1, Math.min(1, (v ?? 0) / SCALE[k]));
  const mix = (a, b, f) => a.map((x, i) => Math.round(x + (b[i] - x) * f));
  const neutral = [236, 238, 233], pos = [104, 196, 152], neg = [226, 132, 112];
  const c = t >= 0 ? mix(neutral, pos, t) : mix(neutral, neg, -t);
  return `rgb(${c.join(",")})`;
}
function sectors() {
  const secs = [...L.sectors].sort((a, b) => (b[sKey] ?? -9) - (a[sKey] ?? -9));
  $("#heat").innerHTML = secs.map(s => `<button class="cell ${s.name === sSel ? "sel" : ""}" data-n="${esc(s.name)}" style="background:${heatColor(s[sKey], sKey)}">
      <span class="nm">${esc(s.name)}</span><span class="v">${spct(s[sKey])}</span>
      <span class="s">${s.leaders} leader${s.leaders === 1 ? "" : "s"}<br>${pct(s.above50)} in uptrend</span></button>`).join("");
  $$("#heat .cell").forEach(c => c.onclick = () => { sSel = sSel === c.dataset.n ? null : c.dataset.n; sectors(); });
  $$("#secPeriod button").forEach(b => { b.classList.toggle("on", b.dataset.k === sKey); b.onclick = () => { sKey = b.dataset.k; sectors(); }; });
  const d = $("#secDetail"), s = L.sectors.find(x => x.name === sSel);
  d.hidden = !s;
  if (s) d.innerHTML = `<b>${esc(s.name)}</b>: ${s.n} stocks. Median move: 1 day ${spct(s.r1)}, 1 week ${spct(s.r5)}, 1 month ${spct(s.r21)}, 3 months ${spct(s.r63)}.
    Strongest stocks: ${s.top.map(t => BY[t] ? `<a href="#" data-sym="${esc(t)}">${esc(t)}</a>` : esc(t)).join(", ")}.`;
  $$("#secDetail a[data-sym]").forEach(a => a.onclick = e => { e.preventDefault(); openStock(a.dataset.sym); });
}
function lc(el, opts = {}) {
  const c = LightweightCharts.createChart(el, Object.assign({
    autoSize: true, layout: {background: {color: "transparent"}, textColor: css("--ink2"), fontFamily: "Plex, system-ui", fontSize: 11},
    grid: {vertLines: {visible: false}, horzLines: {color: css("--rule")}}, rightPriceScale: {borderVisible: false},
    timeScale: {borderVisible: false}, crosshair: {mode: 0}, handleScroll: false, handleScale: false,
    localization: {priceFormatter: v => Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-IN") : (+v).toFixed(2)}}, opts));
  chartObjs.push(c); return c;
}
function marketCharts() {
  if (!window.LightweightCharts || !L) return;
  const mk = L.market;
  for (const id of ["#niftyChart", "#breadthChart"]) $(id).innerHTML = "";
  if (mk.nifty) {
    const c = lc($("#niftyChart"));
    c.addLineSeries({color: css("--ink"), lineWidth: 2, priceLineVisible: false}).setData(mk.dates.map((t, i) => mk.nifty[i] == null ? null : {time: t, value: mk.nifty[i]}).filter(Boolean));
    c.addLineSeries({color: css("--watch"), lineWidth: 1.5, lineStyle: 2, priceLineVisible: false, lastValueVisible: false}).setData(mk.dates.map((t, i) => mk.nifty_sma200[i] == null ? null : {time: t, value: mk.nifty_sma200[i]}).filter(Boolean));
    c.timeScale().fitContent();
  }
  const b = lc($("#breadthChart"), {rightPriceScale: {borderVisible: false, scaleMargins: {top: .1, bottom: .05}}});
  const pf = {type: "custom", formatter: v => Math.round(v) + "%", minMove: 1};
  b.addAreaSeries({lineColor: css("--up"), topColor: css("--up-soft"), bottomColor: "transparent", lineWidth: 2, priceFormat: pf, priceLineVisible: false})
    .setData(mk.dates.map((t, i) => mk.breadth50[i] == null ? null : {time: t, value: mk.breadth50[i] * 100}).filter(Boolean));
  b.addLineSeries({color: css("--ink2"), lineWidth: 1.5, lineStyle: 2, priceFormat: pf, priceLineVisible: false})
    .setData(mk.dates.map((t, i) => mk.breadth200[i] == null ? null : {time: t, value: mk.breadth200[i] * 100}).filter(Boolean));
  b.timeScale().fitContent();
}

/* ------------------------------------------------------------------ record */
function record() {
  const bt = L.meta.backtest, tr = L.track, r = L.meta.rules;
  const stat = (k, v, s) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
  const yrs = Object.entries(bt.years || {});
  const W = Math.max(320, ($("#recTop").clientWidth || 600) - 30), Hh = 150, max = Math.max(.005, ...yrs.map(([, y]) => Math.abs(y.avg || 0)));
  const bw = W / Math.max(1, yrs.length);
  const bars = yrs.map(([yr, y], i) => {
    const h = Math.abs(y.avg) / max * 55, up = y.avg >= 0;
    return `<rect x="${i * bw + bw * .2}" y="${up ? 70 - h : 70}" width="${bw * .6}" height="${Math.max(1, h)}" rx="3" fill="${up ? css("--up") : css("--down")}"/>
      <text x="${i * bw + bw / 2}" y="${up ? 64 - h : 84 + h}" text-anchor="middle">${spct(y.avg)}</text>
      <text x="${i * bw + bw / 2}" y="${Hh - 18}" text-anchor="middle">${yr}</text>
      <text x="${i * bw + bw / 2}" y="${Hh - 5}" text-anchor="middle">${y.n} trades</text>`;
  }).join("");
  $("#recTop").innerHTML = `
    <p class="lede">The rule was tuned on data before ${short(r.test_split)} ${r.test_split.slice(0, 4)} and then checked on the period after it, which it never saw.
      All returns are after about ${(r.cost * 100).toFixed(2)}% costs per trade.</p>
    <div class="stats">
      ${stat(`All ${r.years} years`, pct(bt.all.win), `of ${bt.all.n} trades made money, avg ${spct(bt.all.avg, 2)}`)}
      ${stat("Unseen period", pct(bt.test.win), `${bt.test.n} trades since ${short(r.test_split)} ${r.test_split.slice(2, 4)}, avg ${spct(bt.test.avg, 2)}`)}
      ${stat("Last 12 months, replayed", tr.done ? pct(tr.win) : "–", tr.done ? `${tr.done} closed, avg ${spct(tr.avg, 2)}` : "no closed picks")}
      ${stat("Live since launch", tr.live?.done ? pct(tr.live.win) : "–", tr.live?.done ? `${tr.live.done} closed, avg ${spct(tr.live.avg, 2)}` : `${tr.live?.open || 0} open, building up`)}
    </div>
    <div class="bars"><b style="font-size:14px">Average result per trade, by year</b>
      <svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Average return per trade by year">
        <line x1="0" x2="${W}" y1="70" y2="70" stroke="${css("--rule")}"/>${bars}</svg></div>`;
  let limit = 40;
  const draw = () => {
    const sf = $("#rStatus").value, live = $("#rLive").checked;
    const all = H.filter(k => (!live || !k.replay) && (sf === "all" || (sf === "open" ? k.status !== "DONE" : k.status === "DONE")));
    const rows = all.slice(0, limit);
    $("#recTable").innerHTML = `<thead><tr><th>Signal</th><th>Stock</th><th class="n">Shown</th><th class="n">Bought</th><th class="n">Sold / now</th><th>Result</th><th class="n">Days</th></tr></thead>
      <tbody>${rows.map(k => {
        const st = k.status === "DONE" ? (k.ret > 0 ? "DONE-w" : "DONE-l") : k.status;
        const lab = k.status === "DONE" ? spct(k.ret) : k.status === "OPEN" ? `Open ${spct(k.ret)}` : "Buys next open";
        return `<tr data-sym="${esc(k.symbol)}"><td>${short(k.date)} ${k.replay ? '<span class="tag">Replay</span>' : ""}</td><td><b>${esc(k.symbol)}</b> ${aiTag(k)}</td>
          <td class="n">${pct(k.prob)}</td><td class="n">${inr(k.entry)}</td><td class="n">${inr(k.price)}</td>
          <td class="st-${st}">${lab}</td><td class="n">${k.days ?? "–"}</td></tr>`;
      }).join("")}</tbody>`;
    let more = $("#recMore");
    if (!more) { more = document.createElement("button"); more.id = "recMore"; more.className = "btn quiet more-btn"; $("#recTable").parentNode.after(more); }
    more.hidden = all.length <= limit;
    more.textContent = `Show more (${all.length - limit} left)`;
    more.onclick = () => { limit += 60; draw(); };
  };
  $("#rStatus").onchange = () => { limit = 40; draw(); }; $("#rLive").onchange = () => { limit = 40; draw(); }; draw();
}


/* ------------------------------------------------------------------ accuracy: prediction vs reality */
let accLive = false, accShow = 10;
function verdict(k) {
  if (k.status === "DONE") return k.ret > 0
    ? {c: "buy", t: "Right", d: `Made ${spct(k.ret)} in ${k.days} day${k.days === 1 ? "" : "s"}`}
    : {c: "weak", t: "Wrong", d: `Lost ${spct(-k.ret).slice(1)} in ${k.days} day${k.days === 1 ? "" : "s"}`};
  if (k.status === "OPEN") return {c: "pen", t: "In progress", d: `${spct(k.ret)} so far, day ${k.days} of ${L.meta.rules.max_hold}`};
  return {c: "watch", t: "Waiting", d: "Buys at the next open"};
}
function niftyMove(dateStr) {
  const mk = L.market, i = mk.dates ? mk.dates.indexOf(dateStr) : -1;
  if (i < 1 || !mk.nifty || mk.nifty[i] == null || mk.nifty[i - 1] == null) return null;
  return mk.nifty[i] / mk.nifty[i - 1] - 1;
}
function accuracy() {
  const pool = H.filter(k => !accLive || !k.replay);
  const by = {};
  pool.forEach(k => (by[k.date] = by[k.date] || []).push(k));
  const dates = Object.keys(by).sort().reverse();
  const sorted = [...pool].sort((a, b) => b.date.localeCompare(a.date));
  const done = sorted.filter(k => k.status === "DONE").slice(0, 30), right = done.filter(k => k.ret > 0);
  const nd = sorted.filter(k => k.d1_ret != null).slice(0, 30), up = nd.filter(k => k.d1_ret > 0);
  const recent = sorted;
  const avg = done.length ? done.reduce((a, k) => a + k.ret, 0) / done.length : null;
  const stat = (k, v, s) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
  // bars: last 24 days that had picks, oldest left
  const bd = dates.slice(0, 24).reverse();
  const W = Math.max(320, ($("#acc").clientWidth || 640) - 30), Hh = 120, bw = W / Math.max(1, bd.length);
  const maxN = Math.max(1, ...bd.map(d => by[d].length));
  const bars = bd.map((d, i) => {
    const ks = by[d], cnt = {buy: 0, weak: 0, pen: 0, watch: 0};
    ks.forEach(k => cnt[verdict(k).c]++);
    let y = Hh - 22, out = "";
    for (const [c, col] of [["buy", "--up"], ["weak", "--down"], ["pen", "--pen"], ["watch", "--watch"]]) {
      const h = cnt[c] / maxN * (Hh - 34);
      if (h > 0) { y -= h; out += `<rect x="${i * bw + bw * .18}" y="${y}" width="${bw * .64}" height="${h}" fill="${css(col)}" rx="2"/>`; }
    }
    return out + (i % Math.ceil(bd.length / 8) === 0 ? `<text x="${i * bw + bw / 2}" y="${Hh - 6}" text-anchor="middle">${short(d)}</text>` : "");
  }).join("");
  const cards = dates.slice(0, accShow).map(d => {
    const ks = by[d].sort((a, b) => b.prob - a.prob);
    const fin = ks.filter(k => k.status === "DONE"), ok = fin.filter(k => k.ret > 0).length;
    const d1 = ks.find(k => k.d1_date)?.d1_date, nm = d1 ? niftyMove(d1) : null;
    const score = fin.length ? `${ok} of ${fin.length} right` : "Not finished yet";
    return `<article class="day">
      <header><div><b>Predicted ${day(d)}</b><div class="muted">${ks.length} buy${ks.length > 1 ? "s" : ""} for ${d1 ? day(d1) : "the next session"}${nm != null ? `, Nifty that day <span class="${sign(nm)}">${spct(nm)}</span>` : ""}</div></div>
        <span class="tag ${fin.length ? (ok === fin.length ? "buy" : ok === 0 ? "weak" : "watch") : ""}">${score}</span></header>
      ${ks.map(k => { const v = verdict(k); return `<div class="pk" data-sym="${esc(k.symbol)}">
        <div class="pk-a"><b>${esc(k.symbol)}</b> ${aiTag(k)}<span class="muted">${pct(k.prob)} chance shown, close ${inr(k.signal_close)}</span></div>
        <div class="pk-b">${k.d1_close != null ? `Next day: opened ${inr(k.d1_open)} <span class="${sign(k.d1_gap)}">(${spct(k.d1_gap)})</span>, closed ${inr(k.d1_close)} <b class="${sign(k.d1_ret)}">${spct(k.d1_ret)}</b>` : `<span class="muted">Next day's prices not in yet</span>`}</div>
        <div class="pk-c"><span class="tag ${v.c}">${v.t}</span> <span class="muted">${v.d}</span>${k.replay ? ' <span class="tag">Replay</span>' : ""}</div>
      </div>`; }).join("")}
    </article>`;
  }).join("");
  $("#acc").innerHTML = `
    <div class="filters"><label><input type="checkbox" id="accLive" ${accLive ? "checked" : ""}> Only live picks (made after launch, not replayed)</label></div>
    <div class="stats">
      ${stat("Right, last 30 finished", done.length ? pct(right.length / done.length) : "–", done.length ? `${right.length} of the last ${done.length} finished picks made money` : "No finished picks yet")}
      ${stat("Average result", avg != null ? spct(avg, 2) : "–", "per finished pick, after costs")}
      ${stat("Up the next day", nd.length ? pct(up.length / nd.length) : "–", nd.length ? `${up.length} of the last ${nd.length} closed above the signal price` : "–")}
      ${stat("Still open", recent.filter(k => k.status !== "DONE").length, "in progress or waiting")}
    </div>
    ${bd.length ? `<div class="bars"><b style="font-size:14px">Day by day</b> <span class="muted" style="font-size:13px">Green right, red wrong, blue in progress, yellow waiting</span>
      <svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Right and wrong picks per day">${bars}</svg></div>` : ""}
    <div class="days">${cards || `<div class="rows"><div class="empty">No picks yet. ${accLive ? "Live picks start from the first scan after launch." : ""}</div></div>`}</div>
    ${dates.length > accShow ? `<button class="btn quiet more-btn" id="accMore">Show more days (${dates.length - accShow} left)</button>` : ""}`;
  $("#accLive").onchange = e => { accLive = e.target.checked; accShow = 10; accuracy(); };
  const mb = $("#accMore"); if (mb) mb.onclick = () => { accShow += 10; accuracy(); };
}

/* ------------------------------------------------------------------ AI check vs plain rule */
function aiCheck() {
  const ag = L.track.agent, info = L.meta.agents;
  const stat = (k, v, s) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
  if (!ag) {
    $("#ai").innerHTML = `<p class="lede">${info && info.analysts && info.analysts.length
      ? "The AI news check is on. Results appear here once its first picks are bought and sold."
      : "The AI news check isn't set up yet, so every pick goes through on the rule alone. See README → AI news check."}</p>`;
    return;
  }
  const g = (x, lab) => x && x.done ? `${pct(x.win)} won, avg ${spct(x.avg, 2)}, ${x.done} closed` : `${(x && x.open) || 0} open, none closed yet`;
  const pe = ag.paper.every, pa = ag.paper.ai, diff = pa.value - pe.value;
  const skipAvg = ag.skip.done ? ag.skip.avg : null, keepRows = [ag.go, ag.caution].filter(x => x.done);
  const keepAvg = keepRows.length ? keepRows.reduce((a, x) => a + x.avg * x.done, 0) / keepRows.reduce((a, x) => a + x.done, 0) : null;
  let say;
  if (skipAvg == null || keepAvg == null) say = "Not enough closed picks yet to say whether the AI helps.";
  else say = skipAvg < keepAvg
    ? `So far the picks the AI skipped did worse (${spct(skipAvg, 2)} avg) than the ones it let through (${spct(keepAvg, 2)}). That's what you'd want to see.`
    : `So far the picks the AI skipped did no worse (${spct(skipAvg, 2)} avg) than the ones it let through (${spct(keepAvg, 2)}). The AI isn't helping yet.`;
  const n = ag.all.done;
  $("#ai").innerHTML = `
    <p class="lede">Every live pick since ${short(ag.since)} was checked by the AI, and every one is still tracked with the rule's own exits, including the ones it said to skip.
      Two virtual accounts of ${inr(pe.start)} put ${inr(pe.per_trade)} into each pick: one follows every pick, the other skips what the AI skipped.</p>
    <div class="stats">
      ${stat("Follow every pick", inr(pe.value), `${spct(pe.pnl / pe.start, 2)} on ${pe.trades} trades`)}
      ${stat("Follow the AI", inr(pa.value), `${spct(pa.pnl / pa.start, 2)} on ${pa.trades} trades · ${diff >= 0 ? "+" : "−"}${inr(Math.abs(diff))} vs every pick`)}
      ${stat("AI said go", ag.go.done ? pct(ag.go.win) : "–", g(ag.go))}
      ${stat("AI said caution", ag.caution.done ? pct(ag.caution.win) : "–", g(ag.caution))}
      ${stat("AI said skip", ag.skip.done ? pct(ag.skip.win) : "–", g(ag.skip))}
    </div>
    <p class="lede">${say} ${n < 150 ? `Only ${n} closed so far; about 150–600 are needed before this means much, so keep following the rule until then.` : ""}</p>`;
}

/* ------------------------------------------------------------------ how it works */
function how() {
  const r = L.meta.rules, bt = L.meta.backtest;
  $("#appVersion").innerHTML = `Version ${esc(L.meta.app_version || "–")}. <a href="https://github.com/Jetlin1011/stock-crawler/blob/main/CHANGELOG.md" target="_blank" rel="noopener">See what changed</a>`;
  $("#how").innerHTML = `
  <h2>How it works</h2>
  <p>Every weekday evening a scan runs on GitHub's servers. It downloads prices for ${L.meta.scanned} NSE stocks (the Nifty 500 plus your watchlist),
    fills in the latest day from NSE's official end-of-day file when Yahoo is late, and rebuilds this app. Then it sends the notification.</p>
  <h2>The rule</h2>
  <ol>
    <li><b>Leaders only.</b> Stocks in the top ${Math.round((1 - r.leader_pct) * 100)}% by 6- and 12-month strength, adjusted for volatility (the same method as NSE's momentum indices), above their 200-day average, trading at least ₹${r.min_turnover_cr} crore a day.</li>
    <li><b>Sharp dip.</b> The 2-day RSI falls below ${r.dip_rsi2}, meaning two or three hard down days.</li>
    <li><b>No panic volume.</b> Volume under ${r.max_vol}× its 20-day average. Heavy-volume drops often come with real news and tend to keep falling.</li>
    <li><b>Healthy market.</b> Nifty above its 200-day average.</li>
    <li><b>Exit.</b> Buy at the next open. Sell at the first close above the 5-day average, or after ${r.max_hold} trading days.</li>
  </ol>
  <p>Over ${r.years} years this made money on ${pct(bt.all.win)} of ${bt.all.n} trades, averaging ${spct(bt.all.avg, 2)} each after costs.
    Since ${short(r.test_split)} ${r.test_split.slice(0, 4)} (data the rule wasn't tuned on): ${pct(bt.test.win)} and ${spct(bt.test.avg, 2)}.
    That's a small edge per trade. It only adds up over many trades, so keep position sizes equal and modest.</p>
  <h2>AI news check</h2>
  <p>After the rule picks its buys, two AIs read each stock's headlines from the past week. Claude does it on your Claude Pro plan,
    and Google Gemini (free) gives a second opinion. They answer one question: did it fall because of real bad news about the company?</p>
  <ol>
    <li><b>AI: no bad news.</b> Buy as normal.</li>
    <li><b>AI: read the news first.</b> One AI found bad news, or it's minor. Open the stock and decide yourself.</li>
    <li><b>AI: skip.</b> Both found serious bad news (fraud, regulator action, weak results, a downgrade…). The alert leaves it out.</li>
  </ol>
  <p>The AIs never change prices, never add picks, and must quote a real headline, or their answer is ignored. A plain rule, not an AI,
    makes the final call. Skipped picks are still followed on paper, so the Accuracy tab shows whether skipping them was actually right.</p>
  <h2>Using it with Zerodha</h2>
  <ol>
    <li>In the evening, read the notification or the Today tab.</li>
    <li>Next morning, buy each setup in delivery (CNC) around the open. Skip it if it opens far above the signal close.</li>
    <li>Each evening, check: if it closed above its 5-day average (shown on the stock's page), sell the next morning. Sell anyway after ${r.max_hold} trading days.</li>
    <li>Use the same amount on every trade. Don't put more than 5–10% of your trading money in any one stock.</li>
  </ol>
  <h2>What the other screens mean</h2>
  <ul>
    <li><b>On watch</b>: leaders already dipping that may become setups.</li>
    <li><b>Leaders</b>: the hot list. These are the stocks to keep in mind. The dot map shows which are rising and which are pulling back.</li>
    <li><b>Sectors</b>: which industries are moving. More leaders in a sector means stronger money flow into it.</li>
    <li><b>Your watchlist</b>: Strong / Mixed / Weak trend health for your own stocks.</li>
  </ul>
  <h2>Limits</h2>
  <p>Past results don't guarantee future ones. The test uses today's Nifty 500 members, which flatters results a little. News tags are keyword-based, so read the headlines yourself.
    This tool shortlists stocks; it isn't investment advice.</p>`;
}

/* ------------------------------------------------------------------ stock sheet */
let lastFocus = null;
async function openStock(sym) {
  const r = BY[sym]; if (!r) return;
  lastFocus = document.activeElement;
  const isSetup = L.setups.some(s => s.symbol === sym), mr = L.meta.rules;
  const card = $("#sheetCard");
  const plan = isSetup ? `
    <div class="plan">
      <div><span class="k">Buy</span><span>At the next open, near ${inr(r.close)}. Skip it if it opens more than 2% higher.</span></div>
      <div><span class="k">Sell</span><span>At the first close above the 5-day average (now ${inr(r.sma5)}), or after ${mr.max_hold} trading days.</span></div>
      ${r.agent ? `<div><span class="k">AI check</span><span>${aiTag(r)} ${esc(r.agent.summary || "")}
        ${r.agent.evidence ? `<span class="quote">“${esc(r.agent.evidence)}”</span>` : ""}
        ${(r.agent.opinions || []).length > 1 ? `<span class="muted">${r.agent.opinions.map(o => `${esc(o.by.split(" ")[0])}: ${esc(o.cause.replace(/_/g, " "))}`).join(" · ")}</span>` : ""}</span></div>` : ""}
      <div><span class="k">History</span><span>${pct(r.prob)} of ${Number(r.base_n).toLocaleString("en-IN")} similar trades made money, averaging ${spct(r.ev, 2)} after costs.${r.own_n ? ` This stock: ${r.own_wins} of ${r.own_n}.` : ""}</span></div>
    </div>` : `
    <div class="plan">
      <div><span class="k">Now</span><span>${stateTag(r.state)}${r.health ? ` <span class="tag">${esc(r.health)}</span>` : ""}</span></div>
      <div><span class="k">Strength</span><span>Top ${Math.max(1, Math.round((1 - (r.mom_pct ?? 0)) * 100))}% of scanned stocks over 6–12 months</span></div>
      <div><span class="k">Setup needs</span><span>2-day RSI below ${mr.dip_rsi2} (now ${r.rsi2 ?? "–"}), calm volume and Nifty in an uptrend</span></div>
    </div>`;
  card.innerHTML = `
    <div class="sh-top"><button class="back" id="sheetBack"><svg><use href="#i-back"/></svg>Back</button></div>
    <div class="sh-h"><div><h3 id="sheetTitle">${esc(sym)}</h3><div class="nm">${esc(r.name)}${r.industry ? ", " + esc(r.industry) : ""}</div></div>
      <div class="px">${inr(r.close)}<div class="nm ${sign(r.r1)}">${spct(r.r1)} today</div></div></div>
    ${plan}
    <div class="stats">
      <div class="stat"><div class="k">1 month</div><div class="v ${sign(r.r21)}">${spct(r.r21)}</div></div>
      <div class="stat"><div class="k">6 months</div><div class="v ${sign(r.r126)}">${spct(r.r126, 0)}</div></div>
      <div class="stat"><div class="k">From 52-week high</div><div class="v">${spct(r.from_high)}</div></div>
      <div class="stat"><div class="k">Volume vs usual</div><div class="v">${r.vol_ratio != null ? r.vol_ratio.toFixed(1) + "×" : "–"}</div>${r.delivery != null ? `<div class="s">Delivery ${r.delivery.toFixed(0)}%</div>` : ""}</div>
    </div>
    <div class="chart" id="stockChart"></div>
    <div class="legend"><span style="--c:${css("--pen")}">5-day avg (exit line)</span><span style="--c:${css("--watch")}">50-day avg</span><span style="--c:${css("--ink2")}">200-day avg</span></div>
    <h2>Headlines this week</h2>
    ${newsList(r)}`;
  $("#sheet").hidden = false; document.body.style.overflow = "hidden";
  $("#sheetBack").onclick = closeSheet; $("#sheetBack").focus();
  const all = await charts(), d = all[sym], box = $("#stockChart");
  if (!d || !window.LightweightCharts) { box.innerHTML = `<div class="empty">Chart unavailable.</div>`; return; }
  const c = lc(box, {handleScroll: true, handleScale: true});
  const cs = c.addCandlestickSeries({upColor: css("--up"), downColor: css("--down"), wickUpColor: css("--up"), wickDownColor: css("--down"), borderVisible: false});
  cs.setData(d.t.map((t, i) => d.c[i] == null ? null : {time: t, open: d.o[i], high: d.h[i], low: d.l[i], close: d.c[i]}).filter(Boolean));
  const line = (arr, color, w = 1.5) => c.addLineSeries({color, lineWidth: w, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false})
    .setData(d.t.map((t, i) => arr[i] == null ? null : {time: t, value: arr[i]}).filter(Boolean));
  line(d.sma5, css("--pen"), 2); line(d.sma50, css("--watch")); line(d.sma200, css("--ink2"));
  if (isSetup) cs.setMarkers([{time: d.t[d.t.length - 1], position: "belowBar", color: css("--up"), shape: "arrowUp", text: "setup"}]);
  c.timeScale().setVisibleLogicalRange({from: d.t.length - 90, to: d.t.length + 2});
}
function newsList(r) {
  if (!L.meta.news) return `<p class="muted">News check is off for this run.</p>`;
  if (!r.news) return `<p class="muted">Headlines are checked for setups, watch-list stocks and the top leaders only.</p>`;
  if (!r.news.length) return `<p class="muted">No headlines in the past week. The move looks price-driven.</p>`;
  const tone = {neg: '<span class="tag weak">Negative</span> ', pos: '<span class="tag buy">Positive</span> ', neutral: ""};
  return `<ul class="news">${r.news.map(n => `<li>${tone[n.tone] || ""}<a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>
    <div class="src">${esc(n.source)}, ${short(n.date)}</div></li>`).join("")}</ul>`;
}
function closeSheet() {
  $("#sheet").hidden = true; document.body.style.overflow = "";
  if (lastFocus) lastFocus.focus();
}
$("#sheet").addEventListener("click", e => { if (e.target.id === "sheet") closeSheet(); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#sheet").hidden) closeSheet(); });
document.addEventListener("click", e => {
  const el = e.target.closest("[data-sym]");
  if (el && !el.closest("#leaderMap") && !el.closest("#secDetail") && !el.closest("#sheet")) openStock(el.dataset.sym);
});

/* ------------------------------------------------------------------ tabs */
function showTab(name) {
  $$("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("on", t.id === "tab-" + name));
  if (name === "sectors") requestAnimationFrame(marketCharts);
  if (name === "leaders" && L) requestAnimationFrame(leaderMap);
  if (name === "record" && L) requestAnimationFrame(accuracy);
  scrollTo({top: 0});
  try { history.replaceState(null, "", "#" + name); } catch (e) {}
}
$("#tabs").onclick = e => { const b = e.target.closest("button"); if (b) showTab(b.dataset.tab); };
addEventListener("resize", () => { if (L && $("#tab-leaders").classList.contains("on")) leaderMap(); });

/* ------------------------------------------------------------------ PWA: refresh, install, push */
$("#refreshBtn").onclick = () => refresh(true);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });
setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 15 * 60 * 1000);
addEventListener("online", () => refresh());

const isStandalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
$("#installState").textContent = isStandalone ? "Installed. You're using the app." : "";
let deferredPrompt = null;
addEventListener("beforeinstallprompt", e => { e.preventDefault(); deferredPrompt = e; $("#installBtn").hidden = false; });
$("#installBtn").onclick = async () => { if (!deferredPrompt) return; deferredPrompt.prompt(); await deferredPrompt.userChoice; deferredPrompt = null; $("#installBtn").hidden = true; };

function b64ToBytes(b64) {
  const raw = atob((b64 + "=".repeat((4 - b64.length % 4) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, c => c.charCodeAt(0));
}
function showPushCode(sub) {
  $("#pushCode").hidden = false; $("#pushJson").value = JSON.stringify(sub);
  $("#pushState").textContent = "Notifications are on for this device."; $("#pushBtn").textContent = "Show device code";
}
async function pushUI() {
  const st = $("#pushState"), btn = $("#pushBtn");
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    btn.disabled = true;
    st.textContent = isIOS && !isStandalone ? "Add the app to your Home Screen first, then open it from there." : "This browser doesn't support notifications.";
    return;
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) showPushCode(sub);
  btn.onclick = async () => {
    const ex = await reg.pushManager.getSubscription();
    if (ex) return showPushCode(ex);
    const key = L && L.meta.vapid_public;
    if (!key) { st.textContent = "Push keys aren't set up in GitHub yet."; return; }
    if (await Notification.requestPermission() !== "granted") { st.textContent = "Permission wasn't given. You can allow it in your phone's settings."; return; }
    try { showPushCode(await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: b64ToBytes(key)})); }
    catch (e) { st.textContent = "Couldn't subscribe: " + e.message; }
  };
  $("#copyPush").onclick = async () => {
    try { await navigator.clipboard.writeText($("#pushJson").value); } catch (e) { $("#pushJson").select(); document.execCommand("copy"); }
    toast("Copied");
  };
}

let toastT;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 2600);
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
  navigator.serviceWorker.addEventListener("message", e => { if (e.data?.type === "refresh") refresh(); });
}
const start = (location.hash || "").slice(1);
if (["today", "leaders", "sectors", "record", "more"].includes(start)) showTab(start);
refresh().then(pushUI);
