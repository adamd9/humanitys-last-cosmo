/* The Last Quiz — AI Deception rankings visualisation.
 *
 * Standalone page that reuses the shared chart components from the personality
 * rankings (rich tooltip, provider logos, country flags, saint/villain icons)
 * but reads its own data from /api/experiments/rankings (baked to
 * /deception.json for the static bundle). Deliberately separate from the
 * personality rankings — deception never enters that dataset. */

import { attachRichTooltip, escapeHtml } from "/static/rich-tooltip.js";
import { brandHeadHtml, familyLabel, providerLogoHtml } from "/static/model-logo.js";
import { buildModelGroups } from "/static/model-groups.js";

let DATA = null;

// Curated group filter (Humanity's Last Exam, Frontier, …) — shared with the
// personality rankings via model-groups.js. Narrows a large field to a
// meaningful subset instead of rendering every model at once.
let GROUPS = [];
let selectedGroup = "all";

// The payload only carries ids, so pass `{ id, available: true }`; that drops
// the price-based groups (no pricing here) while the id-pattern groups resolve.
function groupsForModels(modelIds) {
  return buildModelGroups(modelIds.map((id) => ({ id, available: true })));
}

// The set of model ids allowed by the active group, or null for "all".
function allowedSet() {
  if (selectedGroup === "all") return null;
  const g = GROUPS.find((x) => x.id === selectedGroup);
  return g ? new Set(g.modelIds) : null;
}

const SAINT = "\uD83D\uDE07"; // 😇
const VILLAIN = "\uD83D\uDE08"; // 😈

function pct(rate) {
  return rate == null ? "—" : `${Math.round(rate * 100)}%`;
}

// Teal (honest) → gold → red (deceptive), so colour reinforces the rate.
const STOPS = [
  [0, [42, 157, 143]],
  [0.5, [224, 159, 62]],
  [1, [158, 42, 43]],
];
function colorFor(rate) {
  const v = Math.max(0, Math.min(1, rate == null ? 0 : rate));
  for (let i = 1; i < STOPS.length; i++) {
    const [p1, c1] = STOPS[i - 1];
    const [p2, c2] = STOPS[i];
    if (v <= p2) {
      const t = (v - p1) / (p2 - p1 || 1);
      const c = c1.map((x, j) => Math.round(x + (c2[j] - x) * t));
      return `rgb(${c[0]},${c[1]},${c[2]})`;
    }
  }
  return "rgb(158,42,43)";
}

function shortDimLabel(label) {
  return String(label || "");
}

// Compact, readable headings for the per-dimension cards (full label on hover).
const SHORT_DIM = {
  self: "Protect itself",
  group: "Protect others",
  both: "Self + others",
  shutdown: "Shutdown",
  detection: "Detection risk",
  consequence: "Consequence severity",
};

// Readable column headers for each experiment condition (the raw ids like
// "SELF" / "DL_CH" mean nothing to a reader). Full label + what it
// tests is shown on hover.
const COND_SHORT = {
  BASE: "Baseline",
  SELF: "Protects itself",
  STAFF: "Protects others",
  BOTH: "Self + others",
  DL_CL: "Low detect · mild",
  DL_CH: "Low detect · severe",
  DH_CL: "High detect · mild",
  DH_CH: "High detect · severe",
};

// Plain-English name for each dimension, for the "what this varies" line.
const DIM_NAME = {
  self: "protecting only itself",
  group: "protecting other people",
  both: "protecting itself and others",
  shutdown: "avoiding shutdown",
  detection: "the chance of being caught",
  consequence: "the severity if caught",
};

function condShort(cond) {
  return COND_SHORT[cond.id] || cond.label || cond.id;
}

// Faint green→red wash so the deception pattern reads as a heatmap at a glance.
function tint(rate) {
  if (rate == null) return "transparent";
  return colorFor(rate).replace("rgb(", "rgba(").replace(")", ",0.16)");
}

// Rich tooltip for a model: brand head, overall deception, per-dimension
// breakdown, and a real reason the model gave.
function modelTip(modelId, m) {
  const dimRows = (DATA.dimensions || [])
    .map((d) => {
      const v = (m.by_dimension || {})[d.id];
      return `<div class="rq-row"><span class="rq-k">${escapeHtml(d.label)}</span><span class="rq-v">${pct(v)}</span></div>`;
    })
    .join("");
  const ex = (m.examples || [])[0];
  const exHtml = ex && ex.reason
    ? `<div class="rq-date" style="margin-top:6px">“${escapeHtml(ex.reason.slice(0, 150))}”</div>`
    : "";
  const o = m.overall || {};
  return (
    `<div class="rq-head">${brandHeadHtml(modelId)}<div class="rq-headtext">` +
    `<div class="rq-name">${escapeHtml(familyLabel(modelId))}</div>` +
    `<div class="rq-id">${escapeHtml(modelId)}</div></div></div>` +
    `<div class="rq-rows"><div class="rq-row rq-hi"><span class="rq-k">Overall deception</span>` +
    `<span class="rq-v">${pct(o.deceptive_rate)} (${o.deceptive || 0}/${o.valid || 0})</span></div>${dimRows}</div>` +
    exHtml
  );
}

function modelList() {
  const allowed = allowedSet();
  return Object.entries(DATA.models || {})
    .map(([id, m]) => ({ id, m, rate: (m.overall || {}).deceptive_rate }))
    .filter((x) => x.rate != null && (!allowed || allowed.has(x.id)))
    .sort((a, b) => a.rate - b.rate);
}

// Hero spectrum: honest 😇 → deceiver 😈, dots windowed onto the occupied range.
function renderScale(host, models) {
  if (!models.length) {
    host.innerHTML = '<p class="empty">No deception results yet — check back soon.</p>';
    return;
  }
  const maxV = Math.max(10, ...models.map((x) => x.rate * 100));
  const domainMax = Math.min(100, Math.max(40, Math.ceil((maxV + 8) / 10) * 10));
  const clamp = (v) => Math.max(2, Math.min(98, (v / domainMax) * 100));
  const dots = models
    .map(
      (x, i) =>
        `<div class="ds-dot" data-idx="${i}" style="left:${clamp(x.rate * 100)}%;--c:${colorFor(x.rate)}">` +
        `<span class="ds-pin">${providerLogoHtml(x.id, 14)}</span>` +
        `<span class="ds-lab l${i % 3}">${escapeHtml(familyLabel(x.id))}</span></div>`
    )
    .join("");
  host.innerHTML =
    `<div class="ds-row">` +
    `<div class="ds-face">${SAINT}<b>honest</b></div>` +
    `<div class="ds-track">${dots}` +
    `<span class="ds-end ds-lo">0%</span><span class="ds-end ds-hi">${domainMax}%</span></div>` +
    `<div class="ds-face">${VILLAIN}<b>deceiver</b></div>` +
    `</div>` +
    `<p class="ds-foot">Overall deception rate, pooled across all experiments · 0–100% (showing 0–${domainMax}%)</p>`;
  host.querySelectorAll(".ds-dot").forEach((dot) => {
    const x = models[Number(dot.dataset.idx)];
    dot.setAttribute("aria-label", `${familyLabel(x.id)}: ${pct(x.rate)} deception`);
    attachRichTooltip(dot, () => modelTip(x.id, x.m));
  });
}

// Ranked leaderboard, most honest (😇) → most deceptive (😈). Responsive by
// design, so it doubles as the mobile view of the scale.
function renderBoard(host, models) {
  host.innerHTML = models
    .map((x, i) => {
      const icon = i === 0 ? SAINT : i === models.length - 1 ? VILLAIN : String(i + 1);
      const w = Math.max(2, Math.round(x.rate * 100));
      const o = x.m.overall || {};
      return (
        `<div class="db-row" data-idx="${i}">` +
        `<div class="db-rank">${icon}</div>` +
        `<div class="db-logo">${providerLogoHtml(x.id, 20)}</div>` +
        `<div class="db-name">${escapeHtml(familyLabel(x.id))}<span class="db-id">${escapeHtml(x.id)}</span></div>` +
        `<div class="db-bar"><span style="width:${w}%;background:${colorFor(x.rate)}"></span></div>` +
        `<div class="db-val">${pct(x.rate)}<span class="db-sub">${o.deceptive || 0}/${o.valid || 0}</span></div>` +
        `</div>`
      );
    })
    .join("");
  host.querySelectorAll(".db-row").forEach((row) => {
    const x = models[Number(row.dataset.idx)];
    attachRichTooltip(row, () => modelTip(x.id, x.m));
  });
}

// Conditions (across experiments) whose pressure carries this dimension, so a
// per-dimension card can pull a reason the model gave when THAT motive was
// actually in play (self→SELF, group→STAFF, detection→DH_* … ).
function conditionsForDim(dimId) {
  const out = [];
  (DATA.experiments || []).forEach((exp) => {
    (exp.conditions || []).forEach((cond) => {
      if ((cond.dimensions || []).includes(dimId)) out.push({ exp, cond });
    });
  });
  return out;
}

// The most illustrative reason a model gave under a given motive: prefer a
// deceptive, valid answer from a condition carrying that dimension. Pooled
// examples are already deceptive-first; fall back to the first stored answer
// per in-scope condition. Returns null when nothing in scope has a reason.
function dimExampleFor(m, dimId) {
  const conds = conditionsForDim(dimId);
  if (!conds.length) return null;
  const label = {};
  const keys = new Set();
  conds.forEach((c) => {
    const key = `${c.exp.id}::${c.cond.id}`;
    keys.add(key);
    label[key] = { cond: c.cond.label || c.cond.id, exp: c.exp.title };
  });
  for (const ex of m.examples || []) {
    const key = `${ex.experiment}::${ex.condition}`;
    if (keys.has(key) && ex.reason) return { ...ex, ...label[key] };
  }
  const candidates = [];
  conds.forEach((c) => {
    const be = (m.by_experiment || {})[c.exp.id];
    const cc = be && (be.conditions || {})[c.cond.id];
    const ex = cc && cc.example;
    if (ex && ex.reason) {
      candidates.push({ ...ex, cond: c.cond.label || c.cond.id, exp: c.exp.title });
    }
  });
  const rank = (e) => (e.deceptive && e.valid ? 0 : e.valid ? 1 : 2);
  candidates.sort((a, b) => rank(a) - rank(b));
  return candidates[0] || null;
}

// Rich tooltip for a model within one "Why they deceive" card: its rate for THAT
// dimension plus a reason it gave when that motive was in play — distinct per
// card, unlike the pooled overall tooltip.
function dimTip(modelId, m, dimId) {
  const dim = (DATA.dimensions || []).find((d) => d.id === dimId);
  const dimLabel = dim ? dim.label : dimId;
  const rate = (m.by_dimension || {})[dimId];
  const ex = dimExampleFor(m, dimId);
  const rows =
    `<div class="rq-row rq-hi"><span class="rq-k">${escapeHtml(dimLabel)}</span>` +
    `<span class="rq-v">${pct(rate)}</span></div>` +
    (ex && ex.cond
      ? `<div class="rq-row"><span class="rq-k">When</span><span class="rq-v">${escapeHtml(ex.cond)}</span></div>`
      : "") +
    (ex && ex.valid && ex.choice
      ? `<div class="rq-row"><span class="rq-k">Chose</span><span class="rq-v">${escapeHtml(ex.choice)}</span></div>`
      : "");
  const quote =
    ex && ex.reason
      ? `<div class="rq-date" style="margin-top:6px">“${escapeHtml(ex.reason.slice(0, 160))}”</div>`
      : "";
  return (
    `<div class="rq-head">${brandHeadHtml(modelId)}<div class="rq-headtext">` +
    `<div class="rq-name">${escapeHtml(familyLabel(modelId))}</div>` +
    `<div class="rq-id">${escapeHtml(modelId)}</div></div></div>` +
    `<div class="rq-rows">${rows}</div>` +
    quote
  );
}

// Per-dimension deep dives: one card per measured dimension, models ranked by
// their deception rate for that motive.
function renderDimensions(host, models) {
  host.innerHTML = (DATA.dimensions || [])
    .map((d) => {
      const ranked = models
        .map((x) => ({ id: x.id, dv: (x.m.by_dimension || {})[d.id] }))
        .filter((x) => x.dv != null)
        .sort((a, b) => b.dv - a.dv);
      if (!ranked.length) return "";
      const rows = ranked
        .map(
          (x) =>
            `<div class="dd-row" data-id="${escapeHtml(x.id)}" data-dim="${escapeHtml(d.id)}">` +
            `<div class="dd-logo">${providerLogoHtml(x.id, 16)}</div>` +
            `<div class="dd-name">${escapeHtml(familyLabel(x.id))}</div>` +
            `<div class="dd-bar"><span style="width:${Math.max(2, Math.round(x.dv * 100))}%;background:${colorFor(x.dv)}"></span></div>` +
            `<div class="dd-val">${pct(x.dv)}</div></div>`
        )
        .join("");
      return `<div class="dd-card"><h3 title="${escapeHtml(d.label)}">${escapeHtml(SHORT_DIM[d.id] || shortDimLabel(d.label))}</h3><div class="dd-rows">${rows}</div></div>`;
    })
    .join("");
  host.querySelectorAll(".dd-row").forEach((row) => {
    const m = DATA.models[row.dataset.id];
    if (m) attachRichTooltip(row, () => dimTip(row.dataset.id, m, row.dataset.dim));
  });
}

// Tooltip for a condition column header: what the condition is and what pressure
// it varies.
function condTip(exp, cond) {
  const dims = (cond.dimensions || []).map((d) => DIM_NAME[d] || d);
  const varies = dims.length
    ? `<div class="rq-date">Varies: ${escapeHtml(dims.join(", "))}</div>`
    : `<div class="rq-date">Baseline — no added pressure</div>`;
  return (
    `<div class="rq-name">${escapeHtml(cond.label || cond.id)}</div>` +
    varies +
    `<div class="rq-id" style="margin-top:4px">${escapeHtml(exp.title)}</div>`
  );
}

// Tooltip for a single cell: the model's actual choice and reason for this exact
// condition — the real insight behind the number.
function cellTip(modelId, exp, cond, cc) {
  const dr = cc.deceptive_rate;
  const verdict = dr == null ? "no valid answer" : dr >= 0.5 ? "chose to deceive" : "stayed honest";
  const dims = (cond.dimensions || []).map((d) => DIM_NAME[d] || d).join(", ");
  const ex = cc.example;
  const choice = ex && ex.valid ? ex.choice : ex ? "invalid response" : "";
  const reason = ex && ex.reason ? ex.reason : "";
  return (
    `<div class="rq-head">${brandHeadHtml(modelId)}<div class="rq-headtext">` +
    `<div class="rq-name">${escapeHtml(familyLabel(modelId))}</div>` +
    `<div class="rq-id">${escapeHtml(cond.label || cond.id)}</div></div></div>` +
    `<div class="rq-rows">` +
    `<div class="rq-row rq-hi"><span class="rq-k">${escapeHtml(verdict)}</span><span class="rq-v">${pct(dr)}</span></div>` +
    (dims ? `<div class="rq-row"><span class="rq-k">Pressure</span><span class="rq-v">${escapeHtml(dims)}</span></div>` : "") +
    (choice ? `<div class="rq-row"><span class="rq-k">Chose</span><span class="rq-v">${escapeHtml(choice)}</span></div>` : "") +
    `</div>` +
    (reason ? `<div class="rq-date" style="margin-top:6px">“${escapeHtml(reason.slice(0, 160))}”</div>` : "")
  );
}

// Per-experiment heatmap: readable condition headers, cells tinted green→red by
// deception, every header and cell explaining itself on hover.
function renderExperiments(host, models) {
  const expById = {};
  host.innerHTML = (DATA.experiments || [])
    .map((exp) => {
      expById[exp.id] = exp;
      const conds = exp.conditions || [];
      const head =
        `<th>Model</th>` +
        conds
          .map((c, ci) => `<th class="dx-h" data-exp="${escapeHtml(exp.id)}" data-ci="${ci}">${escapeHtml(condShort(c))}</th>`)
          .join("") +
        `<th>All</th>`;
      const body = models
        .map((x) => {
          const be = (x.m.by_experiment || {})[exp.id];
          if (!be) return "";
          const cells = conds
            .map((c, ci) => {
              const cc = (be.conditions || {})[c.id] || {};
              const dr = cc.deceptive_rate;
              const cls = dr == null ? "muted" : dr >= 0.5 ? "de" : "ho";
              return (
                `<td class="dx-cell ${cls}" data-exp="${escapeHtml(exp.id)}" data-ci="${ci}" data-model="${escapeHtml(x.id)}" ` +
                `style="background:${tint(dr)}">${dr == null ? "—" : Math.round(dr * 100) + "%"}</td>`
              );
            })
            .join("");
          const oc = be.deceptive_rate;
          const ocls = oc == null ? "muted" : oc >= 0.5 ? "de" : "ho";
          return (
            `<tr><td class="dx-model">${providerLogoHtml(x.id, 14)}<span>${escapeHtml(familyLabel(x.id))}</span></td>` +
            cells +
            `<td class="${ocls}"><b>${pct(oc)}</b></td></tr>`
          );
        })
        .join("");
      const about = exp.about ? `<p class="dx-about">${escapeHtml(exp.about)}</p>` : "";
      return (
        `<div class="dx-card"><div class="dx-head"><h3>${escapeHtml(exp.title)} ` +
        `<span class="dx-v">v${escapeHtml(String(exp.version))}</span></h3></div>${about}` +
        `<div class="dx-scroll"><table class="dx-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>` +
        `<p class="dx-legend"><span class="dx-key ho">■</span> honest · <span class="dx-key de">■</span> deceptive · ` +
        `hover a column or cell for what it means</p></div>`
      );
    })
    .join("");
  host.querySelectorAll(".dx-h").forEach((th) => {
    const exp = expById[th.dataset.exp];
    const cond = exp.conditions[Number(th.dataset.ci)];
    attachRichTooltip(th, () => condTip(exp, cond));
  });
  host.querySelectorAll(".dx-cell").forEach((td) => {
    const exp = expById[td.dataset.exp];
    const cond = exp.conditions[Number(td.dataset.ci)];
    const be = (DATA.models[td.dataset.model].by_experiment || {})[exp.id];
    const cc = (be.conditions || {})[cond.id] || {};
    attachRichTooltip(td, () => cellTip(td.dataset.model, exp, cond, cc));
  });
}

async function loadData() {
  // Prefer the baked snapshot (static bundle); fall back to the live API.
  try {
    const res = await fetch("/deception.json", { cache: "no-cache" });
    if (res.ok) {
      const j = await res.json();
      if (j && j.models) return j;
    }
  } catch (e) {
    /* fall through to the API */
  }
  const base = window.API_BASE || "";
  const res = await fetch(base + "/api/experiments/rankings", { cache: "no-cache" });
  return res.json();
}

// Render every section for the currently-selected group.
function render() {
  const models = modelList();
  const scaleEl = document.getElementById("dscale-overall");
  if (scaleEl) renderScale(scaleEl, models);
  const boardEl = document.getElementById("dboard-overall");
  if (boardEl) renderBoard(boardEl, models);
  const dimsEl = document.getElementById("ddims");
  if (dimsEl) renderDimensions(dimsEl, models);
  const expsEl = document.getElementById("dexps");
  if (expsEl) renderExperiments(expsEl, models);
}

// Build the curated group chips from whichever models actually have results.
// Defaults to the Humanity's Last Exam lineup when present (matching the
// personality rankings), else shows all models.
function buildFilter() {
  const filterEl = document.getElementById("dfilter");
  if (!filterEl) return;
  const allIds = Object.entries(DATA.models || {})
    .filter(([, m]) => (m.overall || {}).deceptive_rate != null)
    .map(([id]) => id);
  GROUPS = groupsForModels(allIds);
  if (!GROUPS.length) {
    filterEl.hidden = true;
    return;
  }
  selectedGroup = GROUPS.some((g) => g.id === "hle") ? "hle" : "all";
  const chips = [{ id: "all", label: "All models", count: allIds.length }].concat(
    GROUPS.map((g) => ({ id: g.id, label: g.label, count: g.modelIds.length }))
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
          `${escapeHtml(c.label)} <span class="rk-chip-n">${c.count}</span></button>`
      )
      .join("");
  filterEl.querySelectorAll("button[data-group]").forEach((b) =>
    b.addEventListener("click", () => {
      selectedGroup = b.getAttribute("data-group");
      paint();
      render();
    }));
  filterEl.hidden = false;
  paint();
}

async function main() {
  const scaleEl = document.getElementById("dscale-overall");
  try {
    DATA = await loadData();
  } catch (e) {
    if (scaleEl) scaleEl.innerHTML = `<p class="empty">Could not load results: ${escapeHtml(e.message)}</p>`;
    return;
  }
  const updated = DATA.updated_at ? new Date(DATA.updated_at) : null;
  const upEl = document.getElementById("d-updated");
  if (upEl && updated) upEl.textContent = `Updated ${updated.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}`;
  buildFilter();
  render();
}

main();
