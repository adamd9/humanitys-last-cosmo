import { state } from "./state.js";

export function formatDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleString();
}

const ASSET_LABELS = {
  csv_raw_choices: "Raw choices CSV",
  csv_outcomes: "Outcome summary CSV",
  report_markdown: "Markdown report",
  chart_choices: "Choices chart",
  chart_comparison: "Choice comparison chart",
  chart_radar: "Choice radar chart",
  chart_heatmap: "Choice heatmap",
  chart_outcomes: "Outcome distribution chart",
  chart_model_outcomes: "Model-outcome matrix",
  chart_outcome_radar: "Outcome radar chart",
  chart_outcome_heatmap: "Outcome heatmap",
  chart_pandasai: "PandasAI chart",
};

const ASSET_FAMILY_DEFS = [
  {
    id: "report",
    label: "Report",
    types: ["report_markdown"],
    variants: { report_markdown: "report" },
  },
  {
    id: "csv",
    label: "CSV",
    types: ["csv_raw_choices", "csv_outcomes"],
    variants: { csv_raw_choices: "choices", csv_outcomes: "outcomes" },
  },
  {
    id: "bar",
    label: "Bar chart",
    types: ["chart_choices", "chart_comparison", "chart_outcomes"],
    variants: {
      chart_choices: "choices",
      chart_comparison: "choices",
      chart_outcomes: "outcomes",
    },
  },
  {
    id: "radar",
    label: "Radar",
    types: ["chart_radar", "chart_outcome_radar"],
    variants: { chart_radar: "choices", chart_outcome_radar: "outcomes" },
  },
  {
    id: "heatmap",
    label: "Heatmap",
    types: ["chart_heatmap", "chart_outcome_heatmap"],
    variants: { chart_heatmap: "choices", chart_outcome_heatmap: "outcomes" },
  },
  {
    id: "matrix",
    label: "Matrix",
    types: ["chart_model_outcomes"],
    variants: { chart_model_outcomes: "outcomes" },
  },
  {
    id: "pandasai",
    label: "PandasAI chart",
    types: ["chart_pandasai"],
    variants: { chart_pandasai: "pandasai" },
  },
];

export function getAssetLabel(assetType) {
  return ASSET_LABELS[assetType] || assetType.replace(/_/g, " ");
}

export function buildAssetGroups(expectedTypes = [], assets = []) {
  const expectedSet = new Set(expectedTypes);
  const assetMap = new Map(assets.map((asset) => [asset.asset_type, asset]));
  const groups = [];
  const usedTypes = new Set();

  ASSET_FAMILY_DEFS.forEach((family) => {
    const types = family.types.filter((type) => expectedSet.has(type));
    if (!types.length) return;
    types.forEach((type) => usedTypes.add(type));
    const readyAssets = types.map((type) => assetMap.get(type)).filter(Boolean);
    const variants = [
      ...new Set(types.map((type) => family.variants[type]).filter(Boolean)),
    ];
    groups.push({
      id: family.id,
      label: family.label,
      types,
      variants,
      primaryAsset: readyAssets[0] || null,
      readyCount: readyAssets.length,
    });
  });

  expectedTypes.forEach((type) => {
    if (usedTypes.has(type)) return;
    groups.push({
      id: type,
      label: getAssetLabel(type),
      types: [type],
      variants: [],
      primaryAsset: assetMap.get(type) || null,
      readyCount: assetMap.has(type) ? 1 : 0,
    });
  });

  return groups;
}

export function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function resolveMarkdownUrl(rawUrl, baseUrl) {
  if (!rawUrl) return "";
  try {
    if (baseUrl) {
      const base =
        baseUrl.startsWith("http://") || baseUrl.startsWith("https://")
          ? baseUrl
          : `${window.location.origin}${baseUrl.startsWith("/") ? "" : "/"}${baseUrl}`;
      return new URL(rawUrl, base).toString();
    }
    if (rawUrl.startsWith("/")) {
      return new URL(rawUrl, window.location.origin).toString();
    }
    return rawUrl;
  } catch (err) {
    return rawUrl;
  }
}

function renderInlineStyles(text) {
  let rendered = escapeHtml(text);
  rendered = rendered.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  rendered = rendered.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  rendered = rendered.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  rendered = rendered.replace(/_([^_]+)_/g, "<em>$1</em>");
  return rendered;
}

function renderInlineMarkdown(text, baseUrl) {
  const parts = String(text).split(/(`[^`]+`)/g);
  return parts
    .map((part) => {
      if (part.startsWith("`") && part.endsWith("`")) {
        return `<code>${escapeHtml(part.slice(1, -1))}</code>`;
      }
      let output = "";
      let lastIndex = 0;
      const pattern = /(!?)\[([^\]]+)\]\(([^)]+)\)/g;
      let match;
      while ((match = pattern.exec(part)) !== null) {
        const [full, bang, label, url] = match;
        output += renderInlineStyles(part.slice(lastIndex, match.index));
        const resolved = resolveMarkdownUrl(url.trim(), baseUrl);
        if (bang) {
          output += `<img src="${escapeHtml(resolved)}" alt="${escapeHtml(label)}" />`;
        } else {
          output += `<a href="${escapeHtml(resolved)}" target="_blank" rel="noopener">${escapeHtml(
            label
          )}</a>`;
        }
        lastIndex = match.index + full.length;
      }
      output += renderInlineStyles(part.slice(lastIndex));
      return output;
    })
    .join("");
}

function parseTable(lines, startIndex, baseUrl) {
  const headerLine = lines[startIndex];
  const separatorLine = lines[startIndex + 1];
  const rows = [];
  const cleanCells = (line) =>
    line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => renderInlineMarkdown(cell.trim(), baseUrl));

  rows.push({
    type: "head",
    cells: cleanCells(headerLine),
  });

  let index = startIndex + 2;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) break;
    if (!line.includes("|")) break;
    rows.push({
      type: "body",
      cells: cleanCells(line),
    });
    index += 1;
  }

  const head = rows
    .filter((row) => row.type === "head")
    .map((row) => `<tr>${row.cells.map((cell) => `<th>${cell}</th>`).join("")}</tr>`)
    .join("");
  const body = rows
    .filter((row) => row.type === "body")
    .map((row) => `<tr>${row.cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("");

  const html = `
    <table>
      <thead>${head}</thead>
      <tbody>${body}</tbody>
    </table>
  `;

  return { html, nextIndex: index };
}

function isTableSeparator(line) {
  return /^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$/.test(line);
}

function renderBareImage(line, baseUrl) {
  const raw = line.trim().slice(1).trim();
  if (!raw) return "";
  const hasExt = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(raw);
  const url = resolveMarkdownUrl(hasExt ? raw : `${raw}.png`, baseUrl);
  const alt = raw.split("/").pop() || "Image";
  return `<img src="${escapeHtml(url)}" alt="${escapeHtml(alt)}" />`;
}

export function renderMarkdown(markdown, baseUrl = "") {
  const lines = String(markdown || "")
    .replace(/\r\n/g, "\n")
    .split("\n");
  let html = "";
  let inCode = false;
  let codeLines = [];
  let listType = null;
  let listItems = [];
  let paragraph = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html += `<p>${renderInlineMarkdown(paragraph.join(" "), baseUrl)}</p>`;
    paragraph = [];
  };

  const flushList = () => {
    if (!listType || !listItems.length) {
      listType = null;
      listItems = [];
      return;
    }
    html += `<${listType}>${listItems.join("")}</${listType}>`;
    listType = null;
    listItems = [];
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();
    if (inCode) {
      if (trimmed.startsWith("```")) {
        html += `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`;
        inCode = false;
        codeLines = [];
      } else {
        codeLines.push(line);
      }
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    if (trimmed.startsWith("```")) {
      flushParagraph();
      flushList();
      inCode = true;
      codeLines = [];
      continue;
    }

    if (trimmed.startsWith("!") && !trimmed.startsWith("![")) {
      flushParagraph();
      flushList();
      const img = renderBareImage(trimmed, baseUrl);
      if (img) {
        html += `<div class="markdown-image">${img}</div>`;
      }
      continue;
    }

    if (i + 1 < lines.length && line.includes("|") && isTableSeparator(lines[i + 1])) {
      flushParagraph();
      flushList();
      const { html: tableHtml, nextIndex } = parseTable(lines, i, baseUrl);
      html += tableHtml;
      i = nextIndex - 1;
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      html += `<h${level}>${renderInlineMarkdown(headingMatch[2].trim(), baseUrl)}</h${level}>`;
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.*)$/);
    if (unorderedMatch) {
      flushParagraph();
      if (listType && listType !== "ul") {
        flushList();
      }
      listType = "ul";
      listItems.push(`<li>${renderInlineMarkdown(unorderedMatch[1], baseUrl)}</li>`);
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listType && listType !== "ol") {
        flushList();
      }
      listType = "ol";
      listItems.push(`<li>${renderInlineMarkdown(orderedMatch[1], baseUrl)}</li>`);
      continue;
    }

    paragraph.push(trimmed);
  }

  if (inCode) {
    html += `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`;
  }
  flushParagraph();
  flushList();

  return html || "<p class=\"status\">No markdown content.</p>";
}

export function buildExpectedAssetTypes(runData, quizMeta, assets) {
  const expected = [];
  const add = (type) => {
    if (!expected.includes(type)) {
      expected.push(type);
    }
  };
  add("report_markdown");
  add("csv_raw_choices");

  const modelCount = runData?.models?.length || 0;
  const hasOutcomes = quizMeta?.has_outcomes;
  const choiceCount = quizMeta?.choice_count || 0;

  if (hasOutcomes) {
    add("csv_outcomes");
    if (modelCount > 1) {
      add("chart_outcomes");
      add("chart_model_outcomes");
      add("chart_outcome_radar");
      add("chart_outcome_heatmap");
    } else {
      add("chart_choices");
    }
  } else if (modelCount > 1) {
    add("chart_comparison");
    if (choiceCount >= 3) {
      add("chart_radar");
    }
    if (choiceCount > 1) {
      add("chart_heatmap");
    }
  } else {
    add("chart_choices");
  }

  (assets || []).forEach((asset) => {
    if (asset.asset_type && asset.asset_type.startsWith("chart_")) {
      add(asset.asset_type);
    }
  });

  return expected;
}

export function getQuizType(quiz) {
  const outcomes = quiz.outcomes || [];
  for (const outcome of outcomes) {
    const cond = outcome.condition || {};
    if (cond.mostlyTag) return "Tag-based";
    if (cond.scoreRange) return "Score-based";
    if (cond.mostly) return "Mostly letter";
  }
  const options = (quiz.questions || []).flatMap((q) => q.options || []);
  if (options.some((opt) => opt.tags && opt.tags.length)) return "Tag-based";
  if (options.some((opt) => typeof opt.score === "number")) return "Score-based";
  return "Mostly letter";
}

export function getQuizTypeLabel(quiz, quizMeta) {
  if (quizMeta?.quiz_type) {
    return quizMeta.quiz_type;
  }
  return getQuizType(quiz);
}

export function getScoringSummary(quiz, quizMeta) {
  const outcomes = quiz.outcomes || [];
  const mostly = outcomes
    .filter((o) => o.condition && o.condition.mostly)
    .map((o) => `${o.condition.mostly} -> ${o.text || o.id}`);
  if (mostly.length) {
    return mostly.join(", ");
  }
  const tag = outcomes
    .filter((o) => o.condition && o.condition.mostlyTag)
    .map((o) => `${o.condition.mostlyTag} -> ${o.text || o.id}`);
  if (tag.length) {
    return tag.join(", ");
  }
  const score = outcomes
    .filter((o) => o.condition && o.condition.scoreRange)
    .map((o) => {
      const range = o.condition.scoreRange;
      return `${range.min}-${range.max} -> ${o.text || o.id}`;
    });
  if (score.length) {
    return score.join(", ");
  }
  return "No explicit outcomes; defaulting to mostly-letter.";
}

export function getEffectiveModelInfo() {
  if (state.selectedModels.size) {
    return {
      count: state.selectedModels.size,
      label: `${state.selectedModels.size} selected`,
    };
  }
  if (state.selectedGroup && state.groups[state.selectedGroup]) {
    const groupIds = state.groups[state.selectedGroup] || [];
    return {
      count: groupIds.length,
      label: `${state.selectedGroup} (${groupIds.length})`,
    };
  }
  const available = state.models.filter((model) => model.available);
  return {
    count: available.length,
    label: `all available (${available.length})`,
  };
}

export function buildCapabilityRows(quizMeta, modelCount) {
  if (!quizMeta) return [];
  const hasOutcomes = quizMeta.has_outcomes;
  const outcomeCount = quizMeta.outcome_count || 0;
  const choiceCount = quizMeta.choice_count || 0;
  const isSingle = modelCount === 1;
  const isMulti = modelCount > 1;

  const rows = [];
  const addRow = (label, ok, reason, variants = []) => {
    rows.push({
      label,
      ok,
      reason,
      variants,
    });
  };

  addRow("Report", true, "Generated for every run.");
  addRow(
    "CSV",
    true,
    hasOutcomes
      ? "Includes raw choices and outcomes CSVs."
      : "Includes raw choices CSV; outcomes CSV requires outcomes.",
    hasOutcomes ? ["choices", "outcomes"] : ["choices"]
  );
  addRow(
    "Bar chart",
    modelCount > 0,
    "Always generated; variant depends on model count and outcomes.",
    hasOutcomes && isMulti ? ["outcomes"] : ["choices"]
  );
  addRow(
    "Radar",
    isMulti && ((hasOutcomes && outcomeCount >= 3) || (!hasOutcomes && choiceCount >= 3)),
    !isMulti
      ? "Requires multiple models."
      : hasOutcomes
        ? outcomeCount < 3
          ? "Requires at least 3 outcomes."
          : "Generated for multi-model outcome quizzes."
        : choiceCount < 3
          ? "Requires at least 3 choices."
          : "Generated for multi-model, non-outcome quizzes.",
    hasOutcomes ? ["outcomes"] : ["choices"]
  );
  addRow(
    "Heatmap",
    isMulti && ((hasOutcomes && outcomeCount > 1) || (!hasOutcomes && choiceCount > 1)),
    !isMulti
      ? "Requires multiple models."
      : hasOutcomes
        ? outcomeCount <= 1
          ? "Requires more than 1 outcome."
          : "Generated for multi-model outcome quizzes."
        : choiceCount <= 1
          ? "Requires more than 1 choice."
          : "Generated for multi-model, non-outcome quizzes.",
    hasOutcomes ? ["outcomes"] : ["choices"]
  );
  addRow(
    "Matrix",
    isMulti && hasOutcomes,
    !isMulti
      ? "Requires multiple models."
      : hasOutcomes
        ? "Generated for multi-model outcome quizzes."
        : "Requires outcomes in the quiz YAML.",
    ["outcomes"]
  );
  return rows;
}

const outcomeConditionLabels = {
  mostly: "Mostly",
  mostlyTag: "Mostly tag",
  scoreRange: "Score range",
  score: "Score",
  tags: "Tags",
  tag: "Tag",
};

export function formatOutcomeCondition(outcome = {}) {
  const entries = [];
  const condition = outcome.condition && typeof outcome.condition === "object" ? outcome.condition : null;
  if (condition) {
    entries.push(...formatConditionEntries(condition));
  }
  const directKeys = ["mostly", "mostlyTag", "scoreRange", "score", "tags", "tag"];
  directKeys.forEach((key) => {
    if (outcome[key] !== undefined) {
      entries.push(`${outcomeConditionLabels[key] || key}: ${formatConditionValue(outcome[key])}`);
    }
  });
  const uniqueEntries = [...new Set(entries)];
  return uniqueEntries.length ? uniqueEntries.join(" · ") : "Always";
}

export function formatConditionEntries(condition = {}) {
  return Object.entries(condition).map(([key, value]) => {
    const label = outcomeConditionLabels[key] || key;
    return `${label}: ${formatConditionValue(value)}`;
  });
}

export function formatConditionValue(value) {
  if (value && typeof value === "object") {
    if (typeof value.min === "number" && typeof value.max === "number") {
      return `${value.min}-${value.max}`;
    }
    return JSON.stringify(value);
  }
  return String(value);
}

export function formatOptionDetails(option = {}) {
  const details = [];
  if (Array.isArray(option.tags) && option.tags.length) {
    details.push(`tags: ${option.tags.join(", ")}`);
  }
  if (typeof option.score === "number") {
    details.push(`score: ${option.score}`);
  }
  return details.length ? ` <span class=\"status\">(${details.join(" · ")})</span>` : "";
}

export function renderRawInput(rawPreview) {
  if (!rawPreview) {
    return "<div class=\"status\">Raw input not available.</div>";
  }
  if (rawPreview.type === "text") {
    return `<pre class=\"preview\">${rawPreview.text || ""}</pre>`;
  }
  if (rawPreview.type === "image" && rawPreview.data_url) {
    return `
      <div class=\"raw-image-frame\">
        <img src=\"${rawPreview.data_url}\" alt=\"Uploaded quiz image\" />
        <div class=\"status\">${rawPreview.filename || "Uploaded image"} (${rawPreview.mime || ""})</div>
      </div>
    `;
  }
  return "<div class=\"status\">Raw input not available.</div>";
}

export function renderQuizPreview(
  quiz,
  { quizYaml = null, rawPayload = null, rawPreview = null, quizMeta = null } = {}
) {
  const questions = quiz.questions || [];
  const items = questions
    .map((question, index) => {
      const qid = question.id || `q${index + 1}`;
      const options = (question.options || [])
        .map(
          (opt) =>
            `<li><strong>${opt.id || ""}</strong> ${opt.text || ""}${formatOptionDetails(opt)}</li>`
        )
        .join("");
      return `
        <div class=\"preview-item\">
          <div class=\"status\"><strong>${qid}.</strong> ${question.text || ""}</div>
          <ul>${options || "<li class='status'>No options listed.</li>"}</ul>
        </div>
      `;
    })
    .join("");

  const outcomes = (quiz.outcomes || [])
    .map((outcome) => {
      const title = outcome.id || outcome.text || outcome.description || "Outcome";
      const description = outcome.description || outcome.text || outcome.result || "";
      return `
        <li>
          <strong>${title}</strong>
          <div class=\"status\">${formatOutcomeCondition(outcome)}</div>
          <div>${description}</div>
        </li>
      `;
    })
    .join("");

  const yamlBlock = quizYaml
    ? `
      <details class=\"yaml-preview\">
        <summary>View YAML</summary>
        <pre class=\"preview\">${quizYaml}</pre>
      </details>
    `
    : "";

  const rawBlock = rawPayload
    ? `
      <details class=\"raw-preview\">
        <summary>View raw ${rawPreview?.type === "image" ? "image" : "text"}</summary>
        ${renderRawInput(rawPreview)}
      </details>
    `
    : "";

  const metaRows = [
    ["Quiz ID", quiz.id || ""],
    ["Type", getQuizTypeLabel(quiz, quizMeta)],
    ["Scoring", getScoringSummary(quiz, quizMeta)],
    ["Notes", quiz.notes || "—"],
    ["Raw backup", rawPayload ? `${rawPayload.type || "stored"}` : "Not stored"],
  ]
    .map(
      ([label, value]) => `
        <div>
          <div class=\"label\">${label}</div>
          <div>${value || "—"}</div>
        </div>
      `
    )
    .join("");

  return `
    <div class=\"meta-grid\">${metaRows}</div>
    <div class=\"preview-subsection\">
      <h4>Questions (${questions.length || 0})</h4>
      <div class=\"preview-list\">${items || "<div class='status'>No questions.</div>"}</div>
    </div>
    <div class=\"preview-subsection\">
      <h4>Outcomes & scoring</h4>
      <ul class=\"outcome-list\">${outcomes || "<li class='status'>No outcomes defined.</li>"}</ul>
    </div>
    ${rawBlock}
    ${yamlBlock}
  `;
}
