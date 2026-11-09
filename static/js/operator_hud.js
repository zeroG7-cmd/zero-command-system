/* Operator Development HUD - live shell.
 *
 * Visual design ported from the approved sci-fi HUD mockup (see project
 * docs: "Operator Workspace HUD Mockup: Handoff"). Unlike that mockup, this
 * reads real data every load from GET /operator/hud/data (one fetch,
 * assembled server-side by modules/operator_hud.py out of each hub's own
 * real getter - never a second, hand-maintained copy of the data), and the
 * actions that save (Execution, Flights, Challenges logging) really save,
 * via the same POST endpoints each hub's own existing page already used.
 *
 * Every hub's primary actions now live inside this shell - nothing routes
 * out to a separately-styled standalone page. Journal's "new entry" is a
 * real <form> POST to /operator/journal/create (same as Tasks/Fitness
 * below); Learning's "Continue" opens a real in-hub notebook editor
 * (notes/reflection/evidence, save, mark-complete) against the same
 * /operator/learning/tracks/<id>/* endpoints the old notebook drawer used,
 * plus the Import Course/Reconcile Boot.dev/Progress Import admin forms.
 * Tasks and Fitness logging use real <form> submits (their backends expect
 * form-encoded POSTs + a redirect, not JSON); Journal and Learning's admin
 * forms now redirect the same way (see each module's _back() helper), which
 * is why they all land back in this shell afterward with a status in the URL.
 */
(function () {
"use strict";

var $ = function (id) { return document.getElementById(id); };
var fmt = function (n) { return Number(n || 0).toLocaleString("en-GB"); };
var esc = function (s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  });
};
var root = $("root"), page = $("page"), mv = $("mv");
var DATA = null;
var DAY = null;

var NAV = [
  ["overview", "HOME", "Overview"], ["learning", "LEARN", "Learning"],
  ["execution", "EXEC", "Execution"], ["flights", "FLIGHT", "Flights"],
  ["tasks", "TASKS", "Tasks"], ["fitness", "FIT", "Fitness"],
  ["journal", "JOURNAL", "Journal"], ["analytics", "STATS", "Analytics"],
  ["achievements", "ACHV", "Achievements"], ["challenges", "CHAL", "Challenges"]
];
var CRUMB = {
  overview: "OVERVIEW", learning: "LEARNING", execution: "EXECUTION", flights: "FLIGHTS",
  tasks: "TASKS", fitness: "FITNESS", journal: "JOURNAL", analytics: "ANALYTICS",
  achievements: "ACHIEVEMENTS", challenges: "CHALLENGES", tree: "SKILL TREE", skill: "LEARNING"
};
var ORDER = ["CON", "INT", "STR", "DEX", "DISC", "WILL", "SPIRIT"];

var toastT;
function toast(m) {
  var t = $("toast"); t.textContent = m; t.classList.add("on");
  clearTimeout(toastT); toastT = setTimeout(function () { t.classList.remove("on"); }, 2600);
}

function titleFor(level) {
  return level >= 20 ? "Systems Architect" : level >= 10 ? "R&D Operator" : level >= 5 ? "Developing Operator" : "Initiate";
}

/* ---------- shared markup helpers (match operator_hud.css class names) ---------- */
function pn(title, right, body, cls) {
  return '<section class="pn ' + (cls || "") + '"><div class="bar-head"><span>' + esc(title) + '</span><span>' + (right || "") + '</span></div><div class="frame">' + body + '</div></section>';
}
function mini(p, l) {
  return '<div class="mini" style="--p:' + (p || 0) + '"><b' + (String(l).length > 3 ? ' style="font-size:10px"' : "") + '>' + esc(l) + '</b></div>';
}
function pb(p, warm) {
  return '<div class="pb' + (warm ? " warm" : "") + '"><i style="width:' + Math.max(0, Math.min(100, p || 0)) + '%"></i></div>';
}
function rowLeaf(l) {
  return '<div class="row dim">' + mini(l.progress_percentage, l.level) + "<b>" + esc(l.name) + "</b><small>" + fmt(l.xp) + " XP</small><span class=\"r\">" + (l.xp ? Math.round(l.progress_percentage || 0) + "%" : "-") + "</span></div>";
}
function setPage(cls, html) { page.className = "page " + (cls || ""); page.innerHTML = html; }
function empty(msg) { return '<div class="empty">' + esc(msg) + "</div>"; }

/* ---------- core rating ring (SVG) - ported near-verbatim from the approved mockup ---------- */
function polar(r, deg) { var a = deg * Math.PI / 180; return [60 + r * Math.cos(a), 60 + r * Math.sin(a)]; }
function arc(r, a0, a1) {
  var p0 = polar(r, a0), p1 = polar(r, a1);
  return "M" + p0[0].toFixed(2) + " " + p0[1].toFixed(2) + "A" + r + " " + r + " 0 " + ((a1 - a0) > 180 ? 1 : 0) + " 1 " + p1[0].toFixed(2) + " " + p1[1].toFixed(2);
}
function statMap() {
  var ov = (DATA && DATA.overview) || {};
  var byName = {};
  (ov.main_stats || []).forEach(function (s) { byName[s.name] = s; });
  return byName;
}
function bestStat() {
  var m = statMap(), best = ORDER[0], bv = -1;
  ORDER.forEach(function (k) { var v = (m[k] && m[k].average_level) || 0; if (v > bv) { bv = v; best = k; } });
  return best;
}
function coreSvg(size) {
  var ov = (DATA && DATA.overview) || {};
  var m = statMap(), best = bestStat();
  var seg = 360 / 7, s = "";
  ORDER.forEach(function (k, i) {
    var avg = (m[k] && m[k].average_level) || 0;
    var a0 = -90 + i * seg + 3, a1 = a0 + seg - 6;
    var f = avg - Math.floor(avg), near = f >= 0.85;
    s += '<path d="' + arc(46, a0, a1) + '" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="7"/>';
    if (f > 0) s += '<path class="' + (near ? "near" : "") + '" d="' + arc(46, a0, a0 + (a1 - a0) * Math.max(f, 0.06)) + '" fill="none" stroke="' + (k === best ? "#ffcf5c" : "#70ffb4") + '" stroke-width="7"/>';
  });
  var hex = [0, 1, 2, 3, 4, 5].map(function (i) { var p = polar(31, -90 + i * 60); return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ");
  var small = size < 80;
  var overall = (ov.overall || 0).toFixed(2);
  return '<svg class="core" viewBox="-6 -6 132 132" width="' + size + '" height="' + size + '" role="img" aria-label="Overall rating ' + overall + '. Open analytics." data-go="analytics">'
    + '<g class="spin"><circle cx="60" cy="60" r="57" fill="none" stroke="rgba(112,255,180,.5)" stroke-width="1.5" stroke-dasharray="1 5.5"/></g>'
    + '<circle cx="60" cy="60" r="38" fill="rgba(8,16,13,.85)"/>' + s
    + '<polygon class="hex" points="' + hex + '" fill="rgba(112,255,180,.06)" stroke="rgba(112,255,180,.55)" stroke-width="1.5"/>'
    + '<text class="num" x="60" y="' + (small ? 69 : 65) + '" text-anchor="middle" style="font-size:' + (small ? "30px" : "25px") + '">' + overall + "</text>"
    + (small ? "" : '<text class="lab" x="60" y="79" text-anchor="middle">OVERALL</text>') + "</svg>";
}

document.addEventListener("click", function (e) {
  var c = e.target.closest && e.target.closest("[data-go]");
  if (c) location.hash = c.getAttribute("data-go");
});

/* ---------- chrome: nav ring, brand, level badge, crumb ---------- */
function renderChrome(view) {
  var ov = (DATA && DATA.overview) || {};
  $("ring").innerHTML = NAV.map(function (n) {
    return '<a class="hub' + (n[0] === view ? " on" : "") + '" href="#' + n[0] + '" aria-label="' + esc(n[2]) + '">' + n[1] + "</a>";
  }).join("");
  $("minicore").innerHTML = coreSvg(48);
  $("minisub").textContent = titleFor(ov.operator_level || 0);
  $("badgelv").textContent = ov.operator_level || 0;
  $("badgetitle").textContent = titleFor(ov.operator_level || 0).toUpperCase();
  $("crumb").innerHTML = "<a class=\"crumb-home\" href=\"/\">ZERO COMMAND</a> <b>/ " + (CRUMB[view] || view.toUpperCase()) + "</b>";
}

/* ---------- overview ---------- */
var detOpen = null;
function closeDet() {
  $("detail").classList.remove("open"); detOpen = null;
  [].forEach.call(document.querySelectorAll(".skill,.a"), function (b) { b.classList.remove("sel"); });
}
function treeLeafTops(stat, limit) {
  var node = ((DATA.overview || {}).tree || {})[stat];
  var out = [];
  (function walk(n, path) {
    if (!n || typeof n !== "object") return;
    var kids = n.children || {};
    var hasKids = Object.keys(kids).length > 0;
    if (!hasKids && (n.xp || n.level)) {
      out.push({ name: path[path.length - 1] || stat, xp: n.xp || 0, level: n.level || 0, progress: n.level_progress || 0 });
    }
    Object.keys(kids).forEach(function (name) { walk(kids[name], path.concat(name)); });
  })(node, [stat]);
  out.sort(function (a, b) { return b.xp - a.xp; });
  return out.slice(0, limit || 5);
}
function treeCategories(stat) {
  var node = ((DATA.overview || {}).tree || {})[stat] || {};
  var kids = node.children || {};
  return Object.keys(kids).map(function (name) {
    var c = kids[name] || {};
    return { name: name, avg: c.average_level || 0, xp: sumXp(c) };
  }).sort(function (a, b) { return b.xp - a.xp; });
}
function sumXp(node) {
  if (!node || typeof node !== "object") return 0;
  var kids = node.children;
  if (!kids || !Object.keys(kids).length) return node.xp || 0;
  var total = 0;
  Object.keys(kids).forEach(function (k) { total += sumXp(kids[k]); });
  return total;
}
function openStat(k) {
  detOpen = { type: "stat", k: k };
  [].forEach.call(document.querySelectorAll(".skill"), function (b) { b.classList.remove("sel"); });
  [].forEach.call(document.querySelectorAll(".a"), function (b) { b.classList.toggle("sel", b.dataset.stat === k); });
  var m = statMap()[k] || { average_level: 0, child_count: 0, xp: 0 };
  var avg = m.average_level || 0, fr = avg - Math.floor(avg);
  var cats = treeCategories(k);
  var tops = treeLeafTops(k, 5);
  var det = $("detail");
  det.innerHTML = '<header><div><h2>' + k + '</h2><div class="path">ATTRIBUTE</div></div><button class="x" id="cx" type="button" aria-label="Close">x</button></header>'
    + '<div><div class="dl"><span>OVR <b>' + avg.toFixed(2) + '</b></span></div><div class="pb" style="margin:6px 0"><i style="width:' + Math.round(fr * 100) + '%"></i></div><div class="dl"><span>progress to ' + (Math.floor(avg) + 1) + '.00</span><span>' + Math.round(fr * 100) + '%</span></div></div>'
    + '<div class="dl"><span>CATEGORIES</span><span>' + cats.length + '</span></div>'
    + '<div class="clist" style="flex:none;max-height:34%">' + cats.map(function (c) {
        return '<div class="c' + (c.xp ? "" : " zero") + '"><span>' + esc(c.name) + '</span><em>' + c.avg.toFixed(2) + ' / ' + fmt(c.xp) + ' XP</em><div class="pb"><i style="width:' + Math.round((c.avg - Math.floor(c.avg)) * 100) + '%"></i></div></div>';
      }).join("") + '</div>'
    + '<div class="dl"><span>TOP SKILLS</span><span>' + tops.length + '</span></div>'
    + '<div class="clist">' + (tops.length ? tops.map(function (x) {
        return '<div class="c"><span>' + esc(x.name) + '</span><em>L' + x.level + ' / ' + fmt(x.xp) + ' XP</em><div class="pb"><i style="width:' + Math.round(x.progress) + '%"></i></div></div>';
      }).join("") : "<p>No XP in this attribute yet.</p>") + '</div>'
    + '<a class="btn main" href="#tree/' + k + '"><span>OPEN IN SKILL TREE</span><small>full page</small></a>';
  det.classList.add("open"); $("cx").onclick = closeDet;
}
function openSkill(cap) {
  detOpen = { type: "skill", slug: cap.slug };
  [].forEach.call(document.querySelectorAll(".a"), function (b) { b.classList.remove("sel"); });
  [].forEach.call(document.querySelectorAll(".skill"), function (b) { b.classList.toggle("sel", b.dataset.slug === cap.slug); });
  var slugs = (DATA.overview || {}).capability_slugs || {};
  var capId = Object.keys(slugs).filter(function (id) { return slugs[id] === cap.slug; })[0];
  var concepts = ((DATA.overview || {}).concepts_by_capability || {})[capId] || [];
  var sorted = concepts.slice().sort(function (a, b) { return b.xp - a.xp; });
  var det = $("detail");
  det.innerHTML = '<header><div><h2>' + esc(cap.name.toUpperCase()) + '</h2><div class="path">LEVEL ' + cap.level + '</div></div><button class="x" id="cx" type="button" aria-label="Close">x</button></header>'
    + (cap.description ? "<p>" + esc(cap.description) + "</p>" : "")
    + '<div class="dl"><span>XP <b>' + fmt(cap.xp) + '</b></span><span>' + (cap.coverage || 0) + '% mapped</span></div>'
    + '<div class="pb" style="margin:6px 0"><i style="width:' + Math.round(cap.coverage || 0) + '%"></i></div>'
    + '<div class="dl"><span>CONCEPTS</span><span>' + sorted.length + '</span></div>'
    + '<div class="clist">' + (sorted.length ? sorted.map(function (c) {
        return '<div class="c' + (c.xp ? "" : " zero") + '"><span>' + esc(c.name) + '</span><em>L' + c.level + ' / ' + fmt(c.xp) + ' XP</em><div class="pb"><i style="width:' + (c.xp % 100) + '%"></i></div></div>';
      }).join("") : "<p>No concept map for this capability yet.</p>") + '</div>'
    + '<a class="btn main" href="#skill/' + encodeURIComponent(cap.slug) + '"><span>OPEN SKILL PAGE</span><small>full page</small></a>';
  det.classList.add("open"); $("cx").onclick = closeDet;
}
function renderOverview() {
  var ov = DATA.overview || {};
  if (ov.overview_error || !DATA.overview) {
    $("stats").innerHTML = empty((DATA.overview_error) || "Overview data unavailable.");
    $("skills").innerHTML = ""; $("trio").innerHTML = ""; $("ladder").innerHTML = "";
    $("lv").textContent = "-"; $("rtitle").textContent = ""; $("xp").innerHTML = ""; $("chip").textContent = "";
    $("bigcore").innerHTML = coreSvg(96);
    return;
  }
  var m = statMap(), best = bestStat();
  $("stats").innerHTML = ORDER.map(function (k) {
    var s = m[k] || { average_level: 0, xp: 0 };
    var frac = s.average_level - Math.floor(s.average_level), near = frac >= 0.85;
    return '<button type="button" class="a' + (k === best ? " top1" : "") + (near ? " near" : "") + '" data-stat="' + k + '" aria-label="' + k + ' summary"><span>' + k + "</span><b>" + s.average_level.toFixed(2) + "</b><i><u style=\"width:" + Math.round(frac * 100) + '%"></u></i><small>' + fmt(s.xp) + " XP</small></button>";
  }).join("");
  var skills = (ov.featured_capabilities || []).slice().sort(function (a, b) { return b.xp - a.xp; }).slice(0, 4);
  $("trio").innerHTML = "<span>" + fmt(ov.total_xp) + "<small>XP</small></span><span>" + fmt(ov.competency_count) + "<small>COMP</small></span><span>" + skills.length + "<small>ACTIVE</small></span>";
  $("chip").textContent = titleFor(ov.operator_level || 0);
  $("bigcore").innerHTML = coreSvg(96);
  $("skills").innerHTML = skills.map(function (s, i) {
    return '<button class="skill' + (s.coverage >= 85 ? " near" : "") + '" data-slug="' + esc(s.slug) + '" type="button" aria-label="' + esc(s.name) + ' level ' + s.level + '"><div class="ringp" style="--p:' + (s.coverage || 0) + '"><b>' + s.level + '</b></div><span>' + esc(s.name.toUpperCase()) + '</span></button>';
  }).join("") || empty("No active capabilities yet.");
  $("stats").onclick = function (e) {
    var b = e.target.closest(".a"); if (!b) return;
    (detOpen && detOpen.type === "stat" && detOpen.k === b.dataset.stat) ? closeDet() : openStat(b.dataset.stat);
  };
  $("skills").onclick = function (e) {
    var b = e.target.closest(".skill"); if (!b) return;
    var cap = skills.filter(function (s) { return s.slug === b.dataset.slug; })[0];
    if (!cap) return;
    (detOpen && detOpen.type === "skill" && detOpen.slug === cap.slug) ? closeDet() : openSkill(cap);
  };
  $("lv").textContent = ov.operator_level || 0;
  $("rtitle").textContent = titleFor(ov.operator_level || 0).toUpperCase();
  var into = Math.max(0, (ov.next_level_xp || 0) - (ov.xp_to_next_level || 0));
  $("xp").innerHTML = '<div class="rw"><span>XP</span><span>' + fmt(ov.total_xp) + ' total</span></div><div class="progress"><i style="width:' + (ov.level_progress || 0) + '%"></i></div><div class="rw"><span>' + fmt(ov.xp_to_next_level) + ' to level ' + ((ov.operator_level || 0) + 1) + '</span><span>' + Math.round(ov.level_progress || 0) + '%</span></div>';
  var ti = [["Initiate", "0-4", 0], ["Developing Operator", "5-9", 5], ["R&D Operator", "10+", 10], ["Systems Architect", "20+", 20]];
  $("ladder").innerHTML = ti.map(function (t, i) {
    var nx = ti[i + 1] ? ti[i + 1][2] : 1e9;
    return "<div" + ((ov.operator_level || 0) >= t[2] && (ov.operator_level || 0) < nx ? ' class="now"' : "") + "><span>" + t[0] + "</span><span>" + t[1] + "</span></div>";
  }).join("");
}

/* ---------- execution ---------- */
var execPick = null;
function execCatalogSelect() {
  var ex = DATA.execution || {};
  var statSel = $("ex-stat"), catSel = $("ex-cat"), subSel = $("ex-sub"), capSel = $("ex-cap");
  function stats() { return ex.catalog || []; }
  function cats(stat) { return stats().filter(function (c) { return c.stat === stat; }); }
  function fillStat() {
    var uniq = [].concat.apply([], stats().map(function (c) { return [c.stat]; })).filter(function (v, i, a) { return a.indexOf(v) === i; });
    statSel.innerHTML = uniq.map(function (s) { return '<option value="' + s + '">' + s + '</option>'; }).join("");
    fillCat();
  }
  function fillCat() {
    var opts = cats(statSel.value);
    catSel.innerHTML = opts.map(function (c) { return '<option value="' + esc(c.category) + '">' + esc(c.category) + '</option>'; }).join("");
    fillSub();
  }
  function fillSub() {
    var c = cats(statSel.value).filter(function (c) { return c.category === catSel.value; })[0];
    var subs = c ? Object.keys(c.subcategories) : [];
    subSel.innerHTML = subs.map(function (s) { return '<option value="' + esc(s) + '">' + esc(s) + '</option>'; }).join("");
    fillCap();
  }
  function fillCap() {
    var c = cats(statSel.value).filter(function (c) { return c.category === catSel.value; })[0];
    var caps = (c && c.subcategories[subSel.value]) || [];
    capSel.innerHTML = caps.map(function (cp) { return '<option value="' + esc(cp.name) + '">' + esc(cp.name) + " (L" + cp.level + ")</option>"; }).join("");
  }
  statSel.onchange = fillCat; catSel.onchange = fillSub; subSel.onchange = fillCap;
  fillStat();
  return { statSel: statSel, catSel: catSel, subSel: subSel, capSel: capSel };
}
function renderExecution() {
  var ex = DATA.execution;
  if (!ex) { setPage("g1", pn("EXECUTION", "", empty(DATA.execution_error || "Execution data unavailable."))); return; }
  var picks = [];
  var recordsHtml = (ex.records || []).slice(0, 12).map(function (r) {
    return '<div class="row dim"><span class="tag ' + (r.activity_type === "experiment" ? "sim" : "ok") + '" style="grid-row:1/3">' + esc((r.activity_type || "").toUpperCase()) + '</span><b>' + esc(r.title || "") + '</b><small>' + esc(r.scope || "") + ' / ' + fmt(r.xp_total || r.total_xp || 0) + ' XP</small></div>';
  }).join("") || empty("No execution records yet.");
  setPage("g21",
    pn("LOG PROJECT / EXPERIMENT", "", '<div class="two"><label class="f">TITLE<input id="ex-title" type="text" placeholder="What did you build?"></label><label class="f">TYPE<select id="ex-type"><option value="project">Project</option><option value="experiment">Experiment</option></select></label></div>'
      + '<div class="two"><label class="f">SCOPE<select id="ex-scope">' + Object.keys(ex.xp_by_scope || {}).map(function (s) { return '<option value="' + s + '">' + s.toUpperCase() + " (" + ex.xp_by_scope[s] + " XP)</option>"; }).join("") + '</select></label><div></div></div>'
      + '<div class="sec">CAPABILITY</div><div class="two"><label class="f">STAT<select id="ex-stat"></select></label><label class="f">CATEGORY<select id="ex-cat"></select></label></div>'
      + '<div class="two"><label class="f">SUBCATEGORY<select id="ex-sub"></select></label><label class="f">CAPABILITY<select id="ex-cap"></select></label></div>'
      + '<button type="button" class="btn main" id="ex-submit"><span>LOG COMPLETION</span></button>')
    + pn("RECENT", "", '<div class="btns">' + recordsHtml + '</div>')
  );
  var sel = execCatalogSelect();
  $("ex-submit").onclick = function () {
    var body = {
      title: $("ex-title").value, activity_type: $("ex-type").value, scope: $("ex-scope").value,
      capabilities: [{ stat: sel.statSel.value, category: sel.catSel.value, subcategory: sel.subSel.value, capability: sel.capSel.value }],
    };
    postJSON("/operator/execution/api", body, "execution");
  };
}

/* ---------- flights ---------- */
function renderFlights() {
  var fl = DATA.flights;
  if (!fl) { setPage("g1", pn("FLIGHTS", "", empty(DATA.flights_error || "Flight data unavailable."))); return; }
  var subs = Object.keys(fl.catalog || {});
  var records = (fl.records || []).slice(0, 10).map(function (r) {
    return '<div class="row dim"><span class="tag ' + (r.kind === "simulated" ? "sim" : "ok") + '" style="grid-row:1/3">' + esc((r.kind || "").toUpperCase()) + '</span><b>' + esc(r.aircraft || "") + '</b><small>' + (r.duration_minutes || 0) + ' min / ' + fmt(r.xp_total || 0) + ' XP</small></div>';
  }).join("") || empty("No flights logged yet.");
  var platformRows = ["real", "simulated"].reduce(function (acc, k) {
    return acc.concat((fl.platforms && fl.platforms[k]) || []);
  }, []).map(function (p) {
    var flown = p.flights ? p.flights + " flight" + (p.flights === 1 ? "" : "s") + " logged / " + fmt(p.xp) + " XP" : "not logged yet";
    var waiting = p.clips_waiting ? " · " + p.clips_waiting + " clip" + (p.clips_waiting === 1 ? "" : "s") + " waiting" : "";
    return '<div class="row dim"><span class="tag ' + (p.kind === "simulated" ? "sim" : "ok") + '" style="grid-row:1/3">' + esc((p.kind || "").toUpperCase()) + '</span><b>' + esc(p.name) + '</b><small>' + esc(flown) + waiting + '</small></div>';
  }).join("") || empty("No aircraft folders found under Flights/ yet.");
  setPage("g21",
    pn("LOG FLIGHT", "", '<div class="two"><label class="f">KIND<select id="fl-kind"><option value="real">Real</option><option value="simulated">Simulated</option></select></label><label class="f">AIRCRAFT<select id="fl-aircraft"></select></label></div>'
      + '<div class="two"><label class="f">DATE<input id="fl-date" type="date" value="' + esc(fl.today || "") + '"></label><label class="f">DURATION (min)<input id="fl-dur" type="number" min="1" step="1" value="10"></label></div>'
      + '<div class="sec">CAPABILITY (Aviation)</div><div class="two"><label class="f">SUBCATEGORY<select id="fl-sub"></select></label><label class="f">CAPABILITY<select id="fl-cap"></select></label></div>'
      + '<label class="f">EVIDENCE FILE (optional)<input id="fl-evidence" list="fl-evidence-list" placeholder="filename in raw/"><datalist id="fl-evidence-list"></datalist></label>'
      + '<button type="button" class="btn main" id="fl-submit"><span>LOG FLIGHT</span><small>' + (fl.hourly_xp_rate || 0) + ' XP/hr</small></button>')
    + pn("RECENT", "", '<div class="btns">' + records + '</div>')
    + pn("PLATFORMS", "", '<div class="btns">' + platformRows + '</div>')
  );
  var kindSel = $("fl-kind"), acSel = $("fl-aircraft"), subSel = $("fl-sub"), capSel = $("fl-cap");
  function fillAircraft() {
    var list = (fl.aircraft && fl.aircraft[kindSel.value]) || [];
    acSel.innerHTML = list.map(function (a) { return '<option value="' + esc(a) + '">' + esc(a) + '</option>'; }).join("");
    fillEvidence();
  }
  function fillSub() {
    subSel.innerHTML = subs.map(function (s) { return '<option value="' + esc(s) + '">' + esc(s) + '</option>'; }).join("");
    fillCap();
  }
  function fillCap() {
    var caps = (fl.catalog && fl.catalog[subSel.value]) || [];
    capSel.innerHTML = caps.map(function (c) { return '<option value="' + esc(c.name) + '">' + esc(c.name) + " (L" + c.level + ")</option>"; }).join("");
  }
  function fillEvidence() {
    var k = kindSel.value, a = acSel.value;
    if (!a) { $("fl-evidence-list").innerHTML = ""; return; }
    fetch("/operator/flights/evidence-files?kind=" + encodeURIComponent(k) + "&aircraft=" + encodeURIComponent(a))
      .then(function (r) { return r.json(); })
      .then(function (d) { $("fl-evidence-list").innerHTML = (d.files || []).map(function (f) { return '<option value="' + esc(f) + '">'; }).join(""); })
      .catch(function () {});
  }
  kindSel.onchange = fillAircraft; acSel.onchange = fillEvidence;
  fillAircraft(); fillSub();
  $("fl-submit").onclick = function () {
    var body = {
      kind: kindSel.value, aircraft: acSel.value, date: $("fl-date").value,
      duration_minutes: Number($("fl-dur").value || 0),
      capabilities: [{ subcategory: subSel.value, capability: capSel.value }],
      evidence_filename: $("fl-evidence").value || "",
    };
    postJSON("/operator/flights/api", body, "flights");
  };
}

/* ---------- challenges ---------- */
function goalRow(g, withCancel) {
  var pct = g.percentage != null ? g.percentage : (g.progress_xp != null && g.target_xp ? Math.round((g.progress_xp / g.target_xp) * 100) : null);
  return '<div class="row dim"><span class="tag ' + (g.status === "completed" ? "ok" : g.status === "expired" ? "bad" : "") + '" style="grid-row:1/3">' + esc((g.status || "").toUpperCase()) + '</span><b>' + esc(g.title || g.scope_label || "") + '</b><small>' + (g.scope_label ? esc(g.scope_label) + " / " : "") + fmt(g.target_xp) + ' XP target' + (pct != null ? " / " + pct + "%" : "") + '</small>'
    + (withCancel && g.status === "active" ? '<button type="button" class="x" data-cancel="' + esc(g.id) + '" style="grid-row:1/3;align-self:center">x</button>' : '<span class="r"></span>') + '</div>';
}
function renderChallenges() {
  var ch = DATA.challenges;
  if (!ch) { setPage("g1", pn("CHALLENGES", "", empty(DATA.challenges_error || "Challenges data unavailable."))); return; }
  var active = (ch.active_goals || []).map(function (g) { return goalRow(g, true); }).join("") || empty("No active challenges.");
  var done = (ch.completed_goals || []).map(function (g) { return goalRow(g, false); }).join("") || empty("No completed challenges yet.");
  var suggestions = (ch.suggestions || []).map(function (s) {
    return '<button type="button" class="row" data-sugg=\'' + esc(JSON.stringify(s)) + '\'><b>' + esc(s.title || s.scope_label || s.stat || "") + '</b><small>' + fmt(s.target_xp || 50) + ' XP suggested</small><span class="r">+</span></button>';
  }).join("") || empty("No suggestions right now.");
  var catalog = ch.catalog || [];
  setPage("g21",
    pn("ACTIVE", active.length ? String((ch.active_goals || []).length) : "", '<div class="btns">' + active + '</div>', "sp2")
    + pn("NEW CHALLENGE", "", '<div class="two"><label class="f">SCOPE<select id="ch-scopetype"><option value="stat">Whole stat</option><option value="category">Category</option><option value="competency">Specific capability</option></select></label><label class="f">DURATION<select id="ch-dur">' + (ch.durations || []).map(function (d) { return '<option value="' + d + '">' + d + ' days</option>'; }).join("") + '</select></label></div>'
      + '<div class="two"><label class="f">STAT<select id="ch-stat">' + (ch.main_stats || []).map(function (s) { return '<option value="' + s + '">' + s + '</option>'; }).join("") + '</select></label><label class="f" id="ch-cat-wrap" style="display:none">CATEGORY<select id="ch-cat"></select></label></div>'
      + '<div class="two" id="ch-cap-wrap" style="display:none"><label class="f">SUBCATEGORY<select id="ch-sub"></select></label><label class="f">CAPABILITY<select id="ch-cap"></select></label></div>'
      + '<div class="two"><label class="f">TITLE (optional)<input id="ch-title" type="text"></label><label class="f">TARGET XP<input id="ch-xp" type="number" min="10" max="5000" value="50"></label></div>'
      + '<button type="button" class="btn main" id="ch-submit"><span>CREATE CHALLENGE</span></button>')
    + pn("SUGGESTED", "", '<div class="btns">' + suggestions + '</div>')
    + pn("COMPLETED", "", '<div class="btns">' + done + '</div>')
  );
  var scopeSel = $("ch-scopetype"), statSel = $("ch-stat"), catSel = $("ch-cat"), subSel = $("ch-sub"), capSel = $("ch-cap");
  var catWrap = $("ch-cat-wrap"), capWrap = $("ch-cap-wrap");
  function catsFor(stat) { return catalog.filter(function (c) { return c.stat === stat; }); }
  function fillCat() {
    catSel.innerHTML = catsFor(statSel.value).map(function (c) { return '<option value="' + esc(c.category) + '">' + esc(c.category) + '</option>'; }).join("");
    fillSub();
  }
  function fillSub() {
    var c = catsFor(statSel.value).filter(function (c) { return c.category === catSel.value; })[0];
    var subs = c ? Object.keys(c.subcategories) : [];
    subSel.innerHTML = subs.map(function (s) { return '<option value="' + esc(s) + '">' + esc(s) + '</option>'; }).join("");
    fillCap();
  }
  function fillCap() {
    var c = catsFor(statSel.value).filter(function (c) { return c.category === catSel.value; })[0];
    var caps = (c && c.subcategories[subSel.value]) || [];
    capSel.innerHTML = caps.map(function (name) { return '<option value="' + esc(name) + '">' + esc(name) + '</option>'; }).join("");
  }
  function updateVisibility() {
    var t = scopeSel.value;
    catWrap.style.display = (t === "category" || t === "competency") ? "" : "none";
    capWrap.style.display = (t === "competency") ? "" : "none";
  }
  scopeSel.onchange = updateVisibility;
  statSel.onchange = fillCat; catSel.onchange = fillSub; subSel.onchange = fillCap;
  fillCat(); updateVisibility();
  $("ch-submit").onclick = function () {
    var t = scopeSel.value, scope = { stat: statSel.value };
    if (t === "category" || t === "competency") scope.category = catSel.value;
    if (t === "competency") { scope.subcategory = subSel.value; scope.capability = capSel.value; }
    postJSON("/operator/challenges/api/create", {
      scope_type: t, scope: scope,
      target_xp: Number($("ch-xp").value || 50), duration_days: Number($("ch-dur").value || 7),
      title: $("ch-title").value, source: "self",
    }, "challenges");
  };
  page.addEventListener("click", function handler(e) {
    var cancel = e.target.closest("[data-cancel]");
    if (cancel) { postJSON("/operator/challenges/api/" + encodeURIComponent(cancel.dataset.cancel) + "/cancel", {}, "challenges"); return; }
    var sugg = e.target.closest("[data-sugg]");
    if (sugg) {
      try {
        var s = JSON.parse(sugg.dataset.sugg);
        postJSON("/operator/challenges/api/create", {
          scope_type: s.scope_type || "stat", scope: s.scope || { stat: s.stat },
          target_xp: s.target_xp || 50, duration_days: s.duration_days || 7,
          title: s.title || "", source: "suggested",
        }, "challenges");
      } catch (err) { /* ignore malformed suggestion */ }
    }
  }, { once: true });
}

/* ---------- tasks (real form submit, backend expects form-encoded) ---------- */
function renderTasks() {
  var tk = DATA.tasks;
  if (!tk) { setPage("g1", pn("TASKS", "", empty(DATA.tasks_error || "Tasks data unavailable."))); return; }
  var dayBtns = (tk.days || []).map(function (d) {
    return '<button type="button" data-day="' + d.key + '" class="' + (d.key === tk.active_day.key ? "on" : "") + '">' + d.label + '</button>';
  }).join("");
  var catalog = tk.catalog || [];
  var logRows = (tk.day_log || []).map(function (l) {
    return '<div class="row dim"><b>' + esc(l.capability || "") + '</b><small>' + (l.hours || 0) + 'h / ' + fmt(l.xp || 0) + ' XP</small><span class="r"></span></div>';
  }).join("") || empty("Nothing logged today.");
  setPage("g21",
    pn(tk.active_day.focus || "TASKS", "", '<div class="days" id="tk-days">' + dayBtns + '</div><p class="note" style="margin-top:8px">' + esc(tk.active_day.desc || "") + '</p>', "sp2")
    + pn("LOG SESSION", "", '<form method="post" action="/operator/tasks/log" id="tk-form">'
        + '<input type="hidden" name="day" value="' + esc(tk.active_day.key) + '">'
        + '<div class="two"><label class="f">STAT<select name="stat" id="tk-stat"></select></label><label class="f">CATEGORY<select name="category" id="tk-cat"></select></label></div>'
        + '<div class="two"><label class="f">SUBCATEGORY<select name="subcategory" id="tk-sub"></select></label><label class="f">CAPABILITY<select name="capability" id="tk-cap"></select></label></div>'
        + '<label class="f">HOURS<input name="hours" type="number" min="0.1" max="24" step="0.1" value="1"></label>'
        + '<button type="submit" class="btn main"><span>LOG SESSION</span></button></form>')
    + pn("TODAY'S LOG", "", '<div class="btns">' + logRows + '</div>')
  );
  $("tk-days").onclick = function (e) {
    var b = e.target.closest("[data-day]"); if (!b) return;
    fetchData(b.dataset.day).then(function () { route(); });
  };
  var statSel = $("tk-stat"), catSel = $("tk-cat"), subSel = $("tk-sub"), capSel = $("tk-cap");
  function stats() { var u = []; catalog.forEach(function (c) { if (u.indexOf(c.stat) < 0) u.push(c.stat); }); return u; }
  function fillStat() { statSel.innerHTML = stats().map(function (s) { return '<option value="' + s + '">' + s + '</option>'; }).join(""); fillCat(); }
  function fillCat() {
    var opts = catalog.filter(function (c) { return c.stat === statSel.value; });
    catSel.innerHTML = opts.map(function (c) { return '<option value="' + esc(c.category) + '">' + esc(c.category) + '</option>'; }).join(""); fillSub();
  }
  function fillSub() {
    var c = catalog.filter(function (c) { return c.stat === statSel.value && c.category === catSel.value; })[0];
    var subs = c ? Object.keys(c.subcategories) : [];
    subSel.innerHTML = subs.map(function (s) { return '<option value="' + esc(s) + '">' + esc(s) + '</option>'; }).join(""); fillCap();
  }
  function fillCap() {
    var c = catalog.filter(function (c) { return c.stat === statSel.value && c.category === catSel.value; })[0];
    var caps = (c && c.subcategories[subSel.value]) || [];
    capSel.innerHTML = caps.map(function (cp) { return '<option value="' + esc(cp.name) + '">' + esc(cp.name) + " (L" + cp.level + ")</option>"; }).join("");
  }
  statSel.onchange = fillCat; catSel.onchange = fillSub; subSel.onchange = fillCap;
  fillStat();
}

/* ---------- fitness ---------- */
function renderFitness() {
  var ft = DATA.fitness;
  if (!ft) { setPage("g1", pn("FITNESS", "", empty(DATA.fitness_error || "Fitness data unavailable."))); return; }
  var habits = (ft.habits || []).map(function (h) {
    return '<div class="exr"><span>' + esc(h.label) + '</span><em>L' + h.level + ' / ' + fmt(h.xp) + ' XP' + (h.secondary ? " + " + esc(h.secondary.label) : "") + '</em></div>';
  }).join("") || empty("No habits configured.");
  var inputs = (ft.habits || []).map(function (h) {
    return '<label class="f">' + esc(h.label) + " (" + esc(h.unit) + ', target ' + h.target + ')<input name="' + esc(h.key) + '" type="number" min="0" step="any"></label>';
  }).join("");
  var routineDays = ((ft.routine || {}).days || []).map(function (d) {
    return '<div class="exr"><span>' + esc(d.day) + '</span><em>' + esc(d.focus || d.name || "") + '</em></div>';
  }).join("") || empty("No weekly routine configured.");
  setPage("fit",
    '<aside class="pn" style="justify-self:start"><div class="bar-head"><span>DAILY HABITS</span><span>' + (ft.disc_average_level || 0).toFixed(2) + '</span></div><div class="frame">' + habits + '<div class="kv" style="margin-top:6px"><span>Streak</span><b>' + (ft.current_streak || 0) + ' days (best ' + (ft.longest_streak || 0) + ')</b></div></div></aside>'
    + '<div class="stage">' + (ft.muscular_strength_categories || []).map(function (c) {
        return '<button type="button" class="hs" data-hotspot="' + esc(c.hotspot) + '" style="slot:' + esc(c.hotspot) + '"><i>' + Math.floor(c.average_level) + '</i><span>' + esc(c.name.toUpperCase()) + '</span></button>';
      }).join("") + '</div>'
    + '<aside class="pn" style="justify-self:end"><div class="bar-head"><span>LOG TODAY</span><span>' + esc(ft.today_name || "") + '</span></div><div class="frame">'
      + '<form method="post" action="/operator/fitness/log">' + inputs + '<button type="submit" class="btn main" style="margin-top:6px"><span>LOG HABITS</span></button></form>'
      + '<form method="post" action="/operator/fitness/log-gym-day" style="margin-top:10px"><input type="hidden" name="day" value=""><button type="submit" class="btn"><span>LOG GYM DAY</span><small>' + esc((ft.todays_routine_day || {}).focus || "rest day") + '</small></button></form>'
      + '<div class="sec" style="margin-top:10px">WEEKLY ROUTINE</div>' + routineDays
      + '</div></aside>'
  );
}

/* ---------- journal: real in-hub "new entry" form, ported field-for-field
 * from the standalone journal.html (type picker + live XP preview, optional
 * tags/projects/domains/concepts/capabilities, optional manual XP + proof),
 * submitted as a real <form> POST to /operator/journal/create. That route's
 * _back() helper (modules/operator_journal.py) now redirects into this shell
 * with created=/error= instead of back to its own page; modules/operator_hud.py
 * forwards those into get_journal_dashboard_data() so DATA.journal.just_created
 * / .error are populated here exactly like the old page's banner. ---------- */
function renderJournal() {
  var jo = DATA.journal;
  if (!jo) { setPage("g1", pn("JOURNAL", "", empty(DATA.journal_error || "Journal data unavailable."))); return; }
  var catalog = jo.type_catalog || {};
  var types = jo.allowed_types || Object.keys(catalog);

  var banner = "";
  if (jo.error) {
    banner += '<div class="jpreview" style="border-color:var(--bad);margin-bottom:10px"><b style="color:var(--bad)">Couldn’t save that entry.</b><div style="margin-top:4px">' + esc(jo.error) + '</div></div>';
  }
  if (jo.just_created) {
    var jc = jo.just_created, baseXp = jc.base_xp || 0;
    var chips = baseXp > 0 ? (jc.xp_targets || []).map(function (t) {
      return '<span class="award"><b>' + Math.round((t.weight || 0) * baseXp) + ' XP</b> → ' + esc(t.competency_id) + '</span>';
    }).join("") : "";
    banner += '<div class="jpreview" style="margin-bottom:10px"><b>Saved: ' + esc(jc.title || "") + '</b><div style="margin-top:4px">'
      + (baseXp > 0 ? chips : "Recorded with no XP - just a note.") + '</div></div>';
  }

  var typeGrid = types.map(function (key) {
    var info = catalog[key] || {};
    var targets = (info.targets || []).map(function (t) { return t.name + " (" + t.stat + ")"; }).join(", ");
    return '<label data-tkey="' + esc(key) + '"><input type="checkbox" name="entry_types" value="' + esc(key) + '">'
      + '<div><b>' + esc(info.label || key) + '</b>' + (targets ? '<small>→ ' + esc(targets) + '</small>' : '') + '</div></label>';
  }).join("");

  var form = banner
    + '<form method="post" action="/operator/journal/create" id="journal-form">'
    + '<div style="display:grid;gap:10px">'
    + '<label class="f">TITLE<input type="text" name="title" placeholder="A few words about what this is" required></label>'
    + '<label class="f">WHAT’S ON YOUR MIND?<textarea name="body" placeholder="Write it exactly as you’d say it. This never gets edited or rewritten later." required></textarea></label>'
    + '<div><div class="sec">ENTRY TYPE (pick one or more)</div><p class="note">Picking more than one just splits the same total between them - it doesn’t add more XP.</p>'
    + '<div class="ttype" id="jn-types">' + typeGrid + '</div>'
    + '<div class="jpreview" id="jn-preview">Pick at least one type above to see where the XP will go.</div></div>'
    + '<details class="adv"><summary>Add project or concept tags (optional)</summary><div class="frame">'
    + '<div class="two"><label class="f">TAGS<input type="text" name="tags" placeholder="comma, separated"></label><label class="f">PROJECTS<input type="text" name="projects" placeholder="e.g. Shadow Ground Control"></label></div>'
    + '<div class="two" style="margin-top:10px"><label class="f">DOMAINS<input type="text" name="domains" placeholder="comma, separated"></label><label class="f">CONCEPTS<input type="text" name="concepts" placeholder="e.g. Camera Systems, REST APIs"></label></div>'
    + '<label class="f" style="margin-top:10px">CAPABILITIES<input type="text" name="capabilities" placeholder="comma, separated"></label>'
    + '</div></details>'
    + '<details class="adv"><summary>Give this entry its own XP instead of the automatic amount</summary><div class="frame">'
    + '<p class="note">Leave this closed and the entry just gets the automatic amount shown above. Only open this for something bigger than a normal note - it needs real proof.</p>'
    + '<div class="two"><label class="f">XP AMOUNT<input type="number" name="custom_xp" min="0" placeholder="e.g. 20"></label><label class="f">YOUR PROOF<input type="text" name="evidence_note" placeholder="A link, a commit, a file name"></label></div>'
    + '</div></details>'
    + '<button type="submit" class="btn main"><span>SAVE ENTRY</span></button>'
    + '</div></form>';

  var entries = (jo.entries || []).slice(0, 12).map(function (e) {
    return '<div class="row dim"><b>' + esc(e.title || "") + '</b><small>' + esc((e.entry_types || []).join(", ")) + '</small><span class="r">' + fmt(e.base_xp || e.xp || 0) + ' XP</span></div>';
  }).join("") || empty("No journal entries yet.");

  setPage("g21",
    pn("NEW ENTRY", "", form)
    + pn("RECENT ENTRIES", "", '<div class="btns">' + entries + '</div>')
  );

  function updatePreview() {
    var checked = Array.prototype.slice.call(page.querySelectorAll('#jn-types input:checked')).map(function (el) { return el.value; });
    var previewEl = $("jn-preview");
    var customXpEl = page.querySelector('input[name="custom_xp"]');
    var customXp = customXpEl ? parseInt(customXpEl.value, 10) : NaN;
    if (!checked.length) { previewEl.innerHTML = "Pick at least one type above to see where the XP will go."; return; }
    var perTypeWeight = 1 / checked.length, combined = {};
    checked.forEach(function (key) {
      var info = catalog[key]; if (!info) return;
      (info.targets || []).forEach(function (t) {
        var w = (t.weight || 0) * perTypeWeight;
        if (!combined[t.competency_id]) combined[t.competency_id] = { name: t.name, stat: t.stat, weight: 0 };
        combined[t.competency_id].weight += w;
      });
    });
    var totalXp = (customXp && customXp > 0) ? customXp : 30;
    var chips = Object.keys(combined).map(function (id) {
      var e = combined[id];
      return '<span class="award"><b>' + Math.round(e.weight * totalXp) + ' XP</b> → ' + esc(e.name) + ' (' + e.stat + ')</span>';
    }).join("");
    previewEl.innerHTML = '<b>' + totalXp + ' XP total</b><div style="margin-top:4px">' + chips + '</div>';
  }
  Array.prototype.forEach.call(page.querySelectorAll('#jn-types input'), function (el) {
    el.addEventListener("change", function () {
      el.closest("label").classList.toggle("on", el.checked);
      updatePreview();
    });
  });
  var customXpInput = page.querySelector('input[name="custom_xp"]');
  if (customXpInput) customXpInput.addEventListener("input", updatePreview);
  updatePreview();
}

/* ---------- learning: real in-hub library + notebook editor, against the
 * same /operator/learning/tracks/<id>/{notebook,evidence,complete} endpoints
 * the old notebook drawer (operator_notebook.js) used. Any unit can now be
 * opened/completed, in any order - not just whatever the server calls
 * "current" (see operator_learning.py's _resolve_unit_context docstring).
 * openNotebook(trackId, unitId) passes an explicit unitId when the operator
 * clicked a specific chapter/day chip; omitting it keeps the original
 * "open whatever's current" behavior (the plain CONTINUE button still works
 * exactly as before). Every write below (save/evidence/complete) is scoped
 * to whichever unit the open notebook actually resolved to server-side
 * (nb.unit_id), never to a stale client guess. Import Course / Reconcile
 * Boot.dev / Progress Import are real <form> POSTs too; their routes
 * redirect back into this shell (see operator_learning.py's _back()). ---------- */
var learningState = { openTrack: null, openUnit: null, nb: null, nbLoading: false, nbError: null, view: "courses", mapCapability: null };

function nbImgSrc(filename) {
  return "/operator/learning/tracks/" + encodeURIComponent(learningState.openTrack) + "/evidence/" + encodeURIComponent(filename);
}
function mdPreview(src) {
  if (!src || !src.trim()) return '<span class="muted">Nothing written yet.</span>';
  var lines = esc(src).split(/\r?\n/);
  var html = "", inList = null, para = [];
  var inline = function (t) {
    return t
      .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function (m, alt, target) {
        var files = (learningState.nb && learningState.nb.evidence_files) || [];
        if (files.indexOf(target) !== -1) return '<img src="' + nbImgSrc(target) + '" alt="' + alt + '" style="max-width:100%">';
        return '<span class="muted">[image: ' + (alt || target) + ']</span>';
      })
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  };
  var flush = function () { if (para.length) { html += "<p>" + inline(para.join(" ")) + "</p>"; para = []; } };
  var closeL = function () { if (inList) { html += "</" + inList + ">"; inList = null; } };
  lines.forEach(function (raw) {
    var line = raw.trim();
    if (!line) { flush(); closeL(); return; }
    var h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { flush(); closeL(); html += "<h" + h[1].length + ">" + inline(h[2]) + "</h" + h[1].length + ">"; return; }
    var ul = line.match(/^[-*]\s+(.*)$/);
    if (ul) { flush(); if (inList !== "ul") { closeL(); html += "<ul>"; inList = "ul"; } html += "<li>" + inline(ul[1]) + "</li>"; return; }
    closeL(); para.push(line);
  });
  flush(); closeL();
  return html || '<span class="muted">Nothing written yet.</span>';
}

function openNotebook(trackId, unitId) {
  // merges rather than replaces learningState - the notebook only ever
  // opens from the Courses tab's unit chips, but keeping view/mapCapability
  // around means closing it back out doesn't silently reset an unrelated
  // part of the panel's state.
  learningState = {
    view: learningState.view, mapCapability: learningState.mapCapability,
    openTrack: trackId, openUnit: unitId || null, nb: null, nbLoading: true, nbError: null,
  };
  renderLearning();
  var url = "/operator/learning/tracks/" + encodeURIComponent(trackId) + "/notebook";
  if (unitId) url += "?unit_id=" + encodeURIComponent(unitId);
  fetch(url)
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      learningState.nbLoading = false;
      if (!res.ok) { learningState.nbError = (res.d && res.d.error) || "Couldn’t load this unit."; }
      else { learningState.nb = res.d; }
      renderLearning();
    })
    .catch(function () { learningState.nbLoading = false; learningState.nbError = "Network error."; renderLearning(); });
}
function closeNotebook() {
  learningState = {
    view: learningState.view, mapCapability: learningState.mapCapability,
    openTrack: null, openUnit: null, nb: null, nbLoading: false, nbError: null,
  };
  renderLearning();
}
function saveNotebook() {
  var nb = learningState.nb; if (!nb) return Promise.resolve();
  var payload = {};
  if (nb.unit_id) payload.unit_id = nb.unit_id;
  ["notes", "reflection", "evidence_text"].forEach(function (key) {
    var el = $("nb-in-" + key);
    if (el) payload[key] = el.value;
  });
  return fetch("/operator/learning/tracks/" + encodeURIComponent(learningState.openTrack) + "/notebook", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (!res.ok) { toast((res.d && res.d.error) || "Couldn’t save."); return; }
      ["notes", "reflection", "evidence_text"].forEach(function (key) {
        var s = $("nb-stat-" + key); if (s) { s.classList.add("saved"); s.textContent = "SAVED"; }
      });
      toast("Notebook saved");
    })
    .catch(function () { toast("Network error - nothing saved."); });
}
function completeUnit() {
  var trackId = learningState.openTrack;
  var unitId = learningState.nb && learningState.nb.unit_id;
  saveNotebook().then(function () {
    var fd = new FormData();
    if (unitId) fd.append("unit_id", unitId);
    return fetch("/operator/learning/tracks/" + encodeURIComponent(trackId) + "/complete", { method: "POST", body: fd });
  }).then(function () {
    toast("Unit complete");
    closeNotebook();
    return fetchData(DAY);
  }).then(function () { route(); })
    .catch(function () { toast("Network error."); });
}
function renderEvidenceChips() {
  var el = $("nb-chips"); if (!el) return;
  el.innerHTML = ((learningState.nb && learningState.nb.evidence_files) || []).map(function (n) {
    return '<span class="nb-chip">' + esc(n) + '</span>';
  }).join("");
}
function uploadEvidence(file) {
  var fd = new FormData(); fd.append("file", file);
  if (learningState.nb && learningState.nb.unit_id) fd.append("unit_id", learningState.nb.unit_id);
  return fetch("/operator/learning/tracks/" + encodeURIComponent(learningState.openTrack) + "/evidence", { method: "POST", body: fd })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (!res.ok) { toast((res.d && res.d.error) || "Upload failed"); return; }
      if (!learningState.nb.evidence_files) learningState.nb.evidence_files = [];
      if (learningState.nb.evidence_files.indexOf(res.d.filename) === -1) learningState.nb.evidence_files.push(res.d.filename);
      var el = $("nb-in-evidence_text");
      var ref = "\n![" + res.d.filename.replace(/\.[a-z0-9]+$/i, "").replace(/[_-]/g, " ") + "](" + res.d.filename + ")\n";
      el.value = (el.value ? el.value + "\n" : "") + ref.trim();
      $("nb-pv-evidence_text").innerHTML = mdPreview(el.value);
      renderEvidenceChips();
      var s = $("nb-stat-evidence_text"); if (s) { s.classList.remove("saved"); s.textContent = "UNSAVED"; }
    })
    .catch(function () { toast("Upload failed - network error."); });
}
function wireNotebookFields() {
  var nb = learningState.nb; if (!nb) return;
  ["notes", "reflection", "evidence_text"].forEach(function (key) {
    var el = $("nb-in-" + key); if (!el) return;
    el.value = nb[key] || "";
    $("nb-pv-" + key).innerHTML = mdPreview(el.value);
    el.addEventListener("input", function () {
      $("nb-pv-" + key).innerHTML = mdPreview(el.value);
      var s = $("nb-stat-" + key); if (s) { s.classList.remove("saved"); s.textContent = "UNSAVED"; }
    });
  });
  if (nb.evidence_text !== null && nb.evidence_text !== undefined) {
    renderEvidenceChips();
    var zone = $("nb-dropzone"), fileInput = $("nb-file-input");
    if (zone && fileInput) {
      zone.addEventListener("click", function () { fileInput.click(); });
      fileInput.addEventListener("change", function (e) { Array.prototype.forEach.call(e.target.files, uploadEvidence); });
      ["dragenter", "dragover"].forEach(function (evt) { zone.addEventListener(evt, function (e) { e.preventDefault(); zone.classList.add("drag"); }); });
      ["dragleave", "drop"].forEach(function (evt) { zone.addEventListener(evt, function (e) { e.preventDefault(); zone.classList.remove("drag"); }); });
      zone.addEventListener("drop", function (e) { if (e.dataTransfer.files.length) Array.prototype.forEach.call(e.dataTransfer.files, uploadEvidence); });
    }
  }
  var saveBtn = $("nb-save"); if (saveBtn) saveBtn.onclick = saveNotebook;
  var completeBtn = $("nb-complete"); if (completeBtn) completeBtn.onclick = completeUnit;
  var closeBtn = $("nb-close"); if (closeBtn) closeBtn.onclick = closeNotebook;
}
function renderNotebookPanel() {
  if (learningState.nbLoading) return pn("NOTEBOOK", "", empty("Loading…"));
  if (learningState.nbError) return pn("NOTEBOOK", "", '<div class="jpreview" style="border-color:var(--bad)">' + esc(learningState.nbError) + '</div><button type="button" class="btn" id="nb-close" style="margin-top:10px"><span>CLOSE</span></button>');
  var nb = learningState.nb;
  if (!nb) return pn("NOTEBOOK", "", empty("Loading…"));

  var rewardItems = ((nb.reward_preview || {}).items || []).map(function (it) {
    return '<span class="award"><b>' + it.xp + ' XP</b> → ' + esc(it.name) + '</span>';
  }).join("");
  var field = function (key, label) {
    if (nb[key] === null || nb[key] === undefined) return "";
    return '<div style="margin-top:10px"><div class="sec">' + label + ' <span class="nb-status saved" id="nb-stat-' + key + '">SAVED</span></div>'
      + '<div class="nb-split"><div><div class="nb-pane-label">WRITE</div><textarea id="nb-in-' + key + '" style="min-height:100px"></textarea></div>'
      + '<div><div class="nb-pane-label">PREVIEW</div><div class="nb-preview" id="nb-pv-' + key + '"></div></div></div></div>';
  };
  var evidence = "";
  if (nb.evidence_text !== null && nb.evidence_text !== undefined) {
    evidence = '<div style="margin-top:10px"><div class="sec">EVIDENCE <span class="nb-status saved" id="nb-stat-evidence_text">SAVED</span></div>'
      + '<div class="nb-evidence-zone" id="nb-dropzone">Drag a file here, or click to browse<input type="file" id="nb-file-input" multiple></div>'
      + '<div class="nb-chips" id="nb-chips"></div>'
      + '<div class="nb-split"><div><div class="nb-pane-label">WRITE</div><textarea id="nb-in-evidence_text" style="min-height:100px"></textarea></div>'
      + '<div><div class="nb-pane-label">PREVIEW</div><div class="nb-preview" id="nb-pv-evidence_text"></div></div></div></div>';
  }
  var statusTag = nb.is_completed
    ? '<span class="tag ok">COMPLETED</span>'
    : (nb.is_current ? "" : '<span class="tag">OUT OF ORDER</span>');
  return pn(esc(nb.track_title), "UNIT " + (nb.unit_index + 1) + "/" + nb.unit_count,
    '<div class="jpreview">' + ((nb.reward_preview || {}).total_xp != null ? (nb.reward_preview || {}).total_xp : "?") + ' XP on completion<div style="margin-top:4px">' + rewardItems + '</div></div>'
    + '<b style="display:block;margin-top:10px;font:700 18px var(--display);letter-spacing:.04em">' + esc(nb.unit_title) + ' ' + statusTag + '</b>'
    + field("notes", "NOTES") + field("reflection", "REFLECTION") + evidence
    + '<div class="btns h" style="margin-top:12px"><button type="button" class="btn" id="nb-save"><span>SAVE NOTEBOOK</span></button><button type="button" class="btn main" id="nb-complete"><span>MARK UNIT COMPLETE</span></button><button type="button" class="btn" id="nb-close"><span>CLOSE</span></button></div>'
  );
}

/* ---------- learning: Concept Map tab - "the old thing" he asked to have
 * restored into the new hub. Built entirely from data the HUD already
 * fetches (DATA.overview.featured_capabilities / concepts_by_capability /
 * capability_slugs - same fields Overview's signature-skills drill-down
 * already uses, see openSkill() above), so it needed no new backend route
 * for the list+grid views themselves. ---------- */
function slugToCapId(slug) {
  var slugs = (DATA.overview || {}).capability_slugs || {};
  return Object.keys(slugs).filter(function (id) { return slugs[id] === slug; })[0];
}
function capabilityConceptCounts(capId) {
  var concepts = ((DATA.overview || {}).concepts_by_capability || {})[capId] || [];
  var started = concepts.filter(function (c) { return c.xp > 0 || c.status !== "Not Started"; }).length;
  return { started: started, total: concepts.length, concepts: concepts };
}
function renderConceptMapList() {
  var caps = ((DATA.overview || {}).featured_capabilities || []).slice().sort(function (a, b) { return b.xp - a.xp; });
  if (!caps.length) return empty("No capabilities tracked yet.");
  return caps.map(function (c) {
    var counts = capabilityConceptCounts(slugToCapId(c.slug));
    return '<button type="button" class="cm-row" data-cm="' + esc(c.slug) + '">'
      + '<div style="width:38px"><div class="ringp" style="--p:' + (c.coverage || 0) + '"><b>' + c.level + '</b></div></div>'
      + '<div><b>' + esc(c.name) + '</b><small>' + counts.started + ' of ' + counts.total + ' concepts started</small></div>'
      + '</button>';
  }).join("");
}
/* ---------- skill page: full in-HUD tiered concept-map + capability info,
 * reached via #skill/<slug> from either the Concept Map list's rows (below)
 * or Overview's Signature Skills "OPEN SKILL PAGE" (see openSkill() above).
 * Replaces the old cramped tile-grid drill-down AND the standalone
 * /operator/capabilities/<slug> page as the actual destination - that route
 * still exists server-side (and its get_capability_data() is exactly what
 * this fetches, via the thin /data JSON sibling added alongside it) but
 * nothing in the HUD links out to it anymore. ---------- */
var skillState = { slug: null, data: null, loading: false, error: null };
function backToCapabilities() {
  learningState.view = "map"; learningState.mapCapability = null;
  location.hash = "#learning";
}
function currentHashSlug() {
  var part = (location.hash || "").slice(1).split("/")[1] || "";
  try { return decodeURIComponent(part); } catch (e) { return part; }
}
function loadSkill(slug) {
  skillState = { slug: slug, data: null, loading: true, error: null };
  fetch("/operator/capabilities/" + encodeURIComponent(slug) + "/data")
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (skillState.slug !== slug) return; // superseded by a newer navigation
      skillState.loading = false;
      if (!res.ok) { skillState.error = (res.d && res.d.error) || "Couldn't load this capability."; }
      else { skillState.data = res.d; }
      if (currentHashSlug() === slug) renderSkillPage(slug);
    })
    .catch(function () {
      if (skillState.slug !== slug) return;
      skillState.loading = false; skillState.error = "Network error - couldn't reach the server.";
      if (currentHashSlug() === slug) renderSkillPage(slug);
    });
}
function renderSkillPage(slugRaw) {
  var slug = decodeURIComponent(slugRaw || "");
  var backBtn = '<button type="button" class="cm-back" id="skl-back">&larr; ALL CAPABILITIES</button>';
  if (!slug) { setPage("g1", backBtn + empty("No capability specified.")); page.onclick = function (e) { if (e.target.closest("#skl-back")) backToCapabilities(); }; return; }
  if (skillState.slug !== slug) loadSkill(slug);
  if (skillState.slug !== slug || skillState.loading) {
    setPage("g1", backBtn + empty("Loading capability..."));
    page.onclick = function (e) { if (e.target.closest("#skl-back")) backToCapabilities(); };
    return;
  }
  if (skillState.error || !skillState.data) {
    setPage("g1", backBtn + empty(skillState.error || "Capability not found."));
    page.onclick = function (e) { if (e.target.closest("#skl-back")) backToCapabilities(); };
    return;
  }
  var cap = skillState.data;
  $("crumb").innerHTML = "<a class=\"crumb-home\" href=\"/\">ZERO COMMAND</a> <b>/ LEARNING / " + esc(cap.name.toUpperCase()) + "</b>";

  var tierCols = (cap.tiers || []).map(function (tier) {
    var cards = (tier.concepts || []).map(function (c) {
      var started = c.xp > 0 || c.status !== "Not Started";
      return '<article class="skl-card' + (started ? "" : " zero") + '"><h3>' + esc(c.name) + '</h3><small>' + (started ? ("L" + c.level + " / " + fmt(c.xp) + " XP") : "not started") + '</small>'
        + (c.description ? '<p>' + esc(c.description) + '</p>' : "")
        + ((c.prerequisite_names || []).length ? '<small class="skl-suggested">suggested after: ' + esc(c.prerequisite_names.join(", ")) + '</small>' : "")
        + '</article>';
    }).join("");
    return '<div class="skl-col"><p class="skl-tier-label">' + esc(tier.label) + '</p>' + cards + '</div>';
  }).join("");
  var mapBody = '<div class="skl-head"><span>' + (cap.started_count || 0) + ' / ' + ((cap.concepts || []).length) + ' started</span></div>'
    + '<p class="note">Free order. Prerequisites are suggestions, not locks - any concept earns XP in any order.</p>'
    + '<div class="skl-tiers">' + (tierCols || empty("No concept map for this capability yet.")) + '</div>';

  var chips = (cap.relationships || []).map(function (r) { return '<span class="tag">' + esc(r.label) + '</span>'; }).join("");
  var infoBody = backBtn
    + '<div style="width:72px;margin:4px auto 10px"><div class="ringp" style="--p:' + (cap.coverage || 0) + '"><b style="font-size:20px">' + cap.level + '</b></div></div>'
    + (cap.description ? '<p class="note">' + esc(cap.description) + '</p>' : "")
    + '<div class="dl" style="margin-top:8px"><span>XP</span><b>' + fmt(cap.xp) + '</b></div>'
    + '<div class="dl"><span>COVERAGE</span><b>' + (cap.coverage || 0) + '%</b></div>'
    + '<div class="pb" style="margin:6px 0"><i style="width:' + Math.round(cap.coverage || 0) + '%"></i></div>'
    + (chips ? '<div class="sec" style="margin-top:10px">RELATED</div><div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">' + chips + '</div>' : "")
    + '<div class="btns" style="margin-top:12px">'
    + '<a class="btn" href="#tasks"><span>LOG HOURS</span></a>'
    + '<a class="btn" href="#execution"><span>LOG PROJECT</span></a>'
    + '<a class="btn" href="#challenges"><span>SET CHALLENGE</span></a>'
    + '</div>';

  var tracks = cap.tracks || [];
  var tracksBody = tracks.length
    ? '<div class="clist">' + tracks.map(function (t) {
        return '<div class="c"><span>' + esc(t.title) + '</span><em>' + t.completed + '/' + t.total + ' · ' + t.percentage + '%</em><div class="pb"><i style="width:' + (t.percentage || 0) + '%"></i></div></div>';
      }).join("") + '</div>'
    : empty("No tracks linked to this capability yet.");

  setPage("g12",
    pn(cap.name.toUpperCase(), "LV " + cap.level, infoBody)
    + pn("CONCEPT MAP", "", mapBody)
    + pn("LEARNING TRACKS", tracks.length + " linked", tracksBody)
  );
  page.onclick = function (e) { if (e.target.closest("#skl-back")) backToCapabilities(); };
}

function renderLearning() {
  var le = DATA.learning;
  if (!le) { setPage("g1", pn("LEARNING", "", empty(DATA.learning_error || "Learning data unavailable."))); return; }

  var groups = (le.library_groups || []).map(function (g, gi) {
    var cats = (g.categories || []).map(function (cat) {
      var rows = (cat.tracks || []).map(function (t) {
        var units = t.units || [];
        var chips = units.map(function (u) {
          var cls = "lib-unit-chip" + (u.completed ? " done" : "") + (u.is_current ? " current" : "");
          var label = u.title || u.id || "Unit";
          return '<button type="button" class="' + cls + '" data-nb="' + esc(t.id) + '" data-unit="' + esc(u.id || "") + '" title="' + esc(label) + '">' + esc(label) + '</button>';
        }).join("");
        var unitPicker = units.length
          ? '<div class="lib-unit-note">Any order - open any unit below. Out-of-order work still earns full XP.</div><div class="lib-unit-grid">' + chips + '</div>'
          : "";
        return '<details class="lib-track-wrap"><summary class="lib-track"><div><b>' + esc(t.title || "") + '</b><small>' + esc((t.provider || "").toUpperCase()) + ' · ' + esc(t.status || "") + '</small></div>'
          + '<span class="r">' + (t.percentage || 0) + '%</span>'
          + (t.current_unit ? '<button type="button" class="btn" data-nb="' + esc(t.id) + '"><span>CONTINUE</span></button>' : '<span class="tag ok">DONE</span>')
          + '</summary>' + unitPicker + '</details>';
      }).join("");
      return '<div class="lib-cat"><h4>' + esc(cat.name) + '</h4>' + rows + '</div>';
    }).join("");
    return '<details class="lib-stat"' + (gi === 0 ? " open" : "") + '><summary><span>' + esc(g.stat) + ' · ' + esc(g.domain) + '</span><small>' + (g.completed_units || 0) + '/' + (g.total_units || 0) + ' units · ' + (g.percentage || 0) + '%</small></summary>' + cats + '</details>';
  }).join("") || empty("No courses tracked yet.");

  var progress = '<div class="two"><div class="kv"><span>Operator level</span><b>' + (le.operator_level || 0) + '</b></div><div class="kv"><span>XP to next</span><b>' + fmt(le.operator_xp_to_next || 0) + '</b></div></div>'
    + '<div class="pb" style="margin-top:6px"><i style="width:' + (le.operator_level_progress || 0) + '%"></i></div>'
    + '<div class="two" style="margin-top:10px"><div class="kv"><span>Active tracks</span><b>' + (le.track_count || 0) + '</b></div><div class="kv"><span>Units</span><b>' + (le.completed_units || 0) + '/' + (le.total_units || 0) + '</b></div></div>'
    + '<div class="kv" style="margin-top:6px"><span>Track XP</span><b>' + fmt(le.total_track_xp || 0) + '</b></div>'
    + ((le.track_errors || []).length ? '<p class="note" style="margin-top:8px;color:var(--bad)">' + (le.track_errors || []).length + ' track(s) skipped - see server log.</p>' : "");

  // Collapsed-by-default <details> rows, same idiom as the Courses tab's
  // own per-track unit picker (.lib-track-wrap) - three compact summary
  // rows instead of three always-expanded forms eating panel space.
  var tools = '<details class="lib-stat"><summary><span>IMPORT COURSE</span></summary>'
    + '<form method="post" action="/operator/learning/import" class="two" style="align-items:end;padding:10px">'
    + '<label class="f" style="grid-column:1/-1">MANIFEST OR RESOURCE PATH<input type="text" name="manifest_path" placeholder="learning/resources/udemy/course_name" required></label>'
    + '<button type="submit" class="btn" style="grid-column:1/-1"><span>IMPORT</span></button></form></details>'
    + '<details class="lib-stat"><summary><span>PROGRESS SNAPSHOT</span></summary>'
    + '<form method="post" action="/operator/learning/provider-progress" style="padding:10px">'
    + '<label class="f">SNAPSHOT PATH<input type="text" name="snapshot_path" placeholder="learning/resources/youtube/course_name/progress_snapshot.json" required></label>'
    + '<label style="display:flex;gap:6px;align-items:center;margin-top:8px;font:500 11px var(--mono);color:var(--muted)"><input type="checkbox" name="dry_run" style="width:auto" checked> Dry run (preview only)</label>'
    + '<button type="submit" class="btn" style="margin-top:8px"><span>SYNCHRONISE</span></button></form></details>'
    + '<details class="lib-stat"><summary><span>BOOT.DEV</span></summary>'
    + '<form method="post" action="/operator/learning/providers/bootdev/reconcile" style="padding:10px"><button type="submit" class="btn"><span>RECONCILE BOOT.DEV</span></button></form></details>';

  var libTabs = '<div class="btns h" style="margin-bottom:10px">'
    + '<button type="button" class="btn' + (learningState.view === "map" ? "" : " main") + '" id="lib-tab-courses"><span>COURSES</span></button>'
    + '<button type="button" class="btn' + (learningState.view === "map" ? " main" : "") + '" id="lib-tab-map"><span>CONCEPT MAP</span></button>'
    + '</div>';
  var libraryBody = learningState.view === "map" ? renderConceptMapList() : groups;

  setPage("g21",
    pn("LEARNING LIBRARY", (le.track_count || 0) + " tracked", libTabs + libraryBody)
    + (learningState.openTrack ? renderNotebookPanel() : pn("PROGRESS", "", progress))
    + pn("TOOLS", "", tools)
  );

  page.onclick = function (e) {
    var tabCourses = e.target.closest("#lib-tab-courses");
    if (tabCourses) { learningState.view = "courses"; learningState.mapCapability = null; renderLearning(); return; }
    var tabMap = e.target.closest("#lib-tab-map");
    if (tabMap) { learningState.view = "map"; learningState.mapCapability = null; renderLearning(); return; }
    var cmRow = e.target.closest("[data-cm]");
    if (cmRow) { location.hash = "#skill/" + encodeURIComponent(cmRow.dataset.cm); return; }
    var nb = e.target.closest("[data-nb]");
    // preventDefault, not just a plain openNotebook() call: these buttons
    // sit inside a <summary> (the per-track row doubles as the unit-grid's
    // expand/collapse toggle) so a click would otherwise also flip the
    // <details> open/closed - stopping it here keeps opening a notebook
    // from randomly collapsing the chapter list it was just clicked from.
    if (nb) { e.preventDefault(); openNotebook(nb.dataset.nb, nb.dataset.unit || null); }
  };
  var closeBtn = $("nb-close");
  if (closeBtn) closeBtn.onclick = closeNotebook;
  if (learningState.openTrack && learningState.nb) wireNotebookFields();
}

/* ---------- analytics: cards + a cumulative-XP-over-time graph, ported
 * from the mockup's anChart(), driven by stat_timeseries.points (t/stat/cum
 * from operator_analytics.py's _stat_timeseries_hub_summary_and_activity,
 * same field names as every other real consumer of that data). ---------- */
var STC = { CON: "#ff8a7a", INT: "#70ffb4", STR: "#ffcf5c", DEX: "#67e8f9", DISC: "#c4a3ff", WILL: "#ff9de2", SPIRIT: "#a3e635" };
var anView = "cards", anStat = null;
function anChart(an) {
  var pts = ((an.stat_timeseries || {}).points) || [];
  var final = (an.stat_timeseries || {}).final_cumulative || {};
  if (!pts.length) return empty("No XP history yet.");
  var W = 620, H = 250, L = 44, R = 12, T = 12, B = 26;
  var ts = pts.map(function (p) { return Date.parse(p.t); });
  var t0 = Math.min.apply(null, ts), t1 = Math.max.apply(null, ts);
  var ym = Math.max.apply(null, ORDER.map(function (k) { return final[k] || 0; })) || 1;
  var X = function (t) { return L + (t - t0) / Math.max(1, t1 - t0) * (W - L - R); };
  var Y = function (v) { return T + (1 - v / ym) * (H - T - B); };
  var s = "";
  [0, 0.5, 1].forEach(function (f) {
    var y = Y(ym * f);
    s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '" stroke="rgba(255,255,255,.1)"/><text x="' + (L - 6) + '" y="' + (y + 3) + '" text-anchor="end" font-size="10" fill="#8eaa9b" font-family="IBM Plex Mono,monospace">' + fmt(Math.round(ym * f)) + '</text>';
  });
  var d0 = new Date(t0), d1 = new Date(t1);
  var mf = function (d) { return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); };
  s += '<text x="' + L + '" y="' + (H - 6) + '" font-size="10" fill="#8eaa9b" font-family="IBM Plex Mono,monospace">' + mf(d0) + '</text><text x="' + (W - R) + '" y="' + (H - 6) + '" text-anchor="end" font-size="10" fill="#8eaa9b" font-family="IBM Plex Mono,monospace">' + mf(d1) + '</text>';
  var dots = "";
  ORDER.forEach(function (k) {
    var P = pts.filter(function (p) { return p.stat === k; });
    if (!P.length) return;
    var dim = anStat && anStat !== k;
    var d = "M" + X(Date.parse(P[0].t)).toFixed(1) + " " + Y(0).toFixed(1);
    P.forEach(function (p) { d += "H" + X(Date.parse(p.t)).toFixed(1) + "V" + Y(p.cum).toFixed(1); });
    d += "H" + (W - R);
    s += '<path d="' + d + '" fill="none" stroke="' + STC[k] + '" stroke-width="2" opacity="' + (dim ? 0.25 : 1) + '"><title>' + k + " " + fmt(final[k] || 0) + ' XP</title></path>';
    // real per-point hover targets: a small visible dot plus a larger
    // invisible hit circle (easier to land the cursor on) carrying the
    // point's date/stat/value as data-* attrs, read by the mousemove
    // handler wired below in renderAnalytics(). Skipped for a dimmed
    // (unselected) stat so hover stays scoped to what's actually visible.
    if (!dim) {
      P.forEach(function (p) {
        var cx = X(Date.parse(p.t)).toFixed(1), cy = Y(p.cum).toFixed(1);
        dots += '<circle class="an-hit" cx="' + cx + '" cy="' + cy + '" r="9" data-t="' + esc(p.t) + '" data-stat="' + k + '" data-cum="' + p.cum + '"/>'
          + '<circle class="an-dot" cx="' + cx + '" cy="' + cy + '" r="2.5" fill="' + STC[k] + '"/>';
      });
    }
  });
  s += dots;
  return '<div class="an-chart-wrap"><svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" preserveAspectRatio="none" role="img" aria-label="Cumulative XP over time by attribute">' + s + '</svg><div class="an-tip" id="an-tip"></div></div>'
    + '<div class="lg">' + ORDER.map(function (k) { return '<button type="button" data-lg="' + k + '" class="' + (anStat === k ? "on" : "") + '"><i style="background:' + STC[k] + '"></i>' + k + ' <span>' + fmt(final[k] || 0) + '</span></button>'; }).join("") + '</div>';
}
function renderAnalytics() {
  var an = DATA.analytics;
  if (!an) { setPage("g1", pn("ANALYTICS", "", empty(DATA.analytics_error || "Analytics data unavailable."))); return; }
  var stats = an.stats || {};
  var statCards = ORDER.map(function (k) {
    var s = stats[k] || { xp: 0, average_level: 0 };
    return '<button type="button" class="sc' + (anStat === k ? " on" : "") + '" data-stat="' + k + '"><span>' + k + '</span><b>' + s.average_level.toFixed(2) + '</b><i class="pb"><u style="width:' + Math.round((s.average_level - Math.floor(s.average_level)) * 100) + '%"></u></i><small>' + fmt(s.xp) + ' XP</small></button>';
  }).join("");
  var body = statCards ? '<div class="sgrid">' + statCards + '</div>' : "";
  if (anView === "graph") { body = anChart(an); }
  else if (anStat) {
    var cats = (an.full_category_rollup || {})[anStat] || [];
    body += '<div class="sec" style="margin-top:6px">' + anStat + ' CATEGORIES</div>' + (cats.length ? cats.slice().sort(function (a, b) { return (b.xp || 0) - (a.xp || 0); }).map(function (c) {
      return '<div class="hb" style="grid-template-columns:1fr 60px 70px"><span title="' + esc(c.category || "") + '">' + esc((c.category || "").toUpperCase()) + '</span><em>' + (c.average_level || 0).toFixed(2) + '</em><em>' + fmt(c.xp || 0) + ' XP</em></div>';
    }).join("") : empty("No category breakdown for " + anStat + " yet.")) + '<a class="btn" href="#tree/' + anStat + '"><span>OPEN ' + anStat + ' TREE</span></a>';
  }
  var hubs = Object.keys(an.hub_summary || {}).map(function (h) {
    var v = an.hub_summary[h];
    return '<a class="hubc" href="#' + h + '"><span>' + h.toUpperCase() + '</span><b>' + fmt(v.xp) + ' XP</b><small>' + v.count + ' awards</small></a>';
  }).join("");
  var topCats = (an.category_rollup || []).slice(0, 10).map(function (c) {
    return '<div class="hb"><span>' + esc(c.name || c.category || "") + '</span><div class="pb"><i style="width:' + Math.round((c.average_level ? (c.average_level - Math.floor(c.average_level)) * 100 : 0)) + '%"></i></div><em>' + fmt(c.xp || 0) + ' XP</em></div>';
  }).join("") || empty("No category data yet.");
  var timeline = (an.timeline || []).slice(0, 15).map(function (t) {
    return '<div><span>' + esc((t.hub || "").toUpperCase()) + '</span><span>' + esc(t.label || "") + '</span><em>+' + fmt(t.xp || 0) + '</em></div>';
  }).join("") || empty("No recent activity.");
  var toggle = '<span class="seg" style="display:inline-flex"><button type="button" data-av="cards" class="' + (anView === "cards" ? "on" : "") + '" style="padding:1px 10px">CARDS</button><button type="button" data-av="graph" class="' + (anView === "graph" ? "on" : "") + '" style="padding:1px 10px">GRAPH</button></span>';
  setPage("an",
    pn("MAIN STATS", toggle, body, "sp2")
    + pn("HUBS", "", '<div class="hubs">' + hubs + '</div>')
    + pn("RECENT ACTIVITY", "", '<div class="tl">' + timeline + '</div>')
    + pn("TOP CATEGORIES", "", topCats)
  );
  page.onclick = function (e) {
    var v = e.target.closest("[data-av]"), s = e.target.closest("[data-stat]"), g = e.target.closest("[data-lg]");
    if (v) { anView = v.dataset.av; renderAnalytics(); }
    else if (s) { anStat = anStat === s.dataset.stat ? null : s.dataset.stat; renderAnalytics(); }
    else if (g) { anStat = anStat === g.dataset.lg ? null : g.dataset.lg; renderAnalytics(); }
  };
  if (anView === "graph") {
    var chartWrap = page.querySelector(".an-chart-wrap"), tip = $("an-tip");
    if (chartWrap && tip) {
      chartWrap.addEventListener("mousemove", function (e) {
        var hit = e.target.closest(".an-hit");
        if (!hit) { tip.style.display = "none"; return; }
        var when = new Date(hit.dataset.t);
        var df = isNaN(when.getTime()) ? hit.dataset.t : when.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
        tip.innerHTML = '<b>' + esc(hit.dataset.stat) + '</b><small>' + esc(df) + '</small><em>' + fmt(Number(hit.dataset.cum) || 0) + ' XP</em>';
        var box = chartWrap.getBoundingClientRect();
        tip.style.left = Math.min(box.width - 10, e.clientX - box.left + 12) + "px";
        tip.style.top = Math.max(0, e.clientY - box.top - 34) + "px";
        tip.style.display = "block";
      });
      chartWrap.addEventListener("mouseleave", function () { tip.style.display = "none"; });
    }
  }
}

/* ---------- achievements ---------- */
function renderAchievements() {
  var ac = DATA.achievements;
  if (!ac) { setPage("g1", pn("ACHIEVEMENTS", "", empty(DATA.achievements_error || "Achievements data unavailable."))); return; }
  var tracks = (ac.tracks || []).map(function (t) {
    var ms = (t.milestones || []).map(function (m) {
      return '<div class="ach' + (m.unlocked ? " done" : "") + '"><div class="ic"><i>L' + m.level_threshold + '</i></div><b>' + esc(m.title) + '</b><small>' + m.current_xp_display + ' / ' + m.xp_needed_display + ' XP</small><div class="pb"><i style="width:' + (m.progress_percentage || 0) + '%"></i></div></div>';
    }).join("");
    var cs = (t.courses || []).map(function (c) {
      return '<div class="ach' + (c.unlocked ? " done" : "") + '"><div class="ic"><i>C</i></div><b>' + esc(c.title) + '</b><small>' + esc(c.course_status || "") + '</small></div>';
    }).join("");
    return pn(t.label, t.current_xp_display + " XP / L" + t.current_level, (ms || empty("No milestones.")) + cs);
  }).join("");
  setPage("g3", tracks || empty("No achievement tracks yet."));
}

/* ---------- skill tree: horizontal cascading columns, ported from the
 * mockup's own V.tree() - each depth is its own .col, clicking a row at
 * depth N replaces the path from N onward and the columns to the right
 * re-render, same side-by-side cascade as the approved mockup. ---------- */
var treeState = { stat: "INT", path: [] };
function nodeXp(node) { return sumXp(node); }
function bestChainFrom(node) {
  var path = [];
  while (node && node.children && Object.keys(node.children).length) {
    var kids = node.children, bestName = null, bestAvg = -1;
    Object.keys(kids).forEach(function (name) {
      var avg = kids[name].average_level || 0;
      if (avg > bestAvg) { bestAvg = avg; bestName = name; }
    });
    if (bestName == null) break;
    path.push(bestName);
    node = kids[bestName];
  }
  return path;
}
function renderTree(initial) {
  if (initial && initial !== treeState.stat) { treeState = { stat: initial, path: [] }; }
  var ov = DATA.overview || {};
  var tree = ov.tree || {};
  var statAvg = function (k) { return ((tree[k] || {}).average_level || 0).toFixed(2); };
  var tabs = ORDER.map(function (s) {
    return '<button type="button" data-s="' + s + '" class="' + (s === treeState.stat ? "on" : "") + '">' + s + '<small>' + statAvg(s) + '</small></button>';
  }).join("");

  if (!treeState.path.length) {
    treeState.path = bestChainFrom(tree[treeState.stat]);
  }

  var cols = "", node = tree[treeState.stat], lvl = 0, crumb = [treeState.stat];
  while (node && node.children && Object.keys(node.children).length) {
    var kids = node.children;
    var names = Object.keys(kids);
    var selName = treeState.path[lvl];
    var rows = names.map(function (name) {
      var c = kids[name];
      var hasKids = c.children && Object.keys(c.children).length;
      if (!hasKids) {
        return '<button type="button" class="row' + (name === selName ? " sel" : "") + (c.xp ? "" : " dim") + '" data-l="' + lvl + '" data-n="' + esc(name) + '">' + mini(c.level_progress || 0, c.level || 0) + '<b>' + esc(name) + '</b><small>' + fmt(c.xp || 0) + ' XP</small><span class="r">' + (c.xp ? Math.round(c.level_progress || 0) + "%" : "-") + '</span></button>';
      }
      var count = Object.keys(c.children).length;
      var avg = c.average_level || 0;
      return '<button type="button" class="row' + (name === selName ? " sel" : "") + '" data-l="' + lvl + '" data-n="' + esc(name) + '"><div style="width:6px"></div><b>' + esc(name) + '</b><small>' + count + ' groups</small><span class="r">' + avg.toFixed(2) + '</span></button>';
    }).join("");
    cols += '<div class="col">' + (rows || empty("Nothing here yet.")) + '</div>';
    var nextName = treeState.path[lvl];
    var next = nextName ? kids[nextName] : null;
    if (next && next.children && Object.keys(next.children).length) {
      crumb.push(nextName); node = next; lvl++;
    } else {
      node = null;
    }
  }

  setPage("g1 fill",
    pn("SKILL TREE", esc(crumb.join(" / ")), '<div class="tabs">' + tabs + '</div><div class="cols">' + cols + '</div><p class="note">Click a group to open it, click a skill to open its page. Dim rows have no XP yet.</p>')
  );
  page.onclick = function (e) {
    var s = e.target.closest("[data-s]"), r = e.target.closest("[data-l]");
    if (s) { treeState = { stat: s.dataset.s, path: [] }; renderTree(); return; }
    if (r) {
      var lvl2 = +r.dataset.l;
      treeState.path = treeState.path.slice(0, lvl2).concat([r.dataset.n]);
      renderTree();
    }
  };
}

/* ---------- POST helper: fetch JSON, refetch data, re-render, toast ---------- */
function postJSON(url, body, viewAfter) {
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (!res.ok) { toast(res.d && res.d.error ? res.d.error : "That didn't save."); return; }
      toast("Saved");
      return fetchData(DAY).then(function () {
        route();
      });
    })
    .catch(function () { toast("Network error - nothing saved."); });
}

/* ---------- 3D model hotspots (fitness) ---------- */
function positionHotspots() {
  if (!mv || root.getAttribute("data-view") !== "fitness") return;
  document.querySelectorAll(".hs[data-hotspot]").forEach(function (b) {
    var cat = ((DATA.fitness && DATA.fitness.muscular_strength_categories) || []).filter(function (c) { return c.hotspot === b.dataset.hotspot; })[0];
    if (!cat) return;
    b.setAttribute("slot", "hotspot-" + cat.hotspot);
    b.setAttribute("data-position", cat.position);
    b.setAttribute("data-normal", cat.normal);
    mv.appendChild(b);
  });
}

/* ---------- router ---------- */
function route() {
  var hash = (location.hash || "#overview").slice(1);
  var parts = hash.split("/");
  var view = parts[0] || "overview";
  if (NAV.filter(function (n) { return n[0] === view; }).length === 0 && view !== "tree" && view !== "skill") view = "overview";
  closeDet();
  root.setAttribute("data-view", view);
  renderChrome(view);
  if (view === "overview") { renderOverview(); return; }
  if (view === "execution") { renderExecution(); return; }
  if (view === "flights") { renderFlights(); return; }
  if (view === "challenges") { renderChallenges(); return; }
  if (view === "tasks") { renderTasks(); return; }
  if (view === "fitness") { renderFitness(); setTimeout(positionHotspots, 300); return; }
  if (view === "journal") { renderJournal(); return; }
  if (view === "learning") { renderLearning(); return; }
  if (view === "analytics") { renderAnalytics(); return; }
  if (view === "achievements") { renderAchievements(); return; }
  if (view === "tree") { renderTree(parts[1] || treeState.stat); return; }
  if (view === "skill") { renderSkillPage(parts[1] || ""); return; }
}
window.addEventListener("hashchange", route);

/* ---------- boot ---------- */
function fetchData(dayKey) {
  DAY = dayKey || DAY;
  var url = "/operator/hud/data" + (DAY ? "?day=" + encodeURIComponent(DAY) : "");
  return fetch(url).then(function (r) { return r.json(); }).then(function (d) {
    DATA = d; DAY = d.day_key;
    return d;
  });
}
function handleReturnParams() {
  var qs = new URLSearchParams(location.search);
  var hudView = qs.get("hud_view");
  var error = qs.get("error"), output = qs.get("output"), logged = qs.get("logged"), day = qs.get("day");
  if (error) toast(error);
  else if (logged) toast("Logged");
  else if (output) toast(output.split("\n")[0]);
  if (day) DAY = day;
  if (hudView) location.hash = "#" + hudView;
  if (qs.toString()) history.replaceState(null, "", location.pathname + location.hash);
}
handleReturnParams();
fetchData(DAY).then(function () {
  $("loading").style.visibility = "hidden";
  route();
}).catch(function () {
  $("loading").textContent = "COULD NOT LOAD OPERATOR DATA";
});
})();
