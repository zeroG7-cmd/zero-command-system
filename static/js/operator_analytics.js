// Operator Analytics Hub - cross-hub summary page.
//
// DATA comes from modules/operator_analytics.py's get_analytics_dashboard_data(),
// injected by the template as window.__ANALYTICS_DATA__ (see analytics.html).
// This file is otherwise the verified logic from the Analytics Hub demo,
// unchanged, just reading real data instead of a hardcoded blob.
const DATA = window.__ANALYTICS_DATA__;
const HUB_URLS = window.__ANALYTICS_HUB_URLS__ || {};

const HUB_META = {
    fitness: { icon: '💪', label: 'Fitness' },
    learning: { icon: '📚', label: 'Learning' },
    journal: { icon: '📓', label: 'Journal' },
    tasks: { icon: '✅', label: 'Tasks' },
    execution: { icon: '🛠️', label: 'Execution' },
};
Object.keys(HUB_META).forEach(key => { HUB_META[key].url = HUB_URLS[key] || '#'; });

// Level card
const p = DATA.progression;
document.getElementById('an-level-card').innerHTML = `
    <div class="an-level-badge"><span class="n">${p.level}</span><span class="l">LEVEL</span></div>
    <div class="an-level-info">
        <div class="xp-line"><span>Total XP: <b>${p.total_xp.toLocaleString()}</b></span><span>${p.xp_to_next_level} xp to Level ${p.level + 1}</span></div>
        <div class="an-bar-track"><div class="an-bar-fill" style="width:${p.progress_percentage}%"></div></div>
    </div>
`;

// Stat strip - same whole+pct format as the real Task Hub Operator Stats
// panel (modules/tasks.py _stats_panel(): whole=int(average_level), pct=
// fractional part *100, rounded to 1dp). average_level is a recursive
// average of every capability level beneath this stat.
function splitOverall(avg) {
    const whole = Math.trunc(avg);
    const pct = Math.round((avg - whole) * 1000) / 10;
    return { whole, pct };
}

const stripEl = document.getElementById('an-stat-strip');
Object.entries(DATA.stats).forEach(([stat, s]) => {
    const { whole, pct } = splitOverall(s.average_level);
    const catCount = (DATA.full_category_rollup[stat] || []).length;
    const div = document.createElement('div');
    div.className = 'an-stat-cell';
    div.dataset.stat = stat;
    div.innerHTML = `
        <div class="name">${stat}</div>
        <div class="overall">${whole} <span class="pct">· ${pct}%</span></div>
        <div class="an-bar-track-sm"><div class="an-bar-fill-sm" style="width:${pct}%"></div></div>
        <div class="xp">${s.xp} xp</div>
        <div class="cat-count">${catCount} categories ▾</div>
    `;
    div.addEventListener('click', () => toggleStatDetail(stat, div));
    stripEl.appendChild(div);
});

// Nested per-stat category detail - clicking a stat cell expands the FULL
// category list for that stat (not just the top-10 cross-stat panel below,
// which stays as its own separate thing). Accordion: one open at a time.
// Same whole+pct-bar row format as the top-10 panel, just scoped to one stat.
let openStatDetail = null;

function renderStatDetail(stat) {
    const cats = DATA.full_category_rollup[stat] || [];
    document.getElementById('an-stat-detail-title').textContent = `${stat} — all ${cats.length} categories`;
    const list = document.getElementById('an-stat-detail-list');
    list.innerHTML = '';
    cats.forEach(c => {
        const { whole, pct } = splitOverall(c.average_level);
        const div = document.createElement('div');
        div.className = 'an-cat-row';
        div.innerHTML = `
            <div class="head">
                <span class="name">${c.category}</span>
                <span class="right">Ov <b>${whole}</b> · ${pct}%</span>
            </div>
            <div class="an-bar-track-sm"><div class="an-bar-fill-sm" style="width:${pct}%"></div></div>
            <div class="xp">${c.xp} xp${c.xp === 0 ? ' · not started' : ''}</div>
        `;
        list.appendChild(div);
    });
}

function toggleStatDetail(stat, cellEl) {
    const detailEl = document.getElementById('an-stat-detail');
    document.querySelectorAll('.an-stat-cell').forEach(c => c.classList.remove('active'));
    if (openStatDetail === stat) {
        // clicking the already-open stat closes it
        detailEl.style.display = 'none';
        openStatDetail = null;
        return;
    }
    openStatDetail = stat;
    cellEl.classList.add('active');
    renderStatDetail(stat);
    detailEl.style.display = '';
}

document.getElementById('an-stat-detail-close').addEventListener('click', () => {
    document.querySelectorAll('.an-stat-cell').forEach(c => c.classList.remove('active'));
    document.getElementById('an-stat-detail').style.display = 'none';
    openStatDetail = null;
});

// Stat graph - XP over time per stat, cumulative. Built from real
// distribution receipts (operator_core/distribution/receipts/*.json), each
// of which records the exact per-stat XP split for one completion. Task Hub
// and Execution Hub don't create receipts yet (they call
// update_operator_competencies() directly), so their XP won't appear here
// or in Recent Activity until that gets wired up the same way Fitness,
// Learning and Journal already are - receipt_coverage below reports the
// real, current gap (if any) rather than assuming full coverage.
const STAT_COLORS = { CON:'#ffb454', INT:'#70b4ff', STR:'#70ffb4', DEX:'#ff70c8', DISC:'#ffe066', WILL:'#b48eff', SPIRIT:'#ff8e8e' };
const ts = DATA.stat_timeseries;

// Real data points only (no synthetic start/end padding), each with the
// per-event xp delta, precomputed once for hover hit-testing/tooltips.
const hoverPoints = (() => {
    const lastCum = {};
    return ts.points.map(pt => {
        const tMs = new Date(pt.t).getTime();
        const delta = pt.cum - (lastCum[pt.stat] || 0);
        lastCum[pt.stat] = pt.cum;
        return { stat: pt.stat, t: tMs, cum: pt.cum, delta, tIso: pt.t };
    });
})();

// Populated by renderStatChart() with the current coordinate mapping, so
// the hover handler can hit-test points without recomputing chart geometry.
let chartGeom = null;

function renderStatChart(highlight) {
    const canvas = document.getElementById('an-stat-chart');
    const ctx = canvas.getContext('2d');
    if (!ctx) return; // no 2D canvas context available in this environment
    const W = canvas.width, H = canvas.height;
    const padL = 42, padR = 16, padT = 16, padB = 28;
    ctx.clearRect(0, 0, W, H);

    const points = ts.points;
    if (!points.length) return;
    const t0 = new Date(points[0].t).getTime();
    const t1 = new Date(points[points.length - 1].t).getTime();
    const span = Math.max(1, t1 - t0);
    const maxCum = Math.max(1, ...Object.values(ts.final_cumulative));

    // series per stat: running list of {x, y}, starting at (t0, 0)
    const series = {};
    Object.keys(STAT_COLORS).forEach(stat => { series[stat] = [{ t: t0, cum: 0 }]; });
    points.forEach(pt => { series[pt.stat].push({ t: new Date(pt.t).getTime(), cum: pt.cum }); });
    Object.keys(series).forEach(stat => { series[stat].push({ t: t1, cum: series[stat][series[stat].length - 1].cum }); });

    const x = t => padL + ((t - t0) / span) * (W - padL - padR);
    const y = v => H - padB - (v / (maxCum || 1)) * (H - padT - padB);

    chartGeom = { x, y, padL, padR, padT, padB, W, H };

    // gridlines
    ctx.strokeStyle = 'rgba(112,255,180,.12)';
    ctx.lineWidth = 1;
    ctx.font = '11px Segoe UI, system-ui, sans-serif';
    ctx.fillStyle = '#8eaa9b';
    for (let i = 0; i <= 4; i++) {
        const v = Math.round((maxCum * i) / 4);
        const yy = y(v);
        ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke();
        ctx.fillText(String(v), 4, yy + 3);
    }

    // lines
    Object.entries(series).forEach(([stat, pts]) => {
        if (ts.final_cumulative[stat] === 0) return; // skip flat-zero stats
        ctx.strokeStyle = STAT_COLORS[stat];
        ctx.lineWidth = 2;
        ctx.beginPath();
        pts.forEach((pt, i) => { const px = x(pt.t), py = y(pt.cum); if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); });
        ctx.stroke();
    });

    // hover highlight: dashed vertical guide + a ring around the nearest point
    if (highlight) {
        const px = x(highlight.t), py = y(highlight.cum);
        ctx.save();
        ctx.strokeStyle = 'rgba(255,255,255,.22)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(px, padT); ctx.lineTo(px, H - padB); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = STAT_COLORS[highlight.stat];
        ctx.beginPath(); ctx.arc(px, py, 4.5, 0, Math.PI * 2); ctx.fill();
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = '#0c1210';
        ctx.beginPath(); ctx.arc(px, py, 4.5, 0, Math.PI * 2); ctx.stroke();
        ctx.restore();
    }

    // legend
    const legend = document.getElementById('an-chart-legend');
    legend.innerHTML = Object.keys(STAT_COLORS)
        .filter(stat => ts.final_cumulative[stat] > 0)
        .map(stat => `<span><i style="background:${STAT_COLORS[stat]}"></i>${stat} (${ts.final_cumulative[stat]} xp)</span>`)
        .join('');
}

// Hover tooltip: find the nearest real data point (in canvas pixel space)
// to the cursor and, if close enough, redraw the chart with that point
// highlighted and show a tooltip with its stat/timestamp/xp.
const statChartCanvas = document.getElementById('an-stat-chart');
const statChartTooltip = document.getElementById('an-chart-tooltip');
const statChartWrap = document.getElementById('an-chart-wrap');
let lastHoverKey = null;
const HOVER_HIT_RADIUS = 22; // canvas-pixel-space radius, generous for touch/trackpad

function clearChartHover() {
    if (lastHoverKey === null) return;
    lastHoverKey = null;
    statChartTooltip.style.display = 'none';
    renderStatChart();
}

if (statChartCanvas) {
    statChartCanvas.addEventListener('mousemove', e => {
        if (!chartGeom) return;
        const rect = statChartCanvas.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        const scaleX = statChartCanvas.width / rect.width;
        const scaleY = statChartCanvas.height / rect.height;
        const mx = (e.clientX - rect.left) * scaleX;
        const my = (e.clientY - rect.top) * scaleY;

        let nearest = null, nearestDist = Infinity;
        hoverPoints.forEach(pt => {
            if (ts.final_cumulative[pt.stat] === 0) return; // line isn't drawn, so not hoverable
            const px = chartGeom.x(pt.t), py = chartGeom.y(pt.cum);
            const d = Math.hypot(px - mx, py - my);
            if (d < nearestDist) { nearestDist = d; nearest = pt; }
        });

        if (!nearest || nearestDist > HOVER_HIT_RADIUS) { clearChartHover(); return; }

        const key = nearest.stat + '|' + nearest.t;
        if (key !== lastHoverKey) {
            lastHoverKey = key;
            renderStatChart(nearest);
            statChartTooltip.innerHTML =
                `<b style="color:${STAT_COLORS[nearest.stat]}">${nearest.stat}</b> <span class="muted">+${nearest.delta} xp</span><br>` +
                `${new Date(nearest.tIso).toLocaleString()}<br>` +
                `<span class="muted">running total: ${nearest.cum} xp</span>`;
            statChartTooltip.style.display = 'block';
        }

        // position tooltip relative to the chart-wrap, near the highlighted point
        const canvasRect = statChartCanvas.getBoundingClientRect();
        const wrapRect = statChartWrap.getBoundingClientRect();
        const px = chartGeom.x(nearest.t) / scaleX, py = chartGeom.y(nearest.cum) / scaleY;
        let left = (canvasRect.left - wrapRect.left) + px + 14;
        let top = (canvasRect.top - wrapRect.top) + py - 12;
        const tw = statChartTooltip.offsetWidth, th = statChartTooltip.offsetHeight;
        if (left + tw > wrapRect.width) left = (canvasRect.left - wrapRect.left) + px - tw - 14;
        if (top < 0) top = 4;
        if (top + th > wrapRect.height) top = wrapRect.height - th - 4;
        statChartTooltip.style.left = left + 'px';
        statChartTooltip.style.top = top + 'px';
    });

    statChartCanvas.addEventListener('mouseleave', clearChartHover);
}

const coverage = ts.receipt_coverage;
const coverageNote = coverage.full_coverage
    ? 'full coverage'
    : `${coverage.xp_covered} of ${coverage.xp_total_reconciled} total xp on record - ${coverage.xp_total_reconciled - coverage.xp_covered} xp isn't in a receipt yet (Task Hub/Execution completions don't create one)`;
document.getElementById('an-chart-caption').innerHTML = coverage.receipts_count
    ? `<b>XP over time, per stat</b> - built from ${coverage.receipts_count} distribution receipts on disk (${coverage.allocations_count} per-stat allocations, ${coverageNote}), spanning ${new Date(coverage.earliest).toLocaleDateString()} to ${new Date(coverage.latest).toLocaleDateString()}.`
    : `<b>XP over time, per stat</b> - no distribution receipts on disk yet.`;

document.getElementById('an-stat-toggle').addEventListener('click', e => {
    const btn = e.target.closest('button');
    if (!btn) return;
    document.querySelectorAll('#an-stat-toggle button').forEach(b => b.classList.toggle('active', b === btn));
    const isGraph = btn.dataset.view === 'graph';
    document.getElementById('an-stat-strip').style.display = isGraph ? 'none' : '';
    document.getElementById('an-chart-wrap').style.display = isGraph ? '' : 'none';
    if (isGraph) {
        // switching to Graph hides the nested per-stat detail too - it only
        // makes sense alongside the card strip it expands out of
        document.querySelectorAll('.an-stat-cell').forEach(c => c.classList.remove('active'));
        document.getElementById('an-stat-detail').style.display = 'none';
        openStatDetail = null;
        renderStatChart();
    }
});

// Hub cards - each links out to that hub's own page
const hubGrid = document.getElementById('an-hub-grid');
['fitness', 'learning', 'journal', 'tasks', 'execution'].forEach(key => {
    const h = DATA.hub_summary[key];
    const meta = HUB_META[key];
    const a = document.createElement('a');
    a.href = meta.url;
    a.className = 'an-hub-card' + (h.count === 0 ? ' empty' : '');
    a.innerHTML = `
        <div class="ic">${meta.icon}</div>
        <div class="name">${meta.label}</div>
        <div class="xp">${h.count === 0 ? '—' : h.xp + ' xp'}</div>
        <div class="count">${h.count} logged</div>
    `;
    hubGrid.appendChild(a);
});

// Top categories - numbered ranking, same format as Top Capabilities and
// sorted the same way: by XP descending, so the visible ranking always
// matches the visible number. The "Ov" number (average_level's whole part)
// will read 0 for most/all entries - that's expected, it's a secondary
// reference number now. Full detail (bar + percentage) lives in the nested
// per-stat detail view above (click a main stat), not duplicated here.
const catList = document.getElementById('an-cat-list');
const topCatsByXp = [...DATA.category_rollup].sort((a, b) => b.xp - a.xp);
topCatsByXp.forEach((c, i) => {
    const { whole } = splitOverall(c.average_level);
    const div = document.createElement('div');
    div.className = 'an-cap-item';
    div.innerHTML = `<span><span class="an-cap-rank">#${i + 1}</span>${c.category}<span class="lv">Ov ${whole}</span></span><span class="xp">${c.xp} xp</span>`;
    catList.appendChild(div);
});

// Top capabilities
const capList = document.getElementById('an-cap-list');
DATA.top_caps.forEach((c, i) => {
    const div = document.createElement('div');
    div.className = 'an-cap-item';
    div.innerHTML = `<span><span class="an-cap-rank">#${i + 1}</span>${c.name}<span class="lv">Lv ${c.level}</span></span><span class="xp">${c.xp} xp</span>`;
    capList.appendChild(div);
});

// Timeline
const tlEl = document.getElementById('an-timeline');
if (DATA.timeline.length) {
    DATA.timeline.forEach(item => {
        const meta = HUB_META[item.hub] || { icon: '•', label: item.hub };
        const date = new Date(item.occurred_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
        const div = document.createElement('div');
        div.className = 'an-tl-item';
        div.innerHTML = `
            <div class="an-tl-ic ${item.hub}">${meta.icon}</div>
            <div class="an-tl-body">
                <div class="an-tl-label">${item.label}</div>
                <div class="an-tl-meta"><span>${meta.label}</span> · <span>${date}</span> <span class="an-tl-xp">+${item.xp} xp</span></div>
            </div>
        `;
        tlEl.appendChild(div);
    });
} else {
    tlEl.innerHTML = '<p class="an-tl-empty">Nothing logged yet.</p>';
}

document.getElementById('an-note').innerHTML =
    `<b>Where these numbers come from:</b> stat, category and capability levels are read straight from learning_stats.json - the same file every other Operator page treats as the source of truth, so these always match what Fitness/Learning/Tasks show. The XP graph and Recent Activity feed instead come from the distribution receipts in operator_core/distribution/receipts/ - the audit trail of exactly when and where each XP award landed. ${coverage.full_coverage ? 'Every stat currently reconciles exactly to its real total.' : `${coverage.xp_total_reconciled - coverage.xp_covered} xp isn't reflected in that trail yet.`} Task Hub and Execution Hub don't generate receipts yet, so their card above and any of their completions won't show up in the graph or the feed until that's wired up the same way Fitness, Learning and Journal already are.`;
