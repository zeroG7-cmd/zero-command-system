/* zeroGravity Office - live shell (build 1).
 *
 * Ported from the approved Round 1 mockup. Reads everything from one
 * endpoint, GET /business/data (modules/business_office.py), and re-fetches
 * after every action. Nothing here can mark a READY item done: items clear
 * only when the backend's check passes. Hash routes: #ready #research
 * #leads #plan #content, plus locked #money #jobs #site #serv.
 */
(function () {
"use strict";

var $ = function (id) { return document.getElementById(id); };
var esc = function (s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
};
var pct = function (n, d) { return d ? (n / d * 100).toFixed(1) + "%" : "0%"; };
var DATA = null;
var UI = { tier: "all", sec: 4, comp: null };
var LOGO = window.OFFICE_LOGO || "";

var NAV = [
  ["A", "ready", "READY", "Launch readiness"],
  ["A", "research", "RSRCH", "Market research"],
  ["A", "leads", "LEADS", "Leads"],
  ["A", "plan", "PLAN", "King's Trust plan"],
  ["A", "content", "CONTENT", "Content pipeline"],
  ["B", "money", "MONEY", "Money, not built yet"],
  ["C", "jobs", "JOBS", "Jobs, phase 2, locked"],
  ["C", "site", "SITE", "Site pack, phase 2, locked"],
  ["C", "serv", "SERV", "Services, phase 3, locked"]
];
var CRUMB = { ready: "LAUNCH READINESS", research: "MARKET RESEARCH", leads: "LEADS", plan: "KING'S TRUST PLAN",
  content: "CONTENT PIPELINE", money: "MONEY", jobs: "JOBS", site: "SITE PACK", serv: "SERVICES" };

var toastT;
function toast(m) {
  var t = $("toast"); t.textContent = m; t.classList.add("on");
  clearTimeout(toastT); toastT = setTimeout(function () { t.classList.remove("on"); }, 2800);
}
function post(url, body) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })
    .then(function (r) { return r.json().catch(function () { return { ok: r.ok }; }); });
}

/* ---------- markup helpers ---------- */
function pn(title, right, body, warm) {
  return '<section><div class="bh' + (warm ? " w" : "") + '"><span>' + esc(title) + "</span><em>" + esc(right || "") + '</em></div><div class="fr">' + body + "</div></section>";
}
function row(t, sub, ev, tag, cls) {
  return '<div class="row"><b>' + esc(t) + "</b>" + (sub ? "<small>" + esc(sub) + "</small>" : "") +
    (ev ? '<small class="ev">' + esc(ev) + "</small>" : "") + '<span class="r tg ' + esc(cls || "") + '">' + esc(tag) + "</span></div>";
}
function kv(k, v, style) { return '<div class="kv"><span>' + esc(k) + "</span><b" + (style ? ' style="' + style + '"' : "") + ">" + esc(v) + "</b></div>"; }
function tile(label, val, sub, warm) { return '<div class="hc"><span>' + esc(label) + "</span><b" + (warm ? ' class="w"' : "") + ">" + esc(val) + "</b><small>" + esc(sub) + "</small></div>"; }
function errBox(e) { return e ? '<div class="err">' + esc(e) + "</div>" : ""; }
function ringDash(ratio, circ) { return (circ * ratio).toFixed(1) + " " + circ; }
function setBanner(html) { $("banner").innerHTML = html || ""; }

/* ---------- shell ---------- */
function route() { var h = (location.hash || "#ready").slice(1); return CRUMB[h] ? h : "ready"; }

function drawRing(cur) {
  var html = "", last = null;
  NAV.forEach(function (n) {
    if (last && last !== n[0]) html += '<span class="hsep" aria-hidden="true"></span>';
    last = n[0];
    var cls = "hub" + (n[0] === "C" ? " lock" : "") + (n[0] === "B" ? " nb" : "") + (n[1] === cur ? " on" : "");
    html += '<a class="' + cls + '" href="#' + n[1] + '" aria-label="' + esc(n[3]) + '">' + n[2] + "</a>";
  });
  $("ring").innerHTML = html;
}

function render() {
  var cur = route();
  drawRing(cur);
  $("crumb").textContent = CRUMB[cur];
  if (!DATA) return;
  var r = DATA.ready;
  if (r) {
    $("miniRing").setAttribute("stroke-dasharray", ringDash(r.ratio, 314.2));
    $("sub").textContent = "BUSINESS OPS · CORE " + r.ratio.toFixed(2) + " · COMPANY LV " + (DATA.company ? DATA.company.level : 1);
  }
  setBanner("");
  var fn = { ready: viewReady, research: viewResearch, leads: viewLeads, plan: viewPlan, content: viewContent,
    money: viewMoney, jobs: viewJobs, site: viewSite, serv: viewServ }[cur];
  $("page").innerHTML = fn();
}

/* ---------- READY ---------- */
function radar(stats) {
  var cx = 100, cy = 100, R = 80, pts = [], axes = "", labels = "";
  var pos = [[100, 12, "middle"], [174, 56, "start"], [174, 148, "start"], [100, 195, "middle"], [26, 152, "end"], [26, 56, "end"]];
  stats.forEach(function (s, i) {
    var a = -Math.PI / 2 + i * Math.PI / 3, v = Math.max(0.02, s[1]);
    pts.push((cx + Math.cos(a) * R * v).toFixed(1) + "," + (cy + Math.sin(a) * R * v).toFixed(1));
    axes += '<line x1="100" y1="100" x2="' + (cx + Math.cos(a) * R).toFixed(1) + '" y2="' + (cy + Math.sin(a) * R).toFixed(1) + '" stroke="rgba(112,255,180,.12)"></line>';
    labels += '<text x="' + pos[i][0] + '" y="' + pos[i][1] + '" text-anchor="' + pos[i][2] + '" style="font:600 9px Chakra Petch,sans-serif;fill:' + (s[1] > 0 ? "#70ffb4" : "#8eaa9b") + '">' + esc(s[0]) + (s[1] > 0 ? " " + s[1].toFixed(2).slice(1) : "") + "</text>";
  });
  return '<svg width="270" height="205" viewBox="-35 0 270 205" role="img" aria-label="Company stats hexagon">' +
    '<polygon points="100,20 169.3,60 169.3,140 100,180 30.7,140 30.7,60" fill="none" stroke="rgba(112,255,180,.25)"></polygon>' + axes +
    '<polygon points="' + pts.join(" ") + '" fill="rgba(112,255,180,.3)" stroke="#70ffb4" stroke-width="1.5"></polygon>' + labels + "</svg>";
}

function viewReady() {
  var r = DATA.ready;
  if (!r) return errBox("READY failed to load: " + DATA.ready_error);
  var claimedNoProof = r.filed;
  var core = '<div class="core"><svg width="190" height="190" viewBox="0 0 120 120" role="img" aria-label="Launch readiness ' + r.ratio.toFixed(2) + ", " + r.verified + " of " + r.total + ' verified">' +
    '<polygon points="60,6 107,33 107,87 60,114 13,87 13,33" fill="none" stroke="rgba(112,255,180,.3)" stroke-width="1"></polygon>' +
    '<circle cx="60" cy="60" r="44" fill="none" stroke="rgba(255,255,255,.1)" stroke-width="6"></circle>' +
    '<circle cx="60" cy="60" r="44" fill="none" stroke="#70ffb4" stroke-width="6" stroke-dasharray="' + ringDash(r.ratio, 276.5) + '" transform="rotate(-90 60 60)"></circle>' +
    '<text x="60" y="84" text-anchor="middle" style="font:700 17px Chakra Petch,sans-serif;fill:#70ffb4">' + r.ratio.toFixed(2) + "</text>" +
    '<text x="60" y="94" text-anchor="middle" style="font:600 5.5px Chakra Petch,sans-serif;letter-spacing:.2em;fill:#8eaa9b">BUSINESS CORE</text></svg>' +
    '<img src="' + esc(LOGO) + '" alt=""></div>';
  var left = pn("LAUNCH READINESS", "VERIFIED ONLY",
    '<div style="display:grid;justify-items:center;gap:10px;padding:10px 0">' + core +
    '<div style="font:500 12px IBM Plex Mono,monospace;color:#8eaa9b">' + r.verified + " of " + r.total + " verified</div></div>" +
    '<div class="pb"><i style="width:' + Math.round(r.ratio * 100) + '%"></i></div>' +
    '<button class="btn main" type="button" data-act="checks"><span>RUN CHECKS</span><small>re-reads every source</small></button>' +
    '<p class="nt" style="text-align:center">No "mark done" button anywhere. An item clears only when its check passes and writes a receipt.</p>');
  var edited = findItem("footage_edited");
  var next = pn("NEXT UNLOCK", "BOTTLENECK",
    '<div style="font:700 18px Chakra Petch,sans-serif;letter-spacing:.04em">' + (edited && edited.passed ? "Build portfolio piece 2" : "Export a first cut") + "</div>" +
    '<p class="nt">' + esc(edited ? edited.now : "") + ". Export a 30 to 60s cut into a project's <b>exports/</b> folder and <b>Footage edited</b> clears itself.</p>" +
    '<a class="btn" href="#content"><span>OPEN CONTENT PIPELINE</span><small>→</small></a>', true);
  var qw = r.quick_wins.map(function (q) { return row(q.title, q.sub, q.ev, "TODAY", "wip"); }).join("") ||
    '<div class="empty">No quick wins left. Nice.</div>';
  var quick = pn("QUICK WINS", "UNDER 1 HOUR", qw + '<p class="nt">Picked from uncleared READY items that take under an hour, biggest unlock first. When one clears, the next slides in.</p>');

  var tiles = '<div class="tiles">' + tile("VERIFIED", r.verified + " / " + r.total, "receipts on file") +
    tile("FILED, AWAITING CHECK", claimedNoProof, "doesn't count yet", true) +
    tile("IN PROGRESS", r.in_progress, "signal found, not cleared", true) + tile("REVENUE", "£0", "this launch") + "</div>";
  var gates = '<div class="auto">' + r.gates.map(function (g) {
    return pn(g.name, g.score, g.items.map(function (i) { return row(i.title, "CHECK · " + i.check, i.now, i.status, i.cls); }).join(""));
  }).join("") + "</div>";

  var c = DATA.company;
  var company = c ? pn("COMPANY", "LEVEL " + c.level + " · STATS CAN DROP",
    '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:14px">' + radar(c.stats) +
    '<div style="flex:1 1 160px;display:grid;gap:8px">' + kv("Company level", c.level + " · never drops") + kv("Company XP", c.xp + " / [N] to L2") +
    '<div class="pb"><i style="width:2%"></i></div><p class="nt">' + esc(c.formula_note) + ".</p></div></div>") : errBox(DATA.company_error);
  var ledgers = pn("ONE EVENT · TWO LEDGERS", "PROPOSED",
    '<div class="kv"><span class="lb">OUTCOME (VERIFIED)</span><span class="lb">COMPANY XP · ZERO XP</span></div>' +
    kv("Lead contacted", "+10 · none") + kv("Quote sent", "+40 · Business skill") + kv("Portfolio piece live", "+50 · Creative Prod.") +
    kv("Job delivered", "+120 · Aviation (Flights)") + kv("Payment received", "Revenue stat · none") +
    '<p class="nt">Company XP and level live in the Office only. Zero only gets a share when <b>you</b> used a skill. Money never pays Zero. Payouts switch on in build 2.</p>', true);

  return '<div class="cols"><div class="side">' + left + next + quick + "</div>" +
    '<div class="wide">' + tiles + gates + '<div class="auto" style="--min:320px">' + company + ledgers + "</div></div></div>";
}
function findItem(id) {
  var out = null;
  (DATA.ready ? DATA.ready.gates : []).forEach(function (g) { g.items.forEach(function (i) { if (i.id === id) out = i; }); });
  return out;
}

/* ---------- RESEARCH ---------- */
function bars(list, total, max, warmKeys, mutedKeys) {
  return list.map(function (kvp) {
    var k = kvp[0].toLowerCase(), cls = "";
    if (warmKeys.some(function (w) { return k.indexOf(w) >= 0; })) cls = "w";
    else if (mutedKeys === true || mutedKeys.some(function (m) { return k.indexOf(m) >= 0; })) cls = "m";
    return '<div class="bar"><span>' + esc(kvp[0]) + '</span><span class="trk"><i class="' + cls + '" style="width:' + (kvp[1] / max * 100).toFixed(1) + '%"></i></span><b>' + kvp[1] + " · " + pct(kvp[1], total) + "</b></div>";
  }).join("");
}
function viewResearch() {
  var R = DATA.research;
  if (!R) return errBox("RESEARCH failed: " + DATA.research_error);
  var S = R.survey || {}, comps = R.competitors || { areas: [], competitors: [] };
  var html = "";
  if (R.survey_error || S.warning) html += errBox(R.survey_error || S.warning);
  var total = S.total || 0;
  var synced = S.last_synced ? S.last_synced.slice(0, 10) : "never";
  var days = S.last_synced ? Math.floor((Date.now() - new Date(S.last_synced).getTime()) / 864e5) : null;
  var pay100 = (S.budgets || []).filter(function (b) { return !/^£50/.test(b[0]); }).reduce(function (a, b) { return a + b[1]; }, 0);
  var never = (S.used_before || []).filter(function (u) { return /^no/i.test(u[0]); }).reduce(function (a, b) { return a + b[1]; }, 0);
  html += '<div class="tiles">' + tile("RESPONSES", total, "customer_survey_responses") +
    tile("LAST SYNCED", synced, days === null ? "" : days + " days ago", days !== null && days > 30) +
    tile("NEVER USED A DRONE SERVICE", pct(never, total), "first-adopter market") +
    tile("WOULD PAY £100+", pct(pay100, total), pay100 + " of " + total) +
    tile("COMPETITORS LOGGED", comps.competitors.length, "swept " + (comps.swept_at || "")) + "</div>";

  // competitors by area
  var filters = [["all", "ALL"], ["LOCAL", "LOCAL"], ["MID", "MID-TIER"], ["INSPECT", "INSPECTION"], ["HIGH", "HIGH-END"], ["CONTENT", "CONTENT"]];
  var TCLS = { LOCAL: "done", MID: "", INSPECT: "wip", HIGH: "todo", CONTENT: "conf" };
  var fb = filters.map(function (f) { return '<button type="button" class="fbtn' + (UI.tier === f[0] ? " on" : "") + '" data-act="tier" data-v="' + f[0] + '">' + f[1] + "</button>"; }).join("");
  var areas = comps.areas.map(function (a) {
    var all = comps.competitors.filter(function (c) { return c.area === a.id; });
    var vis = all.filter(function (c) { return UI.tier === "all" || c.tier === UI.tier; });
    return '<div class="area"><div class="areah"><span>' + esc(a.name) + "</span><em>" + vis.length + '</em></div><small class="nt">' + esc(a.sub) + "</small>" +
      (vis.map(function (c) {
        return '<button type="button" class="cbtn" data-act="comp" data-v="' + esc(c.id) + '"><span class="hd"><b>' + esc(c.name) + '</b><span class="tg ' + TCLS[c.tier] + '">' + esc(c.tier) + "</span></span><small>" + esc(c.base) + "</small><small>" + esc(c.short) + "</small></button>";
      }).join("") || '<div class="empty">' + (all.length ? "None at this tier" : "No sweep done here yet") + "</div>") + "</div>";
  }).join("");
  html += pn("COMPETITORS BY AREA", "CLICK ONE FOR INTEL",
    '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center"><span class="lb" style="margin-right:4px">SHOW</span>' + fb + "</div>" +
    '<div class="auto" style="--min:240px">' + areas + "</div>");

  var maxS = (S.services && S.services[0]) ? S.services[0][1] : 1;
  var svc = pn("SERVICE INTEREST", "% OF " + total + " · MULTI-SELECT",
    bars(S.services || [], total, maxS, ["construction"], ["real estate", "surveillance", "logistics", "delivery", "agriculture", "church"]) +
    '<p class="nt">Construction / inspections is your third-biggest signal and isn\'t in your plan. It points at Shadow\'s data collection work.</p>');
  var prices = { "£50–£100": [], "£100–£200": ["RE photo £150", "Social £150", "Event £200"], "£200–£500": ["RE photo+video £250", "Event ext £350", "FPV £350 to 500"] };
  var bandsHtml = (S.budgets || []).slice().sort(function (a, b) { return (parseInt(a[0].replace(/\D+/, ""), 10) || 0) - (parseInt(b[0].replace(/\D+/, ""), 10) || 0); }).map(function (b) {
    var chips = (prices[b[0]] || []).map(function (c) { return '<span class="chip">' + esc(c) + "</span>"; }).join("") || '<small class="nt">none of your prices fit</small>';
    return '<div class="band"><div class="top2"><span class="lb">' + esc(b[0]) + "</span><b>" + pct(b[1], total) + '</b></div><div class="pb"><i style="width:' + pct(b[1], total) + '"></i></div><div>' + chips + "</div></div>";
  }).join("");
  var bands = pn("BUDGET BANDS VS YOUR PRICES", "pricing_strategy.md", '<div class="auto" style="--min:200px">' + bandsHtml + "</div>");
  var segMax = (S.segments && S.segments[0]) ? S.segments[0][1] : 1;
  var side = pn("SYNC", "survey_pipeline.py",
      '<button class="btn main" type="button" data-act="sync"><span>SYNC NOW</span><small>zeroGravity .venv</small></button>' +
      '<p class="nt">Runs your pipeline with the business repo\'s own Python, so the Google libraries are there. Read-only Sheets scope.</p>') +
    pn("WHO ANSWERED", "SEGMENTS", bars(S.segments || [], total, segMax, [], ["agent", "business"]) +
      '<p class="nt">Estate agents = <b>' + ((S.segments || []).filter(function (s) { return /agent/i.test(s[0]); }).map(function (s) { return s[1]; })[0] || 0) + "</b>. Property is your primary market and has the least evidence behind it.</p>") +
    pn("BUYING FACTORS", "MULTI-SELECT", (S.buying_factors || []).map(function (f) { return kv(f[0], pct(f[1], total)); }).join("")) +
    pn("SHADOW SIGNALS", '"OTHER" ANSWERS', "<div>" + (S.other_answers || []).map(function (o) { return '<span class="chip">' + esc(o[0]) + "</span>"; }).join("") + '</div><p class="nt">Logged for P3. No names in the survey, so it never feeds LEADS.</p>', true);
  html += '<div class="cols"><div class="wide">' + svc + bands + '</div><div class="side">' + side + "</div></div>";
  return '<div class="g">' + html + "</div>";
}
function openIntel(id) {
  var comps = DATA.research && DATA.research.competitors ? DATA.research.competitors.competitors : [];
  var c = comps.filter(function (x) { return x.id === id; })[0];
  if (!c) return;
  var vs = '<div class="cmp"><span class="lb">COMPARE</span><span class="lb">THEM</span><span class="lb">ZEROGRAVITY</span></div>' +
    (c.vs || []).map(function (v) { return '<div class="cmp"><span>' + esc(v[0]) + "</span><b>" + esc(v[1]) + '</b><b class="' + esc(v[3] || "") + '">' + esc(v[2]) + "</b></div>"; }).join("");
  $("modal").innerHTML = '<div class="ovl"><button class="ovlbg" type="button" aria-label="Close intel panel" data-act="close"></button>' +
    '<div class="modal" role="dialog" aria-label="Competitor intel"><div class="bh" style="padding:8px 14px"><span>INTEL · ' + esc(c.name) + "</span><em>" + esc(c.tier) + "</em></div>" +
    '<div class="fr"><div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><h2>' + esc(c.name) + '</h2><button class="btn" type="button" data-act="close" style="width:auto"><span>CLOSE</span><small>×</small></button></div>' +
    '<div class="cols"><div style="flex:1 1 280px;display:grid;gap:8px">' + kv("Base", c.base) + kv("Sells", c.sells) + kv("Prices", c.price) + kv("Threat to you", c.threat, "color:#ffcf5c") +
    row("Strength", "", c.strength, "PLUS", "") + row("Weakness", "", c.weakness, "MINUS", "") + row("Your opening", "", c.opening, "GO", "done") + "</div>" +
    '<div style="flex:1 1 320px;display:grid;gap:6px">' + vs +
    '<p class="nt">Their column comes from operations/office/competitors.json' + (c.file ? " and docs/02_market_research/competitors/" + esc(c.file) : "") + ". Yours is your own pricing and READY data.</p></div></div></div></div></div>";
  var btn = document.querySelector('.modal [data-act="close"].btn'); if (btn) btn.focus();
}

/* ---------- LEADS ---------- */
function viewLeads() {
  var L = DATA.leads;
  if (!L) return errBox("LEADS failed: " + DATA.leads_error);
  var edited = findItem("footage_edited");
  var html = "";
  if (edited && !edited.passed) setBanner('<div class="banner warn"><span class="tg wip">BLOCKER</span><span class="t">Nothing to send a lead yet. The showreel waits on an exported cut (READY · Footage edited).</span></div>');
  var empties = { contacted: "Log your first lead below", replied: "Empty", quoted: "First quote here unlocks Phase 2", booked: "Empty", lost: "Log why. It's useful data." };
  var cols = L.statuses.map(function (s) {
    var items = L.leads.filter(function (l) { return l.status === s; });
    var body = items.map(function (l) {
      var opts = L.statuses.map(function (o) { return "<option" + (o === s ? " selected" : "") + ">" + o + "</option>"; }).join("");
      return '<div class="card"><b>' + esc(l.name) + "</b><small>" + esc(l.type) + (l.area ? " · " + esc(l.area) : "") + "</small><small>Next: " + esc(l.next_action || "[set one]") + (l.next_date ? " · " + esc(l.next_date) : "") +
        '</small><label class="lb">MOVE <select data-act="leadstatus" data-v="' + esc(l.id) + '">' + opts + "</select></label></div>";
    }).join("") || '<div class="empty">' + empties[s] + "</div>";
    return pn(s.toUpperCase(), String(items.length), body);
  }).join("");
  html += '<div class="auto" style="--min:200px">' + cols + "</div>";
  var form = '<form id="leadForm" class="g" style="gap:10px"><div class="two">' +
    '<label class="fl">NAME<input name="name" type="text" required maxlength="120" placeholder="Business or person"></label>' +
    '<label class="fl">TYPE<select name="type"><option>Real estate</option><option>Events</option><option>Social media content</option><option>Construction / inspection</option><option>Other</option></select></label>' +
    '<label class="fl">SOURCE<select name="source"><option>Walk-in</option><option>Email</option><option>LinkedIn</option><option>Referral</option><option>Website</option></select></label>' +
    '<label class="fl">AREA<select name="area"><option>Bromley &amp; SE London</option><option>Kent</option><option>London-wide</option><option>Essex</option></select></label>' +
    '<label class="fl">NEXT ACTION<input name="next_action" type="text" maxlength="200" placeholder="e.g. send showreel link"></label>' +
    '<label class="fl">NEXT ACTION DATE<input name="next_date" type="date"></label></div>' +
    '<button class="btn main" type="submit"><span>LOG LEAD</span><small>status: contacted</small></button>' +
    '<p class="nt">Logging pays nothing. <b>+10 Company XP</b> when a sent email to this lead is found (build 2 watcher).</p></form>';
  var markets = row("Real estate · PRIMARY", "Your chosen entry · survey 9.4%, 1 agent", "", "UNVALIDATED", "conf") +
    row("Events", "Venues, weddings, parties · 46.9%", "", "VALIDATED", "done") +
    row("Social media content", "Creators, small brands · 43.8%", "", "VALIDATED", "done") +
    row("Construction / inspection", "Builders, roofers, site progress · 31.3%", "", "SIGNAL", "wip") +
    row("Validate property", "CHECK · 5 agent conversations logged with replies",
      L.leads.filter(function (l) { return l.type === "Real estate" && l.status !== "contacted"; }).length + " of 5", "QUEST", "todo");
  html += '<div class="auto" style="--min:320px">' + pn("ADD LEAD", "0 XP TO LOG", form) + pn("TARGET MARKETS", "YOUR CALL VS YOUR DATA", markets) + "</div>";
  return '<div class="g">' + html + "</div>";
}

/* ---------- PLAN ---------- */
function viewPlan() {
  var P = DATA.plan;
  if (!P) return errBox("PLAN failed: " + DATA.plan_error);
  setBanner('<div class="banner warn"><span class="tg conf">PROGRAMME PAUSED</span><span class="t">King\'s Trust reapply: Feb 2027. Judge: ' + esc(P.judge_source || "none") + " run " + esc(P.judge_run_at || "") + ". Placeholder counts are live from the plan file.</span></div>");
  var pass17 = P.sections.filter(function (s) { return s.number <= 7 && s.verdict === "PASS" && s.placeholders === 0; }).length;
  var tagFor = function (s) { return s.verdict === "PASS" ? "done" : s.verdict === "FAIL" ? "bad" : "wip"; };
  var list = P.sections.map(function (s) {
    return '<button type="button" class="btn' + (UI.sec === s.number ? " sel" : "") + '" data-act="sec" data-v="' + s.number + '"><span style="display:grid;gap:2px"><span>' + esc(s.title) +
      '</span><small style="color:#8eaa9b">' + s.placeholders + " placeholder(s) · judge " + s.met + "/" + s.total + '</small></span><span class="tg ' + tagFor(s) + '">' + esc(s.verdict) + "</span></button>";
  }).join("");
  var sel = P.sections.filter(function (s) { return s.number === UI.sec; })[0] || P.sections[0];
  var report = sel.items.map(function (i) {
    return '<div class="row"><b>' + esc(i.c) + '</b><small class="ev">' + esc(i.note) + '</small><span class="r tg ' + (i.met ? "done" : "bad") + '">' + (i.met ? "MET" : "NOT MET") + "</span></div>";
  }).join("") || '<div class="empty">Not judged yet</div>';
  report += kv("Live placeholders in this section", String(sel.placeholders), sel.placeholders ? "color:#ffcf5c" : "");
  var cross = P.cross_checks.map(function (c) { return row(c[0], "", c[2], c[1], c[1] === "FAIL" ? "bad" : "wip"); }).join("");
  var how = kv("Trigger", "plan file changes") + kv("Sends", "section text + rubric to Claude") + kv("Returns", "met / not met per criterion") + kv("Catches", "placeholders, filler, bad maths") +
    '<p class="nt">Typing three letters into a heading doesn\'t pass a rubric. What it <b>can\'t</b> judge is truth. That goes to mentor sign-off. Automatic judging switches on in build 2.</p>';
  return '<div class="cols"><div class="side" style="max-width:460px">' + pn("SECTIONS · AI JUDGE", pass17 + " / 7 PASS", list) + "</div>" +
    '<div class="wide">' + pn("JUDGE REPORT · " + sel.title, sel.met + " / " + sel.total, report) +
    '<div class="auto">' + pn("HOW THE JUDGE WORKS", "TIER 2", how) + pn("CROSS-CHECKS", "NUMBERS DON'T AGREE", cross, true) + "</div></div></div>";
}

/* ---------- CONTENT ---------- */
function mb(b) { return b > 1e9 ? (b / 1e9).toFixed(1) + " GB" : Math.round(b / 1e6) + " MB"; }
function viewContent() {
  var C = DATA.content;
  if (!C) return errBox("CONTENT failed: " + DATA.content_error);
  if (!C.exists) return errBox("Footage folder not found: " + C.root + ". Set ZEROGRAVITY_MEDIA_ROOT if it lives elsewhere.");
  var hot = { VERIFY: 1, EXPORT: 1 };
  var stages = '<div class="auto" style="--min:100px;gap:6px">' + C.stages.map(function (s) {
    return '<div class="stage' + (hot[s[0]] && s[1] === 0 ? " hot" : "") + '"><span class="lb">' + s[0] + "</span><b>" + s[1] + '</b><span class="nt">' + esc(s[2]) + '</span><span class="tg' + (s[3] === "YOU" || s[3] === "PREMIERE" ? " wip" : "") + '">' + s[3] + "</span></div>";
  }).join("") + "</div>";
  var label = { none: "UNTAGGED", hero: "HERO", broll: "B-ROLL", rej: "REJECT" };
  var tagged = C.clips.filter(function (c) { return c.tag !== "none"; }).length;
  var clips = C.clips.map(function (c, i) {
    return '<div class="clip"><div class="thumb" aria-hidden="true">' + String(i + 1).padStart(2, "0") + '</div><div style="display:grid;gap:2px;min-width:0"><b>' + esc(c.name) + "</b><small>trim · " + mb(c.bytes) +
      '</small></div><button type="button" class="ctag' + (c.tag !== "none" ? " " + c.tag : "") + '" data-act="tag" data-v="' + esc(c.key) + '" data-t="' + c.tag + '">' + label[c.tag] + "</button></div>";
  }).join("") || '<div class="empty">No trims found in any project\'s edits/ folder</div>';
  var sel = C.projects.filter(function (p) { return p.name === C.select_project; })[0];
  var left = pn("SELECT · " + (C.select_project || "NO PROJECT"), tagged + " / " + C.clips.length + " TAGGED · " + C.heroes + " HERO",
      clips + '<p class="nt">Tap a tag to cycle HERO, B-ROLL, REJECT. Tags save to operations/office/content_tags.json. This is the one stage where clicking is the real work.</p>') +
    pn("BATCH · SHOWREEL V1", "CLEARS 2 READY ITEMS",
      kv("Heroes picked", C.heroes + " clips") + kv("Target", "60 to 90s · 16:9 4K + 9:16 cut") + kv("When exported", "Footage edited clears · Portfolio 1 of 3", "color:#70ffb4") +
      '<button class="btn main" type="button" data-act="premiere" data-v="' + esc(C.select_project || "") + '"' + (sel && sel.prproj.length ? "" : " disabled") + '><span>OPEN IN PREMIERE</span><small>' + (sel && sel.prproj.length ? ".prproj" : "no project file") + "</small></button>", true) +
    pn("PROJECTS · FOLDER SCAN", "zeroGravity-media/projects", C.projects.map(function (p) {
      var stage = p.exports.length ? "EXPORTED" : p.trims.length ? "TRIMMED" : p.misplaced_cuts.length ? "CHECK" : p.raw ? "RAW" : p.empty ? "EMPTY" : "RAW";
      var cls = { EXPORTED: "done", TRIMMED: "wip", CHECK: "conf", RAW: "todo", EMPTY: "todo" }[stage];
      return row(p.name, "raw " + p.raw + " · trims " + p.trims.length + " · exports " + p.exports.length + (p.prproj.length ? " · .prproj" : ""),
        (p.manifest_id ? p.manifest_id + " · permission " + p.portfolio_permission : "no manifest"), stage, cls);
    }).join(""));
  var right = pn("HOW A CLIP MOVES", "FOLDERS = STAGES",
      kv("raw/", "untouched card dumps") + kv("edits/", "trims + project file") + kv("exports/", "finished cut, 30s+ (ffprobe)") + kv("published", "found on your live site") +
      '<p class="nt">You never press "next stage". Saving a file in the right folder is the action, and the watcher reads it.' + (C.ffprobe ? "" : " <b>ffprobe isn't installed</b>, so export lengths can't be checked yet.") + "</p>") +
    pn("INGEST", "BUILD 2", '<p class="nt">Card in, files copied to a new project\'s raw/, renamed by date, checksummed, manifest created, flight log linked. Proxies for Premiere. Coming next build.</p>') +
    pn("NEEDS YOU", String(C.needs.length), C.needs.map(function (n) { return row(n.title, n.sub, n.ev, n.tag, n.cls); }).join("") || '<div class="empty">Nothing waiting on you</div>', true);
  return '<div class="g">' + pn("MEDIA LIFECYCLE", "FROM YOUR ARCHITECTURE_V2", stages) + '<div class="cols"><div class="wide">' + left + '</div><div class="side">' + right + "</div></div></div>";
}

/* ---------- locked hubs ---------- */
function lockBanner(phase, title, text) {
  setBanner(phase
    ? '<div class="banner phase-lock"><b>' + esc(title) + '</b><span class="t">' + esc(text) + '</span><span class="tg conf push">EARNED BY TRADING</span></div>'
    : '<div class="banner build-lock"><b>NOT BUILT YET · NEXT BUILD</b><span class="t">' + esc(text) + '</span><span class="tg push">SOFTWARE, NOT A GAME LOCK</span></div>');
}
function viewMoney() {
  lockBanner(false, "", "Costs, quotes and receipts that feed the plan figures.");
  return '<div class="auto dim" style="--min:320px">' + pn("STARTUP COSTS", "FEEDS PLAN §1.3 + §8",
      kv("Operator ID", "about £12 / year") + kv("Commercial insurance", "[quote needed]", "color:#ffcf5c") + kv("A2 CofC course", "[£]") + kv("Domain + hosting", "[£ / year]") + kv("TOTAL TO LAUNCH", "[£]")) +
    pn("WHAT YOU'LL DO HERE", "DATA, NOT REWARDS", row("Enter costs and quotes", "Typing a number is fine: it's data, it pays no XP", "", "YOU", "") +
      row("Snap receipts", "From the phone, attached to the cost line", "", "YOU", "") + row("Plan figures fill in", "Totals flow into the King's Trust figures", "", "AUTO", "")) + "</div>";
}
function viewJobs() {
  lockBanner(true, "PHASE 2 · TEST TRADING", "Unlocks when your first quote is sent.");
  return '<div class="auto dim" style="--min:340px">' + pn("JOB RECORD", "[CLIENT] · [DATE]", kv("Service", "Property photo + video") + kv("Quote", "£250 (from pricing)") +
      kv("Flight log", "linked →", "color:#70ffb4") + kv("Footage batch", "linked →", "color:#70ffb4") + kv("Paid", "[verified from bank / accounts]")) +
    pn("WHAT YOU'LL DO HERE", "P2", row("Turn a quote into a job", "One click from LEADS once it's accepted", "", "YOU", "") + row("Profit per job", "Fee minus travel, kit wear, hours", "", "AUTO", "")) + "</div>";
}
function viewSite() {
  lockBanner(true, "PHASE 2 · TEST TRADING", "Unlocks when your first quote is sent.");
  return '<div class="auto dim" style="--min:340px">' + pn("PRE-FLIGHT SITE PACK", "PER JOB", row("Airspace check", "FRZ, NOTAMs, link to the map", "", "YOU", "todo") +
    row("Weather + wind", "Fetched for the postcode and time", "", "AUTO", "todo") + row("Risk assessment", "Template, signed on the phone", "", "YOU", "todo") +
    row("Insurance in date", "Pulled from READY", "", "AUTO", "todo") + '<p class="nt">Ticks here are a <b>safety record</b>, not a reward. They earn nothing, so there\'s no reason to fake them.</p>') + "</div>";
}
function viewServ() {
  lockBanner(true, "PHASE 3 · SCALE", "Unlocks after [N] jobs delivered.");
  return '<div class="g">' + pn("CINEMATIC · YOUR ENTRY", "PHASE 1 · ACTIVE NOW", '<div><span class="chip">Property (primary)</span><span class="chip">Events</span><span class="chip">Social media content</span><span class="chip">FPV cinematic</span></div>') +
    '<div class="auto dim" style="--min:240px">' +
    pn("DATA COLLECTION", "P3 · YEAR 2", '<p class="nt"><b>Shadow, SLAM + LiDAR.</b> Indoor and outdoor. Construction signal (31%) points here.</p>') +
    pn("AGRICULTURE", "P3", '<p class="nt"><b>Computer vision heavy.</b> Crop and field monitoring.</p>') +
    pn("DELIVERY", "P3", '<p class="nt"><b>With your dad.</b> CV-guided, Shadow\'s claw for payloads.</p>') +
    pn("CUSTOM BUILDS", "P3", '<p class="nt"><b>After CAD levels up.</b> Bespoke FPV and cinewhoop builds.</p>') + "</div></div>";
}

/* ---------- actions ---------- */
function load(msg) {
  return fetch("/business/data").then(function (r) { return r.json(); }).then(function (d) {
    DATA = d; render(); if (msg) toast(msg);
  }).catch(function (e) { $("page").innerHTML = errBox("Couldn't load /business/data: " + e); });
}
var NEXT_TAG = { none: "hero", hero: "broll", broll: "rej", rej: "none" };

document.addEventListener("click", function (ev) {
  var el = ev.target.closest("[data-act]");
  if (!el || el.tagName === "SELECT") return;
  var act = el.getAttribute("data-act"), v = el.getAttribute("data-v");
  if (act === "checks") { el.disabled = true; load("Checks re-run"); }
  else if (act === "sync") {
    el.disabled = true; toast("Syncing survey...");
    post("/business/survey/sync").then(function (r) { load(r.ok ? "Survey synced · " + (r.message || "") : "Sync failed: " + (r.message || "")); });
  }
  else if (act === "tier") { UI.tier = v; render(); }
  else if (act === "comp") { openIntel(v); }
  else if (act === "close") { $("modal").innerHTML = ""; }
  else if (act === "sec") { UI.sec = Number(v); render(); }
  else if (act === "tag") {
    var nxt = NEXT_TAG[el.getAttribute("data-t")] || "hero";
    post("/business/content/tag", { key: v, tag: nxt }).then(function (r) { if (r.ok) load(); else toast(r.message || "Couldn't save tag"); });
  }
  else if (act === "premiere") {
    post("/business/content/open", { project: v }).then(function (r) { toast(r.message || (r.ok ? "Opening Premiere" : "Couldn't open")); });
  }
});
document.addEventListener("change", function (ev) {
  var el = ev.target;
  if (el.getAttribute && el.getAttribute("data-act") === "leadstatus") {
    post("/business/leads/" + encodeURIComponent(el.getAttribute("data-v")) + "/status", { status: el.value })
      .then(function (r) { load(r.ok ? "Lead moved to " + el.value : (r.message || "Couldn't move lead")); });
  }
});
document.addEventListener("submit", function (ev) {
  if (ev.target.id !== "leadForm") return;
  ev.preventDefault();
  var f = new FormData(ev.target), body = {};
  f.forEach(function (val, key) { body[key] = val; });
  post("/business/leads", body).then(function (r) { load(r.ok ? "Lead logged · 0 XP until contact is verified" : (r.message || "Couldn't log lead")); });
});
document.addEventListener("keydown", function (ev) {
  if (ev.key === "Escape" && $("modal").innerHTML) $("modal").innerHTML = "";
});
window.addEventListener("hashchange", render);

drawRing(route());
load();
})();
