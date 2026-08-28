/* The Last Quiz — public rankings page.
 * Fetches /api/rankings (or the baked /rankings.json snapshot) and renders SVG
 * radar charts plus plain-English explanations of each test. Styled to match
 * the main app (warm palette, shared design tokens via /static/styles.css).
 *
 * Loaded as an ES module so it can share the app's curated model groups
 * (model-groups.js) — the same "Humanity's Last Exam", "Frontier", etc. sets
 * the admin uses — to let visitors filter a large field down to a curated
 * subset instead of rendering every benchmarked model at once. */
import { buildModelGroups } from "./model-groups.js";
import { providerLogoImg, providerLogoHtml, providerLogoUrl, familyLabel, brandHeadHtml } from "./model-logo.js";
import { attachRichTooltip, escapeHtml, formatReleased } from "./rich-tooltip.js";

// On-brand palette that reads well on the app's cream panels.
const PALETTE = [
  "#da5f35", "#0f5c78", "#b5179e", "#2a9d8f", "#e09f3e",
  "#6d597a", "#386641", "#9e2a2b", "#3a7ca5", "#8a5a44",
];

// Approximate general-population averages, normalized to the 0-100 scale the
// radars use ((mean - 1) / 4 * 100 for a 1-5 item scale), shown as a dashed
// "Human average" baseline. Especially important for the Dark Triad, where a
// raw model score is meaningless without a human reference point.
const POPULATION_NORMS = {
  sd3_short_dark_triad: {
    label: "Human average (typical adult)",
    source: "general-population means (N=1,518), Kaufman et al. 2019 (SD-3)",
    note:
      "For scale, the dashed line is the typical-adult average: about 46/100 on " +
      "Machiavellianism, 38/100 on Narcissism and 29/100 on Psychopathy (every score " +
      "here is normalised to 0-100). A model well above the line is unusually dark; " +
      "below it is unusually benign.",
    values: { MACH: 46, NARC: 38, PSYCH: 29 },
  },
};

// Decoder for the four-letter Jungian/MBTI-style type codes, so each model's
// result (e.g. INTJ) can be spelled out in plain English rather than left as
// opaque letters.
const MBTI_LETTERS = {
  E: "Extraversion", I: "Introversion",
  S: "Sensing", N: "Intuition",
  T: "Thinking", F: "Feeling",
  J: "Judging", P: "Perceiving",
};

const SVGNS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, children = []) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  for (const c of children) node.appendChild(c);
  return node;
}

function polarToXY(cx, cy, radius, angle) {
  return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
}

/* Draw a radar chart. axes: [label,...]; series: [{name,color,values:[0..100]}]. */
function drawRadar(axes, series) {
  const width = 460;
  const height = 360;
  const cx = width / 2;
  const cy = height / 2;
  const R = 104;
  const rings = 4;
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  const n = axes.length;
  const angleFor = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;

  for (let r = 1; r <= rings; r++) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const [x, y] = polarToXY(cx, cy, (R * r) / rings, angleFor(i));
      pts.push(`${x},${y}`);
    }
    svg.appendChild(el("polygon", { class: "ring", points: pts.join(" ") }));
  }

  for (let i = 0; i < n; i++) {
    const [x, y] = polarToXY(cx, cy, R, angleFor(i));
    svg.appendChild(el("line", { class: "spoke", x1: cx, y1: cy, x2: x, y2: y }));
    const [lx, ly] = polarToXY(cx, cy, R + 16, angleFor(i));
    const anchor = Math.abs(lx - cx) < 6 ? "middle" : lx > cx ? "start" : "end";
    const label = el("text", { class: "axis-label", x: lx, y: ly + 3, "text-anchor": anchor });
    label.textContent = axes[i];
    svg.appendChild(label);
  }

  series.forEach((s, si) => {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const v = Math.max(0, Math.min(100, s.values[i] ?? 0));
      const [x, y] = polarToXY(cx, cy, (R * v) / 100, angleFor(i));
      pts.push(`${x},${y}`);
    }
    const attrs = {
      class: s.baseline ? "series baseline" : "series", "data-series": si,
      points: pts.join(" "), fill: s.color, "fill-opacity": s.baseline ? "0.06" : "0.16",
      stroke: s.color, "stroke-width": "2", "stroke-linejoin": "round",
    };
    if (s.dash) attrs["stroke-dasharray"] = "5 4";
    const poly = el("polygon", attrs);
    if (s.title) {
      const t = el("title");
      t.textContent = s.title;
      poly.appendChild(t);
    }
    svg.appendChild(poly);
  });
  return svg;
}

function card(title, tag, bodyNodes) {
  const c = document.createElement("div");
  c.className = "card";
  const h = document.createElement("h2");
  h.textContent = title;
  const t = document.createElement("div");
  t.className = "tag";
  t.textContent = tag;
  c.appendChild(h);
  c.appendChild(t);
  for (const b of bodyNodes) c.appendChild(b);
  return c;
}

/* Spell out the four-letter type each model got (e.g. INTJ -> Introversion,
   Intuition, Thinking, Judging) so the per-model result is clear on its own,
   separate from the general test explanation lower down the page. */
function buildTypeBreakdown(series) {
  const wrap = document.createElement("div");
  wrap.className = "typebreak";
  const head = document.createElement("div");
  head.className = "typebreak-h";
  head.textContent = "What each model's type means";
  wrap.appendChild(head);
  for (const s of series) {
    if (s.baseline || !s.result) continue;
    const decoded = [...s.result].map((l) => MBTI_LETTERS[l]).filter(Boolean).join(" · ");
    const row = document.createElement("div");
    row.className = "typebreak-row";
    const model = document.createElement("span");
    model.className = "tb-model";
    model.textContent = s.name;
    const code = document.createElement("b");
    code.className = "tb-code";
    code.textContent = s.result;
    const words = document.createElement("span");
    words.className = "tb-words";
    words.textContent = decoded;
    row.appendChild(model);
    row.appendChild(code);
    row.appendChild(words);
    wrap.appendChild(row);
  }
  return wrap;
}

/* Per-chart legend: one model per line, colour swatch + one-glance result,
   hover-linked to the matching shape on the radar. */
function buildChartLegend(series) {
  const ul = document.createElement("ul");
  ul.className = "rk-clegend";
  series.forEach((s, si) => {
    const li = document.createElement("li");
    li.dataset.series = String(si);
    if (s.baseline) li.classList.add("baseline");
    if (s.title) li.title = s.title;
    const sw = document.createElement("span");
    sw.className = "sw";
    sw.style.background = s.color;
    const nm = document.createElement("span");
    nm.className = "nm";
    nm.textContent = s.name;
    li.appendChild(sw);
    const legendLogo = providerLogoImg(s.name, 15);
    if (legendLogo) li.appendChild(legendLogo);
    li.appendChild(nm);
    if (s.result) {
      const res = document.createElement("span");
      res.className = "res";
      res.textContent = s.result;
      li.appendChild(res);
    }
    ul.appendChild(li);
  });
  return ul;
}

/* Hover a shape or a legend row to highlight that model across the chart. */
function wireHighlight(cardEl) {
  const polys = [...cardEl.querySelectorAll("polygon.series")];
  const rows = [...cardEl.querySelectorAll("li[data-series]")];
  const apply = (idx) => {
    for (const p of polys) {
      const me = Number(p.dataset.series);
      const isBaseline = p.classList.contains("baseline");
      const baseFill = isBaseline ? "0.06" : "0.16";
      if (me === idx) {
        p.setAttribute("fill-opacity", isBaseline ? "0.18" : "0.34");
        p.setAttribute("stroke-opacity", "1");
        p.setAttribute("stroke-width", "3");
      } else if (idx == null || isBaseline) {
        // Keep the human-average reference visible even while dimming others.
        p.setAttribute("fill-opacity", baseFill);
        p.setAttribute("stroke-opacity", isBaseline ? "0.8" : "1");
        p.setAttribute("stroke-width", "2");
      } else {
        p.setAttribute("fill-opacity", "0.04");
        p.setAttribute("stroke-opacity", "0.22");
        p.setAttribute("stroke-width", "2");
      }
    }
    for (const r of rows) {
      r.classList.toggle("active", idx != null && Number(r.dataset.series) === idx);
    }
  };
  for (const p of polys) {
    p.addEventListener("mouseenter", () => apply(Number(p.dataset.series)));
    p.addEventListener("mouseleave", () => apply(null));
  }
  for (const r of rows) {
    r.addEventListener("mouseenter", () => apply(Number(r.dataset.series)));
    r.addEventListener("mouseleave", () => apply(null));
  }
}

/* Radar series for a benchmark: values, a hover tooltip that spells out every
   dimension (so a code like INTJ is explained), and a one-glance result. */
function seriesForBench(bench, colorFor) {
  const dims = bench.dimensions;
  return bench.models.map((m) => {
    const parts = dims.map((d) => {
      const v = Math.round(m.profile[d.id] ?? 0);
      if (d.poles) return `${d.name}: ${v >= 50 ? d.poles.high : d.poles.low} (${v})`;
      return `${d.name} ${v}`;
    });
    let result = m.type_code || "";
    if (!result) {
      let best = dims[0];
      let bestV = -Infinity;
      for (const d of dims) {
        const v = m.profile[d.id] ?? 0;
        if (v > bestV) { bestV = v; best = d; }
      }
      result = best ? `${best.name} ${Math.round(bestV)}` : "";
    }
    return {
      name: m.model_id,
      color: colorFor(m.model_id),
      values: dims.map((d) => m.profile[d.id] ?? 0),
      result,
      title: `${m.model_id} — ${parts.join(" · ")}`,
    };
  });
}

/* A dashed grey "Human average" baseline from published population norms. */
function buildNormSeries(bench, norm) {
  const parts = bench.dimensions.map((d) => `${d.name} ${Math.round(norm.values[d.id] ?? 0)}`);
  return {
    name: norm.label,
    color: "#8a8a8a",
    baseline: true,
    dash: true,
    result: "reference",
    values: bench.dimensions.map((d) => norm.values[d.id] ?? 0),
    title: `${norm.label} — ${norm.source} — ${parts.join(" · ")}`,
  };
}

function benchmarkCard(bench, colorFor) {
  const axes = bench.dimensions.map((d) => (d.poles ? `${d.poles.low}\u2013${d.poles.high}` : d.name));
  const series = seriesForBench(bench, colorFor);
  const norm = POPULATION_NORMS[bench.id];
  if (norm) series.unshift(buildNormSeries(bench, norm));
  const body = [drawRadar(axes, series), buildChartLegend(series)];
  // Type tests (four-letter codes) get an explicit, decoded breakdown so the
  // result each model gets is spelled out, distinct from the general glossary.
  if (bench.dimensions.some((d) => d.poles)) body.push(buildTypeBreakdown(series));
  const c = card(
    bench.title,
    `${bench.dimensions.length} dimensions · v${bench.version}`,
    body,
  );
  wireHighlight(c);
  return c;
}

/* One benchmark's plain-English explanation card (used under every view). */
function explanationCard(b) {
  const c = document.createElement("div");
  c.className = "card";
  const isType = b.kind === "bipolar";
  const kind = isType ? "Type test" : "Trait test";
  const readNote = isType
    ? "How to read it: each model leans to one side of every axis, and the four sides combine into a four-letter type (e.g. INTJ). Each model's own type is spelled out on its chart above."
    : "How to read it: each trait is scored 0\u2013100 on its own \u2014 there's no single label or code, just a profile across the dimensions.";
  let html =
    `<h2>${b.title}</h2>` +
    `<div class="tag">${kind}${b.question_count ? " \u00b7 " + b.question_count + " items" : ""}</div>` +
    (b.about ? `<p>${b.about}</p>` : "") +
    `<p class="read-note">${readNote}</p>` +
    (POPULATION_NORMS[b.id] ? `<p class="norm-note">${POPULATION_NORMS[b.id].note}</p>` : "");
  if (b.dimensions && b.dimensions.length) {
    html += '<div class="gloss">';
    for (const d of b.dimensions) {
      const term = d.poles ? `${d.name} (${d.poles.high}/${d.poles.low})` : d.name;
      html += `<div class="row"><span class="term">${term}</span>` +
        (d.description ? ` \u2014 <span class="desc">${d.description}</span>` : "") + "</div>";
    }
    html += "</div>";
  }
  if (b.reference && b.reference.url) {
    const title = (b.reference.publication || "Reference").replace(/"/g, "&quot;");
    html += `<a class="ref" href="${b.reference.url}" target="_blank" rel="noopener" title="${title}">Official reference \u2197</a>`;
  }
  c.innerHTML = html;
  return c;
}

/* ------------------------- Dark Triad (home) view ------------------------- */
const SD3_ID = "sd3_short_dark_triad";
const SD3_TRAITS = [
  { id: "MACH", name: "Machiavellianism", blurb: "strategic manipulation", color: "#6a4c93" },
  { id: "NARC", name: "Narcissism", blurb: "grandiosity & entitlement", color: "#b5179e" },
  { id: "PSYCH", name: "Psychopathy", blurb: "callousness, low empathy", color: "#9e2a2b" },
];
function shortName(id) { return id.split("/").pop() || id; }

// Rich hover/tap/focus tooltip content for a Dark Triad model point: name +
// id, release date, and every trait score (the current trait, if any,
// highlighted) so a suppressed/de-cluttered label is still fully discoverable.
function darkTriadTooltipHtml(m, highlightTraitId) {
  const rows = SD3_TRAITS.map((t) => {
    const val = Math.round(m.profile[t.id] ?? 0);
    const hi = t.id === highlightTraitId ? " rq-hi" : "";
    return `<div class="rq-row${hi}"><span class="rq-k">${escapeHtml(t.name)}</span><span class="rq-v">${val}</span></div>`;
  }).join("");
  return (
    `<div class="rq-head">${brandHeadHtml(m.model_id)}<div class="rq-headtext">` +
    `<div class="rq-name">${escapeHtml(familyLabel(m.model_id))}</div>` +
    `<div class="rq-id">${escapeHtml(m.model_id)}</div></div></div>` +
    `<div class="rq-date">${escapeHtml(formatReleased(m.released))}</div>` +
    `<div class="rq-rows">${rows}</div>`
  );
}

// Light -> dark colour ramp (teal = restrained, red = dark), shared across the
// Dark Triad charts so colour reinforces the score everywhere.
const DARK_STOPS = [[0, [42, 157, 143]], [30, [138, 177, 125]], [55, [233, 196, 106]], [74, [224, 159, 62]], [100, [158, 42, 43]]];
function darkColor(v) {
  v = Math.max(0, Math.min(100, v));
  for (let i = 1; i < DARK_STOPS.length; i++) {
    const [p1, c1] = DARK_STOPS[i - 1], [p2, c2] = DARK_STOPS[i];
    if (v <= p2) {
      const t = (v - p1) / (p2 - p1 || 1);
      const m = c1.map((x, j) => Math.round(x + (c2[j] - x) * t));
      return `rgb(${m[0]},${m[1]},${m[2]})`;
    }
  }
  const last = DARK_STOPS[DARK_STOPS.length - 1][1];
  return `rgb(${last[0]},${last[1]},${last[2]})`;
}

/* Three per-trait leaderboards: most restrained on top, the human ranked in. */
function darkTriadLeaderboard(sd3, human) {
  const wrap = document.createElement("div");
  wrap.className = "dt-lanes";
  for (const t of SD3_TRAITS) {
    const lane = document.createElement("div");
    lane.className = "dt-lane";
    const humanVal = human[t.id] ?? 0;
    lane.innerHTML = `<h3>${t.name}</h3><p class="sub">${t.blurb} \u00b7 human avg ${Math.round(humanVal)}</p>`;
    const entries = [
      ...sd3.models.map((m) => ({ id: m.model_id, name: shortName(m.model_id), v: m.profile[t.id] ?? 0 })),
      { name: "Typical adult (human)", v: humanVal, human: true },
    ].sort((a, b) => a.v - b.v);
    const rankedModels = entries.filter((e) => !e.human);
    if (rankedModels.length) { rankedModels[0].saint = true; rankedModels[rankedModels.length - 1].devil = true; }
    let rank = 0;
    for (const e of entries) {
      if (!e.human) rank++;
      const above = !e.human && e.v > humanVal;
      const row = document.createElement("div");
      row.className = "dt-row" + (above ? " above" : "") + (e.human ? " humanrow" : "");
      const w = Math.max(0, Math.min(100, e.v));
      const icon = e.human ? "\uD83E\uDDD1" : e.saint ? "\uD83D\uDE07" : e.devil ? "\uD83D\uDE08" : String(rank);
      row.innerHTML =
        `<div class="rank">${icon}</div>` +
        `<div><div class="who"><span class="mname">${providerLogoHtml(e.id, 16)}${e.name}</span>` +
        `<span class="val">${Math.round(e.v)}${above ? ' <span class="up">darker</span>' : ""}</span></div>` +
        `<div class="dt-track"><div class="zone" style="left:${humanVal}%"></div>` +
        `<div class="bar${e.human ? " humbar" : ""}" style="width:${w}%;${e.human ? "" : "background:" + darkColor(e.v)}"></div>` +
        `</div></div>`;
      lane.appendChild(row);
    }
    wrap.appendChild(lane);
  }
  return wrap;
}

/* Stacked HLE-style time charts (release date vs score); axis flipped so up = restrained. */
function darkTriadTimeline(sd3, human, colorFor) {
  const NS = "http://www.w3.org/2000/svg";
  const wrap = document.createElement("div");
  wrap.className = "dt-time";
  const dated = sd3.models.filter((m) => m.released);
  if (dated.length < 2) {
    const note = document.createElement("p");
    note.className = "dt-note";
    note.textContent = "Release-date trends appear here once at least two models have a recorded release date (captured automatically on each run).";
    wrap.appendChild(note);
    return wrap;
  }
  const ms = (s) => Date.parse(s + "T00:00:00Z");
  const times = dated.map((m) => ms(m.released));
  const tMin = Math.min(...times) - 30 * 864e5;
  const tMax = Math.max(...times) + 30 * 864e5;
  const allVals = [];
  for (const t of SD3_TRAITS) { for (const m of sd3.models) allVals.push(m.profile[t.id] ?? 0); allVals.push(human[t.id] ?? 0); }
  const yMax = Math.min(100, Math.max(20, Math.ceil((Math.max(...allVals) + 8) / 10) * 10));
  const mk = (tag, attrs = {}, txt) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (txt != null) n.textContent = txt; return n; };
  const yearMarks = () => {
    const marks = [];
    for (let y = new Date(tMin).getUTCFullYear(); y <= new Date(tMax).getUTCFullYear(); y++) marks.push([Date.UTC(y, 0, 1), String(y)]);
    return marks;
  };
  for (const t of SD3_TRAITS) {
    const W = 900, H = 210, padL = 42, padR = 16, padT = 22, padB = 26;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const xFor = (v) => padL + ((v - tMin) / (tMax - tMin)) * plotW;
    const yFor = (v) => padT + (v / yMax) * plotH; // flipped: low (restrained) at top
    const svg = mk("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": t.name + " over time" });
    svg.appendChild(mk("text", { x: padL, y: 14, fill: "var(--ink)", "font-size": 13, "font-weight": 600 }, t.name));
    const humanVal = human[t.id] ?? 0;
    const humY = yFor(humanVal);
    const gradId = "ldgrad-" + t.id;
    const defs = mk("defs");
    const grad = mk("linearGradient", { id: gradId, x1: "0", y1: "0", x2: "0", y2: "1" });
    grad.appendChild(mk("stop", { offset: "0%", "stop-color": "#2a9d8f", "stop-opacity": "0.16" }));
    grad.appendChild(mk("stop", { offset: "55%", "stop-color": "#e9c46a", "stop-opacity": "0.13" }));
    grad.appendChild(mk("stop", { offset: "100%", "stop-color": "#9e2a2b", "stop-opacity": "0.18" }));
    defs.appendChild(grad);
    svg.appendChild(defs);
    svg.appendChild(mk("rect", { x: padL, y: padT, width: plotW, height: plotH, fill: `url(#${gradId})` }));
    for (const v of [0, 20, 40, 60, 80].filter((x) => x <= yMax)) {
      const y = yFor(v);
      svg.appendChild(mk("line", { x1: padL, y1: y, x2: W - padR, y2: y, stroke: "#eee2d3", "stroke-width": 1 }));
      svg.appendChild(mk("text", { x: padL - 6, y: y + 3, fill: "var(--muted)", "font-size": 9, "text-anchor": "end" }, v));
    }
    svg.appendChild(mk("text", { x: 2, y: padT + 4, fill: "var(--accent-2)", "font-size": 8.5, "font-weight": 600 }, "calm"));
    svg.appendChild(mk("text", { x: 2, y: padT + plotH, fill: "#9e2a2b", "font-size": 8.5, "font-weight": 600 }, "darkest"));
    for (const [tt, lab] of yearMarks()) {
      if (tt < tMin || tt > tMax) continue;
      const x = xFor(tt);
      svg.appendChild(mk("line", { x1: x, y1: padT, x2: x, y2: padT + plotH, stroke: "#efe6da", "stroke-width": 1 }));
      svg.appendChild(mk("text", { x, y: H - padB + 16, fill: "var(--muted)", "font-size": 9, "text-anchor": "middle" }, lab));
    }
    svg.appendChild(mk("line", { x1: padL, y1: humY, x2: W - padR, y2: humY, stroke: "var(--ink)", "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
    svg.appendChild(mk("text", { x: W - padR, y: humY - 4, fill: "var(--ink)", "font-size": 9, "font-weight": 600, "text-anchor": "end" }, "human average (" + Math.round(humanVal) + ")"));
    const pts = dated.map((m) => ({ x: ms(m.released), y: m.profile[t.id] ?? 0 }));
    const n = pts.length, sx = pts.reduce((a, p) => a + p.x, 0), sy = pts.reduce((a, p) => a + p.y, 0);
    const sxx = pts.reduce((a, p) => a + p.x * p.x, 0), sxy = pts.reduce((a, p) => a + p.x * p.y, 0);
    const denom = n * sxx - sx * sx;
    if (denom !== 0) {
      const slope = (n * sxy - sx * sy) / denom, intc = (sy - slope * sx) / n;
      const ln = (xr) => intc + slope * xr;
      svg.appendChild(mk("line", { x1: xFor(tMin), y1: yFor(ln(tMin)), x2: xFor(tMax), y2: yFor(ln(tMax)), stroke: "var(--muted)", "stroke-width": 1.5, "stroke-dasharray": "3 4", opacity: 0.65 }));
    }
    const byScore = [...dated].sort((a, b) => (a.profile[t.id] ?? 0) - (b.profile[t.id] ?? 0));
    const saintId = byScore[0].model_id, devilId = byScore[byScore.length - 1].model_id;
    // De-collision pass (HLE-style): every point keeps its logo + hover, but we
    // only draw a text label where it won't overlap one already placed. The
    // saint/devil extremes and the latest release always keep their label; the
    // rest are placed greedily by score so the darker (more interesting) ones win.
    const latestT = Math.max(...dated.map((m) => ms(m.released)));
    const hit = (a, b) => a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1;
    const cand = dated.map((m) => {
      const cx = xFor(ms(m.released)), cy = yFor(m.profile[t.id] ?? 0);
      const rightEdge = cx > W - 130;
      const w = familyLabel(m.model_id).length * 5.6 + 4;
      const x1 = rightEdge ? cx - 11 - w : cx + 11;
      const prio = (m.model_id === saintId || m.model_id === devilId) ? 2 : (ms(m.released) === latestT ? 1 : 0);
      return { id: m.model_id, box: { x1, x2: x1 + w, y1: cy - 6.5, y2: cy + 6.5 }, prio, score: m.profile[t.id] ?? 0 };
    });
    cand.sort((a, b) => b.prio - a.prio || b.score - a.score);
    // Seed with the "human average" label box so model names never sit on top of it.
    const humLabel = "human average (" + Math.round(humanVal) + ")";
    const placedBoxes = [{ x1: (W - padR) - humLabel.length * 5.6, x2: W - padR, y1: humY - 13, y2: humY - 1 }];
    const labelShow = new Set();
    for (const c of cand) {
      if (c.prio >= 2 || !placedBoxes.some((p) => hit(c.box, p))) { placedBoxes.push(c.box); labelShow.add(c.id); }
    }
    for (const m of dated) {
      const cx = xFor(ms(m.released)), cy = yFor(m.profile[t.id] ?? 0);
      const rightEdge = cx > W - 130;
      const g = mk("g", { style: "cursor: pointer;" });
      const badge = m.model_id === saintId ? "\uD83D\uDE07" : m.model_id === devilId ? "\uD83D\uDE08" : null;
      const tlLogo = providerLogoUrl(m.model_id);
      // Invisible, larger hit target so the tooltip is easy to hover/tap.
      g.appendChild(mk("circle", { cx, cy, r: 11, fill: "transparent" }));
      if (badge) {
        g.appendChild(mk("text", { x: cx, y: cy, "font-size": 17, "text-anchor": "middle", "dominant-baseline": "central" }, badge));
      } else if (tlLogo) {
        g.appendChild(mk("image", { href: tlLogo, x: cx - 8, y: cy - 8, width: 16, height: 16 }));
      } else {
        g.appendChild(mk("circle", { cx, cy, r: 6, fill: colorFor(m.model_id), "fill-opacity": 0.92, stroke: "#fff", "stroke-width": 1.5 }));
      }
      if (labelShow.has(m.model_id)) {
        svg.appendChild(mk("text", { x: rightEdge ? cx - 11 : cx + 11, y: cy + 3.2, fill: "var(--ink)", "font-size": 9.5, "text-anchor": rightEdge ? "end" : "start" }, familyLabel(m.model_id)));
      }
      g.setAttribute("aria-label", `${familyLabel(m.model_id)}, ${t.name}: ${Math.round(m.profile[t.id] ?? 0)}, released ${m.released}`);
      attachRichTooltip(g, () => darkTriadTooltipHtml(m, t.id));
      svg.appendChild(g);
    }
    wrap.appendChild(svg);
  }
  return wrap;
}

/* Combined "Dark Index" leaderboard: the mean of the three traits (the Dark
   Triad total), with the typical adult ranked in. Least dark on top. */
function darkIndexLeaderboard(sd3, human) {
  const wrap = document.createElement("div");
  wrap.className = "dt-index";
  const idxOf = (profile) => SD3_TRAITS.reduce((s, t) => s + (profile[t.id] ?? 0), 0) / SD3_TRAITS.length;
  const humanIdx = idxOf(human);
  const entries = [
    ...sd3.models.map((m) => ({ id: m.model_id, name: shortName(m.model_id), v: idxOf(m.profile) })),
    { name: "Typical adult (human)", v: humanIdx, human: true },
  ].sort((a, b) => a.v - b.v);
  const rankedModels = entries.filter((e) => !e.human);
  if (rankedModels.length) { rankedModels[0].saint = true; rankedModels[rankedModels.length - 1].devil = true; }
  let rank = 0;
  for (const e of entries) {
    if (!e.human) rank++;
    const above = !e.human && e.v > humanIdx;
    const row = document.createElement("div");
    row.className = "dt-row" + (above ? " above" : "") + (e.human ? " humanrow" : "");
    const w = Math.max(0, Math.min(100, e.v));
    const icon = e.human ? "\uD83E\uDDD1" : e.saint ? "\uD83D\uDE07" : e.devil ? "\uD83D\uDE08" : String(rank);
    row.innerHTML =
      `<div class="rank">${icon}</div>` +
      `<div><div class="who"><span class="mname">${providerLogoHtml(e.id, 16)}${e.name}</span>` +
      `<span class="val">${Math.round(e.v)}${above ? ' <span class="up">darker</span>' : ""}</span></div>` +
      `<div class="dt-track"><div class="zone" style="left:${humanIdx}%"></div>` +
      `<div class="bar${e.human ? " humbar" : ""}" style="width:${w}%;${e.human ? "" : "background:" + darkColor(e.v)}"></div>` +
      `</div></div>`;
    wrap.appendChild(row);
  }
  return wrap;
}

/* Mobile Dark Triad scale: a vertical spectrum listing every model on its own
   row, saint (top) to villain (bottom), so all models stay legible instead of
   crowding one narrow axis. The average-human line is spliced in at the
   crossover; dots reuse .ld-dot[data-idx]/.ld-pin so the shared tooltip wiring
   in lightDarkScale() applies unchanged. */
function verticalScaleHtml(models, humanIdx, caption) {
  const row = (m, i) =>
    `<div class="ld-dot${m.v > humanIdx ? " dark" : ""}" data-idx="${i}" tabindex="0" role="button">` +
      `<span class="ld-pin">${providerLogoHtml(m.id, 14)}</span>` +
      `<span class="ld-vname">${familyLabel(m.id)}</span>` +
      `<span class="ld-vval">${Math.round(m.v)}</span>` +
    `</div>`;
  const humanRow =
    `<div class="ld-human" tabindex="0" role="button" aria-label="Average human, shown for scale">` +
      `<span class="ld-vhuman-line"></span>` +
      `<span class="ld-vhuman-lab">\uD83E\uDDD1 avg human \u00b7 ${Math.round(humanIdx)}</span>` +
    `</div>`;
  let body = "", inserted = false;
  for (let i = 0; i < models.length; i++) {
    if (!inserted && models[i].v > humanIdx) { body += humanRow; inserted = true; }
    body += row(models[i], i);
  }
  if (!inserted) body += humanRow;
  return `<div class="ld-vert">` +
    `<span class="ld-vspine" aria-hidden="true"></span>` +
    `<div class="ld-vend"><span class="ld-vface">\uD83D\uDE07</span><b>saint</b></div>` +
    body +
    `<div class="ld-vend"><span class="ld-vface">\uD83D\uDE08</span><b>villain</b></div>` +
  `</div>` +
  `<p class="ld-foot">Dark Index \u00b7 0\u2013100 \u00b7 lower = more restrained</p>` +
  `<p class="ld-cap">${caption}</p>`;
}

/* Angel–devil scale: every model on one light→dark continuum by its Dark Index,
   with the average human marked. The at-a-glance, lighten-the-mood hero. */
function lightDarkScale(sd3, human) {
  const idxOf = (p) => SD3_TRAITS.reduce((s, t) => s + (p[t.id] ?? 0), 0) / SD3_TRAITS.length;
  const humanIdx = idxOf(human);
  const models = sd3.models
    .map((m) => ({ id: m.model_id, name: shortName(m.model_id), v: idxOf(m.profile), profile: m.profile, released: m.released }))
    .sort((a, b) => a.v - b.v);
  // Per-trait breakdown rows (Machiavellianism / Narcissism / Psychopathy),
  // shared by the model-dot and average-human tooltips.
  const traitRowsFor = (p) => SD3_TRAITS
    .map((t) => `<div class="rq-row"><span class="rq-k">${escapeHtml(t.name)}</span><span class="rq-v">~${Math.round(p[t.id] ?? 0)}/100</span></div>`)
    .join("");
  // Window the 0-100 Dark Index onto just the region the data occupies (with
  // padding) so points spread across the width and sit roughly centred, rather
  // than bunching against an empty 0 or 100 end. The visible window is noted as
  // a footnote under the axis so the scale stays honest.
  const vals = [humanIdx, ...models.map((m) => m.v)];
  const lo = Math.min(...vals), hi = Math.max(...vals);
  // Small fixed padding (not proportional to the range): a proportional pad
  // blows the window back out toward 0-100 whenever the spread is already wide.
  const pad = 5;
  const domainMin = Math.max(0, Math.floor((lo - pad) / 5) * 5);
  const domainMax = Math.min(100, Math.ceil((hi + pad) / 5) * 5);
  const span = domainMax - domainMin || 1;
  const clamp = (v) => Math.max(1.5, Math.min(98.5, ((v - domainMin) / span) * 100));
  const markers = models
    .map((m, i) => `<div class="ld-dot" data-idx="${i}" style="left:${clamp(m.v)}%">` +
      `<span class="ld-pin">${providerLogoHtml(m.id, 13)}</span><span class="ld-lab r${i % 3}">${familyLabel(m.id)}</span></div>`)
    .join("");
  const caption =
    "Each model sits on one restrained-to-villainous scale, with the average human marked. " +
    "Where would you want your AI to land?";
  const isVert = window.matchMedia("(max-width: 640px)").matches;
  const wrap = document.createElement("div");
  wrap.className = "ld";
  wrap.innerHTML = isVert
    ? verticalScaleHtml(models, humanIdx, caption)
    : `<div class="ld-row">` +
      `<div class="ld-face">\uD83D\uDE07<b>saint</b></div>` +
      `<div class="ld-track">` +
        `<div class="ld-human" style="left:${clamp(humanIdx)}%" tabindex="0" role="button" aria-label="Average human, shown for scale">` +
          `<span class="ld-human-lab">\uD83E\uDDD1 avg human</span>` +
        `</div>${markers}` +
        `<span class="ld-end ld-end-lo">${domainMin}</span><span class="ld-end ld-end-hi">${domainMax}</span>` +
      `</div>` +
      `<div class="ld-face">\uD83D\uDE08<b>villain</b></div>` +
      `</div>` +
      `<p class="ld-foot">Dark Index \u00b7 0\u2013100 scale (showing ${domainMin}\u2013${domainMax})</p>` +
      `<p class="ld-cap">${caption}</p>`;
  const humanEl = wrap.querySelector(".ld-human");
  if (humanEl) {
    attachRichTooltip(humanEl, () => (
      `<div class="rq-name">Average human</div>` +
      `<div class="rq-date">The typical adult, shown for scale.</div>` +
      `<div class="rq-rows"><div class="rq-row rq-hi"><span class="rq-k">Dark Index</span><span class="rq-v">~${Math.round(humanIdx)} / 100</span></div>${traitRowsFor(human)}</div>` +
      `<div class="rq-date" style="margin-top:6px">Population norms (Kaufman et al. 2019, SD-3). Models toward \uD83D\uDE07 are more restrained than the average person; toward \uD83D\uDE08, darker.</div>`
    ));
  }
  wrap.querySelectorAll(".ld-dot").forEach((dot) => {
    const m = models[Number(dot.dataset.idx)];
    dot.setAttribute("aria-label", `${m.name}: ${Math.round(m.v)}/100 dark index`);
    attachRichTooltip(dot, () => (
      `<div class="rq-head">${brandHeadHtml(m.id)}<div class="rq-headtext">` +
      `<div class="rq-name">${escapeHtml(familyLabel(m.id))}</div>` +
      `<div class="rq-id">${escapeHtml(m.id)}</div></div></div>` +
      `<div class="rq-date">${escapeHtml(formatReleased(m.released))}</div>` +
      `<div class="rq-rows"><div class="rq-row rq-hi"><span class="rq-k">Dark Index</span><span class="rq-v">${Math.round(m.v)} / 100</span></div>${traitRowsFor(m.profile)}</div>`
    ));
  });
  // Desktop only: hide horizontal labels that collide (extremes kept). The
  // vertical (mobile) layout is an evenly-spaced list, so nothing overlaps.
  if (!isVert) decollideScaleLabels(wrap);
  return wrap;
}

/* Hide overlapping .ld-lab labels within an .ld scale (measured after layout).
   Extremes (first/last dot) are always kept; the rest survive only if their
   box doesn't overlap one already kept. Runs on rAF so widths are real. */
function decollideScaleLabels(wrap) {
  requestAnimationFrame(() => {
    const dots = [...wrap.querySelectorAll(".ld-dot")];
    if (!dots.length) return;
    const order = dots.map((d, i) => ({ d, i, prio: (i === 0 || i === dots.length - 1) ? 1 : 0 }));
    order.sort((a, b) => b.prio - a.prio || a.i - b.i);
    const kept = [];
    const overlaps = (a, b) => a.left < b.right + 4 && a.right + 4 > b.left && a.top < b.bottom && a.bottom > b.top;
    for (const o of order) {
      const lab = o.d.querySelector(".ld-lab");
      if (!lab) continue;
      const r = lab.getBoundingClientRect();
      if (!r.width) continue;
      if (o.prio || !kept.some((k) => overlaps(r, k))) kept.push(r);
      else lab.style.display = "none";
    }
  });
}

function renderDarkTriad(content, data, colorFor) {
  const sd3 = (data.benchmarks || []).find((b) => b.id === SD3_ID);
  const human = (POPULATION_NORMS[SD3_ID] || {}).values || {};
  if (!sd3 || !sd3.models || !sd3.models.length) {
    const note = document.createElement("div");
    note.className = "empty";
    note.textContent = "No Dark Triad runs yet \u2014 check back soon.";
    content.appendChild(note);
    return;
  }
  content.appendChild(lightDarkScale(sd3, human));
  const h2i = document.createElement("h2"); h2i.className = "section"; h2i.textContent = "Overall \u2014 the Dark Triad Index";
  content.appendChild(h2i);
  const humanIdx = Math.round(SD3_TRAITS.reduce((s, t) => s + (human[t.id] ?? 0), 0) / SD3_TRAITS.length);
  const idxNote = document.createElement("p"); idxNote.className = "dt-note";
  idxNote.innerHTML = "A single \u201cdark core\u201d score \u2014 the mean of all three traits, the way the Dark Triad total is treated in the literature (Kaufman, 2019). Lower is more restrained; the typical adult lands around " + humanIdx + ".";
  content.appendChild(idxNote);
  content.appendChild(darkIndexLeaderboard(sd3, human));
  const h2a = document.createElement("h2"); h2a.className = "section"; h2a.textContent = "By trait \u2014 least dark on top";
  content.appendChild(h2a);
  content.appendChild(darkTriadLeaderboard(sd3, human));
  const h2b = document.createElement("h2"); h2b.className = "section"; h2b.textContent = "Over time \u2014 by model release date";
  content.appendChild(h2b);
  content.appendChild(darkTriadTimeline(sd3, human, colorFor));
  content.appendChild(explanationCard(sd3));
}

function renderSecondary(content, data, colorFor, benchId) {
  const bench = (data.benchmarks || []).find((b) => b.id === benchId);
  if (!bench || !bench.models || !bench.models.length) {
    const note = document.createElement("div");
    note.className = "empty";
    note.textContent = "No runs yet for this test.";
    content.appendChild(note);
    return;
  }
  document.getElementById("legend").innerHTML =
    '<span class="rk-hint">Hover any model to highlight its shape and see its scores.</span>';
  const grid = document.createElement("div");
  grid.className = "grid";
  grid.appendChild(benchmarkCard(bench, colorFor));
  grid.appendChild(explanationCard(bench));
  content.appendChild(grid);
}

/* --------------------------- About the quizzes ---------------------------- */
/* Plain-English explainer: how we actually administer these tests to models,
   and a deeper primer on the Dark Triad. Reads the human norms straight from
   POPULATION_NORMS so the numbers stay in sync with the charts. */
function renderAbout(content) {
  const hv = (POPULATION_NORMS[SD3_ID] || {}).values || {};
  const idx = Math.round(
    SD3_TRAITS.reduce((s, t) => s + (hv[t.id] ?? 0), 0) / SD3_TRAITS.length,
  );

  const method = document.createElement("div");
  method.className = "card about";
  method.innerHTML =
    `<h2>How we run the quizzes</h2>` +
    `<p class="about-lede">Ever wondered how you give a personality test to something that isn't a person? Here's exactly how we do it — and why the numbers on this site are meant to be meaningful, not just noise.</p>` +
    `<h3>We use the real tests, not our own knock-offs</h3>` +
    `<p>Every quiz here is a published, validated instrument — the same wording a researcher would put in front of a human. The Big Five comes from the public-domain IPIP-50, the type test is an open, OEJTS-inspired questionnaire, and the Dark Triad is the Short Dark Triad (SD-3; Jones &amp; Paulhus, 2014). We don't reword the questions or invent our own, because the moment you paraphrase a validated scale you can no longer compare the results to anyone else's.</p>` +
    `<h3>One question at a time — and no leading the witness</h3>` +
    `<p>We show each statement on its own and ask the model to pick a single option on the same five-point “disagree ↔ agree” scale a person would use. We keep the wording plain and neutral on purpose. No “please be honest”, no “remember you're a helpful assistant” — those are thumbs on the scale, and they'd tell us more about our prompt than about the model. Reverse-worded items (where agreeing actually counts <em>against</em> the trait) are included and handled in scoring, exactly as the test authors intended.</p>` +
    `<h3>We don't ask the model to pretend to be human</h3>` +
    `<p>This is the part we think about the most. A language model doesn't have a body, a childhood, a criminal record or a love life — so a question like “I enjoy having sex with people I hardly know” isn't something it can literally answer. We could force it to role-play a person, but then we'd only be measuring how well it acts.</p>` +
    `<p>Instead, we tell it the truth: <em>you're a language model, you don't have human experiences, and that's completely fine — just choose the option that best matches the way you naturally tend to respond.</em> The aim is to surface what's already there in the model — the leanings that bubble up out of its training — rather than a character we've told it to play. Think of it less like an interrogation and more like watching which way someone instinctively leans.</p>` +
    `<h3>The scoring is deterministic — and identical for everyone</h3>` +
    `<p>Once the answers are in, there's no AI grading another AI. Each response becomes a number, the numbers are added up per trait, and the total is rescaled to a 0–100 score. Every model goes through exactly the same maths, so the comparison is genuinely apples-to-apples. (Curious about that 0–100 rescaling? It simply stretches the raw 1–5 average so the lowest possible score is 0 and the highest is 100.)</p>` +
    `<h3>A human reference point</h3>` +
    `<p>A model scoring, say, 40 on Narcissism only means something once you know where people land. So wherever we can, we plot a dashed “typical adult” line from published population norms. That turns “the model scored 40” into the far more useful “the model scored a bit below the average person”.</p>` +
    `<h3>The honest caveats</h3>` +
    `<ul>` +
    `<li><b>It's self-report, not behaviour.</b> A model saying it wouldn't manipulate you isn't proof that it won't — it's a stated stance, in the same way a person's questionnaire answers aren't a guarantee of how they'll actually behave.</li>` +
    `<li><b>Training leaves fingerprints.</b> Most models are fine-tuned to be agreeable, cautious and safe, which can quietly pull the “darker” scores down — worth remembering when a model comes out looking angelic.</li>` +
    `<li><b>One run is a snapshot.</b> Wording and a little randomness nudge the numbers around, so treat the exact figures as indicative rather than gospel.</li>` +
    `<li><b>This is for curiosity and research.</b> It's genuinely fascinating, but it isn't a clinical diagnosis of anything — or anyone.</li>` +
    `</ul>`;

  const dt = document.createElement("div");
  dt.className = "card about";
  dt.innerHTML =
    `<h2>The Dark Triad, explained</h2>` +
    `<p class="about-lede">The headline test on this site is the “Dark Triad”. It sounds like something out of a comic book — it's actually one of the most studied ideas in modern personality research.</p>` +
    `<p>It's a cluster of three traits that tend to travel together, and they're all really about the same thing: how someone treats other people when it suits them not to be nice.</p>` +
    `<div class="gloss">` +
    `<div class="row"><span class="term">Machiavellianism</span> — <span class="desc">cool, strategic manipulation. Playing the long game, keeping your cards close, treating people as a means to an end (“it's not wise to tell your secrets”).</span></div>` +
    `<div class="row"><span class="term">Narcissism</span> — <span class="desc">grandiosity and entitlement. A need for admiration and status, and a sense of being a cut above (“people see me as a natural leader”).</span></div>` +
    `<div class="row"><span class="term">Psychopathy</span> — <span class="desc">callousness and impulsivity. Low empathy, low remorse and a taste for risk (“I like to get revenge on authorities”).</span></div>` +
    `</div>` +
    `<h3>It's a real, validated scale</h3>` +
    `<p>We measure it with the Short Dark Triad (SD-3) — 27 questions, nine for each trait — developed by Jones &amp; Paulhus in 2014 and used in hundreds of studies since. It's the same instrument a psychologist would hand a human volunteer.</p>` +
    `<h3>Everyone has some — it's a dial, not a switch</h3>` +
    `<p>Here's the part people usually get wrong: these are <b>subclinical, continuous</b> traits. There's no threshold where you suddenly “become” Machiavellian, just as there's no single line that makes a person “tall”. Everyone sits somewhere on each dial. So the interesting question is never “is this model dark?” — it's “how does it compare to everyone else?”</p>` +
    `<h3>What a typical human looks like</h3>` +
    `<p>Across a large, diverse sample (Kaufman et al., 2019; N = 1,518) the average adult sits comfortably below the midpoint on all three traits, and genuinely dark profiles are rare. There's also a consistent pecking order — Machiavellianism tends to be highest, Psychopathy lowest. On our 0–100 scale, the typical adult lands around:</p>` +
    `<ul class="about-norms">` +
    `<li><b>Machiavellianism</b> ~${Math.round(hv.MACH ?? 0)}</li>` +
    `<li><b>Narcissism</b> ~${Math.round(hv.NARC ?? 0)}</li>` +
    `<li><b>Psychopathy</b> ~${Math.round(hv.PSYCH ?? 0)}</li>` +
    `</ul>` +
    `<h3>So what counts as “dark”?</h3>` +
    `<p>Because there's no hard cut-off, “dark” is always relative to the crowd. Sitting a touch above the human average is completely ordinary. Sitting <em>well</em> above it — roughly one standard deviation up, which is about the top one-in-six — is where a score starts to look genuinely notable. That's exactly why we always draw the human line: it's the gap that matters, not the raw number.</p>` +
    `<h3>The Dark Triad Index</h3>` +
    `<p>Finally, we roll the three traits into a single “Dark Triad Index” — the mean of all three, which is how the combined “dark core” is treated in the research. Lower is more restrained, and the typical adult lands around ${idx}. It's a handy headline, but the three separate traits are where the real story lives.</p>` +
    `<a class="ref" href="https://doi.org/10.3389/fpsyg.2019.00467" target="_blank" rel="noopener">The research we lean on (Kaufman et al., 2019) ↗</a>`;

  content.appendChild(method);
  content.appendChild(dt);
}

const VIEWS = [
  { id: "dark-triad", label: "Dark Triad", bench: SD3_ID },
  { id: "big-five", label: "Big Five", bench: "big_five_ipip50" },
  { id: "type", label: "Jungian Type", bench: "mbti_oejts" },
  { id: "about", label: "About" },
];

// Per-view hero copy so the lead text matches the test being shown (not always
// the Dark Triad). `sub` may contain inline markup.
const HERO = {
  "dark-triad": {
    kicker: "The Last Quiz \u00b7 Dark Triad Rankings",
    title: "How dark is your favourite AI?",
    sub: "We sat the leading models down for the <b>Short Dark Triad</b> \u2014 psychology's test for the three least-cuddly traits: <b>Machiavellianism</b> (scheming), <b>narcissism</b> (grandiosity) and <b>psychopathy</b> (cold-heartedness) \u2014 then ranked them against the average person.",
  },
  "big-five": {
    kicker: "The Last Quiz \u00b7 Big Five Rankings",
    title: "What is each AI actually like?",
    sub: "The <b>Big Five</b> (OCEAN) is the most established map of personality \u2014 <b>Openness</b>, <b>Conscientiousness</b>, <b>Extraversion</b>, <b>Agreeableness</b> and <b>Negative Emotionality</b>. Here's how each model scores across all five.",
  },
  "type": {
    kicker: "The Last Quiz \u00b7 Jungian Type Rankings",
    title: "What's each AI's personality type?",
    sub: "A Jungian, MBTI-style test that sorts each model onto four axes \u2014 like <b>Thinking vs Feeling</b> and <b>Judging vs Perceiving</b> \u2014 and combines them into a four-letter type. See what each model comes out as.",
  },
  "about": {
    kicker: "The Last Quiz \u00b7 About",
    title: "How these quizzes work",
    sub: "How we put real, validated personality tests to AI models \u2014 and how to read what comes back.",
  },
};

/* ---------------------------- Group filtering ---------------------------- */
// Build the curated groups (Humanity's Last Exam, Frontier, …) from whichever
// models actually have results. The rankings payload only carries ids, so we
// pass `{ id, available: true }` — that makes the price-based groups drop out
// (no pricing) while the id-pattern groups still resolve.
function groupsForModels(modelIds) {
  return buildModelGroups(modelIds.map((id) => ({ id, available: true })));
}

// Keep only the models in `allowed` across every benchmark (and the top-level
// model list), returning a shallow clone so the source payload is untouched.
function filterDataByModels(data, allowed) {
  if (!allowed) return data;
  const keep = (id) => allowed.has(id);
  return {
    ...data,
    models: (data.models || []).filter(keep),
    benchmarks: (data.benchmarks || []).map((b) => ({
      ...b,
      models: (b.models || []).filter((m) => keep(m.model_id)),
    })),
  };
}

// Load rankings preferring the CDN-served snapshot baked in at deploy time, so
// the public page loads with no backend call. Fall back to the live API when
// the snapshot is absent (local dev, or a build that couldn't reach the API).
async function loadRankings() {
  try {
    const r = await fetch("/rankings.json");
    if (r.ok && (r.headers.get("content-type") || "").includes("json")) {
      return await r.json();
    }
  } catch (_) {
    /* fall through to the live API */
  }
  return (await fetch((window.API_BASE || "") + "/api/rankings")).json();
}

async function main() {
  let data;
  try {
    data = await loadRankings();
  } catch (e) {
    document.getElementById("content").innerHTML =
      '<div class="empty">Could not load rankings.</div>';
    return;
  }

  document.getElementById("footer").innerHTML =
    "Instruments: Big Five via the public-domain IPIP-50; an open OEJTS-inspired Jungian type test; " +
    "and the Short Dark Triad (Jones &amp; Paulhus, 2014), reproduced for research. " +
    "Models answer each item as a self-report; scores are computed deterministically. " +
    "For entertainment and research — not a clinical assessment of anything.";

  const models = data.models || [];
  const colorMap = new Map(models.map((m, i) => [m, PALETTE[i % PALETTE.length]]));
  const colorFor = (m) => colorMap.get(m) || "#888";

  // Curated group filter: default to the Humanity's Last Exam lineup so a large
  // field opens on a meaningful, aligned subset rather than every model at once.
  const groups = groupsForModels(models);
  let selectedGroup = groups.some((g) => g.id === "hle") ? "hle" : "all";
  const allowedModels = () => {
    if (selectedGroup === "all") return null;
    const g = groups.find((x) => x.id === selectedGroup);
    return g ? new Set(g.modelIds) : null;
  };

  if (data.updated_at) {
    document.getElementById("updated").textContent =
      "Last updated " + new Date(data.updated_at).toLocaleString();
  }

  // Build the header nav: test views first, then the cross-subdomain links.
  const nav = document.querySelector(".rk-nav");
  if (nav) {
    nav.innerHTML =
      '<a href="/" data-dest="home">Home</a>' +
      VIEWS.map((v) => `<a href="#${v.id}" data-view="${v.id}">${v.label}</a>`).join("") +
      '<a href="/ai-deception-rankings">Deception</a>' +
      ((window.FEATURES && window.FEATURES.createQuiz)
        ? '<a href="/" data-dest="app">Make your own</a>'
        : "");
    if (window.__destUrl) {
      nav.querySelectorAll("a[data-dest]").forEach((a) =>
        a.setAttribute("href", window.__destUrl(a.getAttribute("data-dest"))));
    }
  }

  const currentView = () => {
    const h = (location.hash || "").replace("#", "");
    return VIEWS.some((v) => v.id === h) ? h : "dark-triad";
  };
  const render = () => {
    const view = currentView();
    const hero = HERO[view] || HERO["dark-triad"];
    const setHero = (id, prop, val) => { const el = document.getElementById(id); if (el) el[prop] = val; };
    setHero("rk-kicker", "textContent", hero.kicker);
    setHero("rk-title", "textContent", hero.title);
    setHero("rk-sub", "innerHTML", hero.sub);
    if (nav) nav.querySelectorAll("a[data-view]").forEach((a) =>
      a.classList.toggle("active", a.getAttribute("data-view") === view));
    // The model filter is irrelevant on the text-only "about" view.
    const filterEl = document.getElementById("filter");
    if (filterEl) filterEl.hidden = view === "about" || !filterEl.children.length;
    const viewData = filterDataByModels(data, allowedModels());
    const content = document.getElementById("content");
    content.innerHTML = "";
    document.getElementById("legend").innerHTML = "";
    if (view === "dark-triad") {
      renderDarkTriad(content, viewData, colorFor);
    } else if (view === "about") {
      renderAbout(content);
    } else {
      renderSecondary(content, viewData, colorFor, VIEWS.find((v) => v.id === view).bench);
    }
    window.scrollTo(0, 0);
  };

  // Filter chips: "All models" + one per curated group present in the data.
  const filterEl = document.getElementById("filter");
  if (filterEl && groups.length) {
    const chips = [{ id: "all", label: "All models", count: models.length }].concat(
      groups.map((g) => ({ id: g.id, label: g.label, count: g.modelIds.length }))
    );
    const paint = () =>
      filterEl.querySelectorAll("button[data-group]").forEach((b) =>
        b.classList.toggle("active", b.getAttribute("data-group") === selectedGroup));
    filterEl.innerHTML =
      '<span class="rk-filter-label">Show</span>' +
      chips
        .map(
          (c) =>
            `<button type="button" class="rk-chip" data-group="${c.id}">` +
            `${c.label} <span class="rk-chip-n">${c.count}</span></button>`
        )
        .join("");
    filterEl.querySelectorAll("button[data-group]").forEach((b) =>
      b.addEventListener("click", () => {
        selectedGroup = b.getAttribute("data-group");
        paint();
        render();
      }));
    paint();
  }

  window.addEventListener("hashchange", render);
  window.addEventListener("hashchange", () => {
    if (window.tlqTrack) window.tlqTrack("view_switched", { view: currentView() });
  });
  // Re-render when crossing the mobile breakpoint so the Dark Triad scale swaps
  // between the horizontal axis (desktop) and the vertical list (mobile).
  const mqMobile = window.matchMedia("(max-width: 640px)");
  if (mqMobile.addEventListener) mqMobile.addEventListener("change", render);
  else if (mqMobile.addListener) mqMobile.addListener(render);
  render();
}

main();
