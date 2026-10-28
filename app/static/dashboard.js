"use strict";

/* ------------------------------------------------------------------ config */
const body = document.body;
const ROTATION_MS = (parseInt(body.dataset.rotationSeconds, 10) || 15) * 1000;
const POLL_MS = Math.max(
    15000,
    ((parseInt(body.dataset.refreshIntervalSeconds, 10) || 600) * 1000) / 4
);

const sidebarOverview = document.getElementById("sidebar-overview");
const rightNav = document.getElementById("right-nav");
const mainEl = document.getElementById("main");
const refreshInfoEl = document.getElementById("refresh-info");
const clockEl = document.getElementById("clock");
const progressBar = document.getElementById("progress-bar");

let latest = null;
let viewIndex = 0;
let rotationTimer = null;
let progressTimer = null;

/* ------------------------------------------------------------------- views */
const VIEWS = [
    { id: "t1",        group: "Coherence",          title: "T1",                   mode: "qubit" },
    { id: "t2star",    group: "Coherence",          title: "T2*",                  mode: "qubit" },
    { id: "readout",   group: "Readout",            title: "Readout (g/e)",        mode: "qubit" },
    { id: "gef",       group: "Readout",            title: "GEF Readout (g/e/f)",  mode: "qubit" },
    { id: "rb1q",      group: "Single-Qubit Gates", title: "1Q RB Fidelity",       mode: "qubit" },
    { id: "rb2q",      group: "Two-Qubit Gates",    title: "2Q RB Fidelity",       mode: "pair"  },
    { id: "bell",      group: "Two-Qubit Gates",    title: "Bell State Fidelity",  mode: "pair"  },
];

/* --------------------------------------------------------------- utilities */
function fmtPct(f, digits) {
    if (f == null) return "\u2014";
    return (f * 100).toFixed(digits ?? 1) + "%";
}

function fmtNum(v, unit, digits) {
    if (v == null) return "\u2014";
    const n = typeof v === "number" ? v.toFixed(digits ?? 1) : v;
    return unit ? `${n} ${unit}` : `${n}`;
}

function fmtDateTime(iso) {
    if (!iso) return "\u2014";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
}

function metricValue(m) {
    if (m == null) return null;
    if (typeof m === "object") return m.value;
    return m;
}

function qualityColor(score) {
    if (score == null) return "#dcdfe8";
    const s = Math.max(0, Math.min(1, score));
    const bad  = [216, 122, 122];
    const mid  = [230, 183,  64];
    const good = [ 52, 184, 122];
    let a, b, t;
    if (s < 0.5) { a = bad; b = mid; t = s / 0.5; }
    else         { a = mid; b = good; t = (s - 0.5) / 0.5; }
    const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function fidelityScore(f, floor) {
    if (f == null) return null;
    return Math.max(0, (f - floor) / (1 - floor));
}

function rangeScore(v, min, max) {
    if (v == null) return null;
    if (max <= min) return 0.5;
    return Math.max(0, Math.min(1, (v - min) / (max - min)));
}

/* -------------------------------------------------------------- SVG helpers */
function svgEl(name, attrs) {
    const e = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
}

/* ----------------------------------------------------------- grid geometry */
const R_ACTIVE   = 24;
const R_INACTIVE = 11;
const SPACING    = 78;
const PAD        = 44;

function gridExtent(qubits) {
    let maxCol = 0, maxRow = 0;
    qubits.forEach(q => {
        if (q.grid) {
            maxCol = Math.max(maxCol, q.grid.col);
            maxRow = Math.max(maxRow, q.grid.row);
        }
    });
    return { cols: maxCol + 1, rows: maxRow + 1 };
}

function nodeCenter(grid, rows) {
    return {
        cx: PAD + grid.col * SPACING,
        cy: PAD + (rows - 1 - grid.row) * SPACING,
    };
}

/* ---------------------------------------------------------- build fixed grid */
function buildGrid(backend) {
    const qubits = backend.qubits;
    const pairs = backend.pairs;
    const { cols, rows } = gridExtent(qubits);
    const w = PAD * 2 + (cols - 1) * SPACING;
    const h = PAD * 2 + (rows - 1) * SPACING;

    const svg = svgEl("svg", {
        viewBox: `0 0 ${w} ${h}`,
        preserveAspectRatio: "xMidYMid meet",
        width: "100%",
        height: "100%",
    });

    const byId = {};
    qubits.forEach(q => { byId[q.id] = q; });

    // Draw pair edges (active only)
    const edgeEls = {};
    const edgeLabelEls = {};
    pairs.forEach(p => {
        if (!p.active) return;
        const c = byId[p.control];
        const t = byId[p.target];
        if (!c || !t || !c.grid || !t.grid) return;
        const a = nodeCenter(c.grid, rows);
        const b = nodeCenter(t.grid, rows);
        const line = svgEl("line", {
            x1: a.cx, y1: a.cy, x2: b.cx, y2: b.cy,
            class: "pair-edge",
            stroke: p.active ? "#111" : "#bbb",
            "stroke-width": p.active ? 2 : 1,
        });
        svg.appendChild(line);
        edgeEls[p.id] = line;

        // value label on edge (hidden initially)
        const mx = (a.cx + b.cx) / 2;
        const my = (a.cy + b.cy) / 2;
        const bg = svgEl("rect", {
            x: mx - 22, y: my - 8, width: 44, height: 16, rx: 4,
            fill: "rgba(255,255,255,0.85)", opacity: 0,
        });
        const lbl = svgEl("text", {
            x: mx, y: my, class: "edge-value", opacity: 0,
        });
        svg.appendChild(bg);
        svg.appendChild(lbl);
        edgeLabelEls[p.id] = { bg, lbl };
    });

    // Draw qubit circles
    const circleEls = {};
    const valueLabelEls = {};
    qubits.forEach(q => {
        if (!q.grid) return;
        const { cx, cy } = nodeCenter(q.grid, rows);
        const r = q.active ? R_ACTIVE : R_INACTIVE;
        const circle = svgEl("circle", {
            cx, cy, r,
            class: "q-circle",
            fill: q.active ? "#d4d8e4" : "#c0c4cc",
            stroke: q.active ? "#111" : "#999",
            "stroke-width": q.active ? 1.8 : 1,
        });
        svg.appendChild(circle);
        circleEls[q.id] = circle;

        if (q.active) {
            const lbl = svgEl("text", {
                x: cx, y: cy, class: "q-value", opacity: 0,
            });
            svg.appendChild(lbl);
            valueLabelEls[q.id] = lbl;
        }
    });

    return { svg, circleEls, valueLabelEls, edgeEls, edgeLabelEls, rows };
}

/* ---------------------------------------------------- metric accessor map */
function getQubitAccessor(viewId, backend) {
    const qubits = backend.qubits;
    switch (viewId) {
    case "t1": {
        const vals = qubits.map(q => q.t1_us).filter(v => v != null);
        const mx = Math.max(50, ...vals);
        return q => ({
            score: rangeScore(q.t1_us, 0, mx),
            label: q.t1_us != null ? `${q.t1_us.toFixed(0)}` : "",
        });
    }
    case "t2star": {
        const vals = qubits.map(q => q.t2star_us).filter(v => v != null);
        const mx = Math.max(50, ...vals);
        return q => ({
            score: rangeScore(q.t2star_us, 0, mx),
            label: q.t2star_us != null ? `${q.t2star_us.toFixed(0)}` : "",
        });
    }
    case "readout":
        return q => ({
            score: fidelityScore(q.readout_fidelity, 0.8),
            label: q.readout_fidelity != null ? fmtPct(q.readout_fidelity) : "",
        });
    case "gef":
        return q => ({
            score: fidelityScore(q.gef_readout_fidelity, 0.8),
            label: q.gef_readout_fidelity != null ? fmtPct(q.gef_readout_fidelity) : "",
        });
    case "rb1q": {
        return q => {
            const v = metricValue(q.rb_1q_fidelity);
            return {
                score: fidelityScore(v, 0.98),
                label: v != null ? fmtPct(v, 2) : "",
            };
        };
    }
    default:
        return () => ({ score: null, label: "" });
    }
}

function getPairAccessor(viewId) {
    switch (viewId) {
    case "rb2q":
        return p => {
            const v = metricValue(p.rb_2q_fidelity);
            return { score: fidelityScore(v, 0.9), label: v != null ? fmtPct(v) : "" };
        };
    case "bell":
        return p => {
            const v = metricValue(p.bell_fidelity);
            return { score: fidelityScore(v, 0.8), label: v != null ? fmtPct(v) : "" };
        };
    default:
        return () => ({ score: null, label: "" });
    }
}

/* -------------------------------------------------- legend label helpers */
function getLegendLabels(viewId, backend) {
    const qubits = backend.qubits;
    switch (viewId) {
    case "t1": {
        const vals = qubits.map(q => q.t1_us).filter(v => v != null);
        const mx = Math.max(50, ...vals);
        return { low: "0 \u00b5s", high: `${Math.round(mx)} \u00b5s` };
    }
    case "t2star": {
        const vals = qubits.map(q => q.t2star_us).filter(v => v != null);
        const mx = Math.max(50, ...vals);
        return { low: "0 \u00b5s", high: `${Math.round(mx)} \u00b5s` };
    }
    case "readout":
        return { low: "80%", high: "100%" };
    case "gef":
        return { low: "80%", high: "100%" };
    case "rb1q":
        return { low: "98%", high: "100%" };
    case "rb2q":
        return { low: "90%", high: "100%" };
    case "bell":
        return { low: "80%", high: "100%" };
    default:
        return { low: "", high: "" };
    }
}

/* ------------------------------------------------- update overlay on grid */
function updateGridOverlay(gridState, backend, view) {
    const { circleEls, valueLabelEls, edgeEls, edgeLabelEls } = gridState;
    const isPairView = view.mode === "pair";

    // Update qubit circles
    if (!isPairView) {
        const accessor = getQubitAccessor(view.id, backend);
        backend.qubits.forEach(q => {
            const circle = circleEls[q.id];
            if (!circle) return;
            if (!q.active) return;
            const { score, label } = accessor(q);
            circle.setAttribute("fill", qualityColor(score));
            const lbl = valueLabelEls[q.id];
            if (lbl) {
                lbl.textContent = label;
                lbl.setAttribute("opacity", label ? 1 : 0);
            }
        });
    } else {
        backend.qubits.forEach(q => {
            const circle = circleEls[q.id];
            if (!circle || !q.active) return;
            circle.setAttribute("fill", "#d4d8e4");
            const lbl = valueLabelEls[q.id];
            if (lbl) lbl.setAttribute("opacity", 0);
        });
    }

    // Update pair edges
    const pairAccessor = isPairView ? getPairAccessor(view.id) : null;
    backend.pairs.forEach(p => {
        const line = edgeEls[p.id];
        if (!line) return;
        const lblEls = edgeLabelEls[p.id];
        if (isPairView && p.active) {
            const { score, label } = pairAccessor(p);
            line.setAttribute("stroke", qualityColor(score));
            line.setAttribute("stroke-width", 5);
            if (lblEls) {
                lblEls.lbl.textContent = label;
                lblEls.lbl.setAttribute("opacity", label ? 1 : 0);
                lblEls.bg.setAttribute("opacity", label ? 1 : 0);
            }
        } else {
            line.setAttribute("stroke", p.active ? "#111" : "#bbb");
            line.setAttribute("stroke-width", p.active ? 2 : 1);
            if (lblEls) {
                lblEls.lbl.setAttribute("opacity", 0);
                lblEls.bg.setAttribute("opacity", 0);
            }
        }
    });
}

/* ----------------------------------------------------------- sidebar render */
function renderSidebar(backends) {
    const brandEl = document.getElementById("brand-name");
    if (brandEl && backends.length > 0) {
        brandEl.textContent = backends.map(b => b.backend).join(" / ") + " Chip State";
    }

    // Overview
    sidebarOverview.innerHTML = "";
    backends.forEach(b => {
        const section = el("div");

        const rows = [
            ["Active qubits", b.n_active_qubits],
            ["Active pairs", b.n_active_pairs],
            ["Last calibration", fmtDateTime(b.last_calibration)],
            ["Cluster", b.cluster_name || "\u2014"],
        ];
        rows.forEach(([label, val]) => {
            const row = el("div", "overview-row");
            row.appendChild(el("span", "label", label));
            row.appendChild(el("span", "val", String(val)));
            section.appendChild(row);
        });

        // Gate table
        if (b.native_gates && b.native_gates.length) {
            const gateDiv = el("div", "gate-list");
            gateDiv.appendChild(el("div", "gate-list-title", "Native Gates"));
            b.native_gates.forEach(g => {
                const row = el("div", "gate-row");
                row.appendChild(el("span", null, g.name));
                row.appendChild(el("span", "gate-time", fmtNum(g.length_ns, "ns", 0)));
                gateDiv.appendChild(row);
            });
            section.appendChild(gateDiv);
        }

        sidebarOverview.appendChild(section);
    });

    // Nav in RIGHT pane
    rightNav.innerHTML = "";
    let lastGroup = "";
    VIEWS.forEach((v, i) => {
        if (v.group !== lastGroup) {
            rightNav.appendChild(el("div", "nav-group-title", v.group));
            lastGroup = v.group;
        }
        const item = el("div", "nav-item" + (i === viewIndex ? " active" : ""));
        item.dataset.idx = i;
        item.appendChild(el("span", "nav-dot"));
        item.appendChild(el("span", null, v.title));
        item.addEventListener("click", () => {
            viewIndex = i;
            applyView();
            restartRotation();
        });
        rightNav.appendChild(item);
    });
}

function updateNavHighlight() {
    const items = rightNav.querySelectorAll(".nav-item");
    items.forEach((item, i) => {
        item.classList.toggle("active", i === viewIndex);
    });
}

/* -------------------------------------------------------------- grid state */
let gridStates = [];  // one per backend

function rebuildGrids() {
    if (!latest || !latest.backends || !latest.backends.length) return;
    mainEl.innerHTML = "";
    gridStates = [];

    // Wrap grid(s) + legend together so they stay centered as a unit
    const gridRow = el("div", "grid-row");

    latest.backends.forEach(backend => {
        const gs = buildGrid(backend);
        gridStates.push(gs);

        const container = el("div", "grid-container");
        const holder = el("div", "grid-svg-holder");
        holder.appendChild(gs.svg);
        container.appendChild(holder);
        gridRow.appendChild(container);
    });

    // Legend sits immediately to the right of the grid(s)
    const legendPanel = el("div", "legend-panel");

    const legendTitle = el("div", "legend-title");
    legendTitle.id = "legend-title";
    legendPanel.appendChild(legendTitle);

    const highLabel = el("div", "legend-label");
    highLabel.id = "legend-high";
    const lowLabel = el("div", "legend-label");
    lowLabel.id = "legend-low";
    legendPanel.appendChild(highLabel);
    legendPanel.appendChild(el("div", "legend-bar"));
    legendPanel.appendChild(lowLabel);

    gridRow.appendChild(legendPanel);
    mainEl.appendChild(gridRow);
}

/* -------------------------------------------------------------- apply view */
function applyView() {
    if (!latest || !latest.backends || !latest.backends.length) return;
    const view = VIEWS[viewIndex];

    latest.backends.forEach((backend, i) => {
        if (!gridStates[i]) return;
        updateGridOverlay(gridStates[i], backend, view);
    });

    // Update right-pane legend
    const legendTitle = document.getElementById("legend-title");
    if (legendTitle) legendTitle.textContent = view.title;

    const b0 = latest.backends[0];
    if (b0) {
        const labels = getLegendLabels(view.id, b0);
        const lowEl = document.getElementById("legend-low");
        const highEl = document.getElementById("legend-high");
        if (lowEl) lowEl.textContent = labels.low;
        if (highEl) highEl.textContent = labels.high;
    }

    updateNavHighlight();
}

function advanceView() {
    viewIndex = (viewIndex + 1) % VIEWS.length;
    applyView();
    restartProgress();
}

/* --------------------------------------------------------------- rotation */
function restartRotation() {
    if (rotationTimer) clearInterval(rotationTimer);
    rotationTimer = setInterval(advanceView, ROTATION_MS);
    restartProgress();
}

function restartProgress() {
    if (progressTimer) clearInterval(progressTimer);
    const start = Date.now();
    progressBar.style.width = "0%";
    progressTimer = setInterval(() => {
        const pct = Math.min(100, ((Date.now() - start) / ROTATION_MS) * 100);
        progressBar.style.width = pct + "%";
    }, 200);
}

/* ------------------------------------------------------------------- data */
async function poll() {
    try {
        const resp = await fetch("/api/data", { cache: "no-store" });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const prev = latest;
        latest = await resp.json();

        const backendsChanged = !prev
            || !prev.backends
            || prev.backends.length !== latest.backends.length
            || prev.last_refresh !== latest.last_refresh;

        if (backendsChanged) {
            rebuildGrids();
            renderSidebar(latest.backends);
        }
        applyView();
        updateRefreshInfo();
    } catch (e) {
        console.error("poll failed", e);
    }
}

function updateRefreshInfo() {
    if (!latest) return;
    const last = latest.last_refresh;
    refreshInfoEl.textContent = "Cloud sync: " + fmtDateTime(last);
    if (last) {
        const ageMin = (Date.now() - new Date(last).getTime()) / 60000;
        const interval = (latest.config?.refresh_interval_seconds || 600) / 60;
        refreshInfoEl.classList.toggle("stale", ageMin > interval * 2.5);
    }
}

function tickClock() {
    clockEl.textContent = new Date().toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
}

/* ------------------------------------------------------------------- init */
function init() {
    tickClock();
    setInterval(tickClock, 1000);
    poll();
    setInterval(poll, POLL_MS);
    restartRotation();
}

init();
