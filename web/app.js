// Faultline dashboard. Plain JavaScript, no build step.
// Each page is a function that fetches data and returns HTML.

const view = document.getElementById("view");
let CONFIG = null;

// ---------- icons (inline SVG, stroke style) ----------

const ICON_PATHS = {
  runs: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  alert: '<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17.5v.01"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3z"/><path d="m9 12 2 2 4-4"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/>',
  wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 0 0 5.2-5.4l-2.5 2.5-2.5-.5-.5-2.5 2.5-2.5z"/>',
  code: '<path d="m8 8-5 4 5 4M16 8l5 4-5 4M14 4l-4 16"/>',
  graph: '<circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="6" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M7.3 11 16.7 7M7.3 13l9.4 4"/>',
  quote: '<path d="M7 7h4v4H7zM7 11c0 3-1 5-3 6M15 7h4v4h-4zM15 11c0 3-1 5-3 6"/>',
  play: '<path d="M7 4v16l13-8L7 4z"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
  file: '<path d="M14 3H6v18h12V7l-4-4z"/><path d="M14 3v4h4"/>',
};

function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name] || ""}</svg>`;
}

function cardHead(title, iconName, right = "") {
  return `<div class="card-head"><h2><span class="ic">${icon(iconName)}</span>${title}</h2>${right}</div>`;
}

// ---------- helpers ----------

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let message = res.statusText;
    try { message = (await res.json()).detail || message; } catch (e) { /* not json */ }
    throw new Error(message);
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function pretty(value) {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function ms(value) {
  if (value >= 1000) return (value / 1000).toFixed(1) + " s";
  return Math.round(value) + " ms";
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.hidden = true; }, 2600);
}

function statusChip(status) {
  if (status === "success") return `<span class="chip good"><span class="dot"></span>success</span>`;
  return `<span class="chip bad"><span class="dot"></span>failed</span>`;
}

function classChip(cls) {
  if (!cls) return `<span class="chip">—</span>`;
  if (cls === "healthy") return `<span class="chip good">healthy</span>`;
  if (cls === "inconclusive") return `<span class="chip warn">inconclusive</span>`;
  return `<span class="chip cls">${esc(cls)}</span>`;
}

function emptyState(title, text, buttonHtml = "") {
  return `<div class="card empty"><h2>${esc(title)}</h2><p>${esc(text)}</p>${buttonHtml}</div>`;
}

// Hover tooltips: any element with data-tip shows it.
const tip = document.getElementById("tooltip");
document.addEventListener("mousemove", (e) => {
  const target = e.target.closest("[data-tip]");
  if (!target) { tip.hidden = true; return; }
  tip.innerHTML = target.dataset.tip;
  tip.hidden = false;
  const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 10);
  tip.style.left = x + "px";
  tip.style.top = (e.clientY + 14) + "px";
});

async function withBusy(button, label, work) {
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span> ${label}`;
  try {
    await work();
  } catch (err) {
    toast("Error: " + err.message);
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

// ---------- charts ----------

function horizontalBars(rows, { suffix = "", max = null } = {}) {
  if (!rows.length) return `<p class="note small">No data yet.</p>`;
  const top = max ?? Math.max(...rows.map((r) => r.value), 1);
  return `<div class="bars">${rows.map((r) => `
    <div class="bar-row" data-tip="<b>${esc(r.label)}</b><br>${r.value}${suffix}${r.extra ? "<br>" + esc(r.extra) : ""}">
      <span class="name">${esc(r.label)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${(100 * r.value) / top}%"></div></div>
      <span class="val">${r.value}${suffix}</span>
    </div>`).join("")}</div>`;
}

function runsPerDay(timeline) {
  if (!timeline.length) return `<p class="note small">No runs yet.</p>`;
  const top = Math.max(...timeline.map((d) => d.success + d.failed), 1);
  const cols = timeline.map((d) => {
    const label = new Date(d.day + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const tipText = `<b>${label}</b><br>${d.success} success · ${d.failed} failed`;
    return `<div class="col" data-tip="${esc(tipText)}">
      <div class="seg" style="height:${(100 * d.success) / top}%;background:var(--good)"></div>
      <div class="seg top" style="height:${(100 * d.failed) / top}%;background:var(--critical)"></div>
    </div>`;
  }).join("");
  const labels = timeline.map((d) =>
    `<span>${new Date(d.day + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>`).join("");
  return `<div class="columns">${cols}</div><div class="col-labels">${labels}</div>`;
}

// ---------- pages ----------

async function pageOverview() {
  const s = await api("/api/stats");
  if (!s.total_traces) {
    return emptyState("No traces yet", "Load 48 demo runs of a travel-booking agent, including 36 seeded failures.",
      `<button class="btn" id="seed-btn">Load demo data</button>`);
  }
  const evalAcc = s.eval ? s.eval.class_accuracy + "%" : "—";
  const kpis = [
    ["Agent runs", s.total_traces, "across all sources", "runs", "blue"],
    ["Failure rate", s.failure_rate + "%", `${s.failed_traces} failed runs`, "alert", "red"],
    ["Root causes found", s.root_causes_found, `${s.analyzed} runs investigated`, "search", "violet"],
    ["Fixes verified", s.fix_verified_rate + "%", "proven by replay", "shield", "green"],
    ["Eval accuracy", evalAcc, s.eval ? `${s.eval.mode} mode · ${s.eval.total} labeled` : "run an eval", "target", "aqua"],
    ["Time to root cause", ms(s.avg_investigation_ms), "average per run", "clock", "amber"],
  ];

  const classes = s.by_class.map((c) => ({ label: c.failure_class, value: c.count }));
  const clusters = s.clusters.map((c) => `
    <div class="cluster">
      <span class="count">${c.count}</span>
      <div class="what">
        <div>${classChip(c.failure_class)} <span class="mono">${esc(c.tool)}</span></div>
        <small>${c.count} runs share this root cause · e.g. <a href="#/trace/${esc(c.trace_ids[0])}">${esc(c.trace_ids[0])}</a></small>
      </div>
      <a class="btn ghost small" href="#/traces?cls=${encodeURIComponent(c.failure_class)}">View</a>
    </div>`).join("") || `<p class="note small">Run an analysis to group failures.</p>`;

  const recent = s.recent_failures.map((t) => `
    <tr class="clickable" data-href="#/trace/${esc(t.id)}">
      <td class="mono">${esc(t.id)}</td>
      <td class="task" style="max-width:220px" title="${esc(t.task)}">${esc(t.task)}</td>
      <td>${classChip(t.failure_class || (t.analyzed ? "inconclusive" : null))}</td>
      <td>${t.verified ? `<span class="chip good">verified</span>` : `<span class="chip">—</span>`}</td>
      <td class="num">${when(t.created_at)}</td>
    </tr>`).join("");

  return `
    <section class="hero">
      <div>
        <span class="eyebrow"><span class="dot"></span> Agent failure forensics</span>
        <h1>Observability shows <i>what</i> happened.<br><span class="gradient-text">Faultline tells you why.</span></h1>
        <p class="sub">Every failed run goes through a 7-agent investigation: root cause with evidence, a fix proven by replay, and a regression test.</p>
        <div class="hero-flow">
          ${["triage", "researcher", "investigator", "critic", "fixer", "replayer", "test_writer"].map((n, i) =>
            `${i ? "<i>→</i>" : ""}<span>${n}</span>`).join("")}
        </div>
      </div>
      <div class="actions">
        <button class="btn ghost" id="seed-btn">${icon("refresh")} Reset demo data</button>
        <button class="btn" id="analyze-all-btn">${icon("play")} Investigate all runs</button>
      </div>
    </section>
    <div class="grid kpis">
      ${kpis.map(([label, value, foot, ic, tone]) => `
        <div class="card kpi tone-${tone}">
          <div class="top"><span class="label">${label}</span><span class="ic">${icon(ic)}</span></div>
          <div class="value">${value}</div><div class="foot">${foot}</div></div>`).join("")}
    </div>
    <div class="grid two" style="margin-top:16px">
      <div class="card">
        <div class="card-head"><h2><span class="ic">${icon("chart")}</span>Runs per day</h2>
          <div class="legend"><span><i style="background:var(--good)"></i>Success</span><span><i style="background:var(--critical)"></i>Failed</span></div>
        </div>
        <div class="card-body">${runsPerDay(s.timeline)}</div>
      </div>
      <div class="card">
        ${cardHead("Root causes by class", "layers", `<span class="hint">investigated runs</span>`)}
        <div class="card-body">${horizontalBars(classes)}</div>
      </div>
    </div>
    <div class="grid two" style="margin-top:16px">
      <div class="card">
        ${cardHead("Recent failures", "alert", `<a href="#/traces?status=failed" class="hint">All failures →</a>`)}
        <div class="card-body table-wrap" style="padding-top:6px">
          <table><thead><tr><th>Run</th><th>Task</th><th>Root cause</th><th>Fix</th><th style="text-align:right">When</th></tr></thead>
          <tbody>${recent}</tbody></table>
        </div>
      </div>
      <div class="card">
        ${cardHead("Failure clusters", "graph", `<span class="hint">same class + same tool</span>`)}
        <div class="card-body">${clusters}</div>
      </div>
    </div>`;
}

async function pageTraces(params) {
  const traces = await api("/api/traces");
  if (!traces.length) {
    return emptyState("No traces yet", "Load demo data or import from Langfuse / LangSmith.",
      `<button class="btn" id="seed-btn">Load demo data</button>`);
  }
  const classes = [...new Set(traces.map((t) => t.failure_class).filter(Boolean))].sort();
  const status = params.get("status") || "";
  const cls = params.get("cls") || "";
  const q = params.get("q") || "";

  let rows = traces;
  if (status) rows = rows.filter((t) => t.status === status);
  if (cls) rows = rows.filter((t) => t.failure_class === cls);
  if (q) rows = rows.filter((t) => (t.id + " " + t.task).toLowerCase().includes(q.toLowerCase()));

  const body = rows.map((t) => `
    <tr class="clickable" data-href="#/trace/${esc(t.id)}">
      <td class="mono">${esc(t.id)}</td>
      <td>${statusChip(t.status)}</td>
      <td class="task" title="${esc(t.task)}">${esc(t.task)}</td>
      <td>${t.multi_agent ? `<span class="chip info">multi-agent</span>` : `<span class="chip">single</span>`}</td>
      <td class="num">${t.steps}</td>
      <td class="num">${t.errors}</td>
      <td class="num">${ms(t.latency_ms)}</td>
      <td>${t.analyzed ? classChip(t.failure_class || (t.status === "success" ? "healthy" : "inconclusive")) : `<span class="chip warn">not analyzed</span>`}</td>
      <td class="num">${when(t.created_at)}</td>
    </tr>`).join("");

  return `
    <div class="page-head">
      <div><h1>Traces</h1><p class="sub">${rows.length} of ${traces.length} agent runs</p></div>
      <div class="actions"><button class="btn" id="analyze-all-btn">Investigate all runs</button></div>
    </div>
    <div class="filters">
      <input id="f-q" placeholder="Search id or task…" value="${esc(q)}">
      <select id="f-status">
        <option value="">All statuses</option>
        <option value="failed" ${status === "failed" ? "selected" : ""}>Failed</option>
        <option value="success" ${status === "success" ? "selected" : ""}>Success</option>
      </select>
      <select id="f-cls">
        <option value="">All root causes</option>
        ${classes.map((c) => `<option ${c === cls ? "selected" : ""}>${esc(c)}</option>`).join("")}
      </select>
    </div>
    <div class="card table-wrap">
      <table>
        <thead><tr><th>Run</th><th>Status</th><th>Task</th><th>Agents</th><th style="text-align:right">Steps</th>
          <th style="text-align:right">Errors</th><th style="text-align:right">Duration</th><th>Root cause</th><th style="text-align:right">When</th></tr></thead>
        <tbody>${body || `<tr><td colspan="9" class="note">No traces match these filters.</td></tr>`}</tbody>
      </table>
    </div>`;
}

function renderStep(step, autopsy, multiAgent) {
  const rootStep = autopsy && autopsy.root_cause ? autopsy.root_cause.root_cause_step : null;
  const affected = autopsy ? autopsy.affected_steps : [];
  let cls = "";
  let tag = "";
  if (step.index === rootStep) {
    cls = "root";
    tag = `<span class="chip bad">root cause</span>`;
  } else if (affected.includes(step.index)) {
    cls = "affected";
    tag = `<span class="chip warn">impact</span>`;
  }
  return `
    <div class="step ${cls}" id="step-${step.index}">
      <div class="step-head" data-toggle="${step.index}">
        <span class="step-node ${esc(step.type)}">${step.index}</span>
        <span class="step-type ${esc(step.type)}">${esc(step.type)}</span>
        <span class="step-name">${esc(step.name)}</span>
        ${multiAgent ? `<span class="chip">${esc(step.agent)}</span>` : ""}
        ${tag}
        <span class="step-spacer"></span>
        <span class="step-ms">${ms(step.latency_ms)}</span>
      </div>
      ${step.error ? `<div class="step-error">✕ ${esc(step.error)}</div>` : ""}
      <div class="step-body">
        <div class="kv"><label>Input</label><pre class="code">${esc(pretty(step.input))}</pre></div>
        <div class="kv"><label>Output</label><pre class="code">${esc(pretty(step.output))}</pre></div>
      </div>
    </div>`;
}

function renderAutopsy(trace, a) {
  if (!a) {
    return `<div class="card empty"><h2>Not investigated yet</h2>
      <p>Run the 7-agent investigation pipeline on this trace.</p>
      <button class="btn" id="analyze-btn">Run autopsy</button></div>`;
  }

  let verdict;
  if (a.root_cause) {
    const r = a.root_cause;
    verdict = `
      <div class="verdict bad">
        <div class="eyebrow">Root cause · step #${r.root_cause_step}</div>
        <h2>${esc(r.title)}</h2>
        <div style="margin-bottom:8px">${classChip(r.failure_class)}</div>
        <p>${esc(r.explanation)}</p>
        <div class="confidence"><span>Confidence</span>
          <div class="track"><div class="fill" style="width:${Math.round(r.confidence * 100)}%"></div></div>
          <b>${Math.round(r.confidence * 100)}%</b></div>
      </div>`;
  } else if (a.verdict === "healthy") {
    verdict = `<div class="verdict good"><div class="eyebrow">Verdict</div><h2>Healthy run</h2>
      <p>No serious failure signals. ${a.signals.length ? `${a.signals.length} informational signal(s) below.` : ""}</p></div>`;
  } else {
    verdict = `<div class="verdict unknown"><div class="eyebrow">Verdict</div><h2>Inconclusive</h2>
      <p>The run failed but the deterministic detectors found no known failure pattern. This usually means a
      semantic problem (wrong intent, wrong entity). Enable LLM mode to let Claude investigate it.</p></div>`;
  }

  const evidence = a.root_cause && a.root_cause.evidence.length ? `
    <div class="card">${cardHead("Evidence", "quote", `<span class="hint">click to jump to step</span>`)}
      <div class="card-body evidence">
        ${a.root_cause.evidence.map((e) => `
          <button data-jump="${e.step_index}"><span class="where">step #${e.step_index}</span>
          <span class="quote">${esc(e.quote)}</span></button>`).join("")}
      </div></div>` : "";

  const pipeline = `
    <div class="card">${cardHead("Investigation", "graph", `<span class="hint">${esc(a.mode)} mode · ${ms(a.duration_ms)}</span>`)}
      <div class="card-body pipeline">
        ${a.investigation.map((n, i) => `
          ${i ? `<span class="arrow">→</span>` : ""}
          <div class="node ${a.mode === "llm" && (n.node === "investigator" || n.node === "fixer") ? "llm" : ""}"
               data-tip="<b>${esc(n.node)}</b><br>${esc(n.note)}<br>${n.ms} ms">
            <b>${esc(n.node)}</b><small>${esc(n.note)}</small></div>`).join("")}
      </div></div>`;

  const fix = a.fix ? `
    <div class="card">${cardHead("Proposed fix", "wrench",
      a.replay && a.replay.verified ? `<span class="chip good">✓ verified by replay</span>` : `<span class="chip warn">not verified</span>`)}
      <div class="card-body">
        <div style="margin-bottom:6px"><span class="chip info mono">${esc(a.fix.kind)}</span></div>
        <p class="note">${esc(a.fix.summary)}</p>
        ${a.fix.details && a.fix.details.code_change ? `<div class="kv"><label>Suggested change</label><pre class="code">${esc(a.fix.details.code_change)}</pre></div>` : ""}
        ${a.replay ? `<div class="replay-log"><div><b>${esc(a.replay.method)}</b></div>${a.replay.log.map((l) => `<div class="${/BLOCKED/.test(l) ? "blocked" : /: ok|allowed|result:/.test(l) ? "ok" : ""}">${esc(l)}</div>`).join("")}</div>` : ""}
      </div></div>` : "";

  const test = a.regression_test ? `
    <div class="card">${cardHead("Regression test", "code", `
      <div class="actions"><button class="btn ghost small" id="copy-test">Copy</button>
      <a class="btn ghost small" href="/api/traces/${esc(trace.id)}/regression-test">Download .py</a></div>`)}
      <div class="card-body"><pre class="code" id="test-code">${esc(a.regression_test)}</pre></div></div>` : "";

  const others = a.other_hypotheses.length ? `
    <div class="card">${cardHead("Other hypotheses", "layers", `<span class="hint">likely symptoms</span>`)}
      <div class="card-body">${a.other_hypotheses.map((h) => `
        <div style="margin-bottom:8px">${classChip(h.failure_class)} <b>${esc(h.title)}</b>
        <span class="note small">· step #${h.root_cause_step} · ${Math.round(h.confidence * 100)}%</span></div>`).join("")}
      </div></div>` : "";

  const similar = a.similar.length ? `
    <div class="card">${cardHead("Similar past incidents", "history", `<span class="hint">BM25 retrieval</span>`)}
      <div class="card-body">${a.similar.map((s) => `
        <div style="margin-bottom:6px"><a href="#/trace/${esc(s.id)}" class="mono">${esc(s.id)}</a>
        <span class="note"> ${esc(s.title)}</span> <span class="note small">score ${s.score}</span></div>`).join("")}
      </div></div>` : "";

  const signals = a.signals.length ? `
    <div class="card">${cardHead("Detector signals", "search", `<span class="hint">deterministic</span>`)}
      <div class="card-body">${a.signals.map((s) => `
        <div style="margin-bottom:8px">${classChip(s.failure_class)}
          <span class="chip ${s.severity >= 3 ? "bad" : s.severity === 2 ? "warn" : ""}">sev ${s.severity}</span>
          <span class="note small">step #${s.step_index}</span>
          <div class="note">${esc(s.message)}</div></div>`).join("")}
      </div></div>` : "";

  return `<div class="stack">${verdict}${evidence}${fix}${pipeline}${test}${others}${signals}${similar}
    <div class="actions"><button class="btn ghost small" id="analyze-btn">Re-run autopsy</button>
    ${trace.source === "langfuse" || trace.source === "langsmith" ? `<button class="btn ghost small" id="push-btn">Push verdict to ${esc(trace.source)}</button>` : ""}</div></div>`;
}

async function pageTrace(id) {
  const { trace, autopsy } = await api("/api/traces/" + encodeURIComponent(id));
  const multiAgent = new Set(trace.steps.map((s) => s.agent)).size > 1;
  const total = trace.steps.reduce((sum, s) => sum + s.latency_ms, 0);
  const label = trace.label && trace.label.scenario ? `<span class="chip" data-tip="Ground truth from the simulator: ${esc(trace.label.failure_class || "healthy")} at step ${esc(trace.label.root_cause_step ?? "-")}">scenario: ${esc(trace.label.scenario)}</span>` : "";

  return `
    <div class="page-head">
      <div>
        <a href="#/traces" class="note small">← Traces</a>
        <h1 class="mono" style="margin-top:4px">${esc(trace.id)}</h1>
        <p class="sub">${esc(trace.task)}</p>
        <div class="trace-meta">
          ${statusChip(trace.status)}
          <span class="chip">${esc(trace.agent_name)}</span>
          <span class="chip">source: ${esc(trace.source)}</span>
          <span class="chip">${trace.steps.length} steps · ${ms(total)}</span>
          ${multiAgent ? `<span class="chip info">multi-agent</span>` : ""}
          ${label}
        </div>
      </div>
    </div>
    <div class="grid split">
      <div class="stack">
        <div class="card">${cardHead("Execution timeline", "runs", `<span class="hint">click a step to expand</span>`)}
          <div class="card-body timeline">${trace.steps.map((s) => renderStep(s, autopsy, multiAgent)).join("")}</div></div>
        <div class="card">${cardHead("Final output", "file")}
          <div class="card-body"><pre class="code">${esc(pretty(trace.final_output))}</pre>
          ${trace.expected_output_keys.length ? `<p class="note small" style="margin-top:8px">Expected JSON keys: ${trace.expected_output_keys.map(esc).join(", ")}</p>` : ""}</div></div>
      </div>
      ${renderAutopsy(trace, autopsy)}
    </div>`;
}

async function pageEval() {
  const e = await api("/api/eval");
  const llmOk = CONFIG && CONFIG.llm_available;
  const buttons = `
    <button class="btn ghost" id="eval-rules">Run eval · rules</button>
    <button class="btn" id="eval-llm" ${llmOk ? "" : "disabled"} title="${llmOk ? "" : "Set ANTHROPIC_API_KEY and FAULTLINE_MODE=llm"}">Run eval · Claude</button>`;
  if (!e) {
    return `<div class="page-head"><div><h1>Evaluation</h1></div><div class="actions">${buttons}</div></div>
      ${emptyState("No evaluation yet", "Run Faultline against every labeled trace and measure how often it finds the true root cause.")}`;
  }
  const big = [
    ["Root-cause class accuracy", e.class_accuracy + "%", `${e.failed_runs} failed runs`, "target", "violet"],
    ["Class + step accuracy", e.step_accuracy + "%", "exact first domino", "search", "blue"],
    ["False positive rate", e.false_positive_rate + "%", `${e.healthy_runs} healthy runs`, "alert", "red"],
    ["Fixes verified by replay", e.fix_verified_rate + "%", "of correct diagnoses", "shield", "green"],
  ];
  const rows = e.per_class.map((c) => ({ label: c.failure_class, value: c.class_accuracy, extra: `n=${c.n} · step accuracy ${c.step_accuracy}%` }));
  const misses = e.misses.map((m) => `
    <tr class="clickable" data-href="#/trace/${esc(m.trace_id)}">
      <td class="mono">${esc(m.trace_id)}</td><td class="mono">${esc(m.scenario)}</td>
      <td>${classChip(m.expected)}</td><td>${classChip(m.got)}</td></tr>`).join("");

  return `
    <div class="page-head">
      <div><h1>Evaluation</h1>
        <p class="sub">Every demo trace carries a ground-truth label because the failure was injected on purpose.
        Last run: <b>${esc(e.mode)}</b> mode, ${e.total} traces, ${e.avg_ms_per_trace} ms per trace, ${when(e.created_at)}.</p></div>
      <div class="actions">${buttons}</div>
    </div>
    <div class="grid kpis" style="grid-template-columns:repeat(4,minmax(0,1fr))">
      ${big.map(([l, v, f, ic, tone]) => `<div class="card kpi tone-${tone}"><div class="top"><span class="label">${l}</span><span class="ic">${icon(ic)}</span></div><div class="metric-big">${v}</div><div class="foot">${f}</div></div>`).join("")}
    </div>
    <div class="grid two" style="margin-top:16px">
      <div class="card">${cardHead("Accuracy by failure class", "chart", `<span class="hint">class accuracy</span>`)}
        <div class="card-body">${horizontalBars(rows, { suffix: "%", max: 100 })}
        <div class="table-wrap" style="margin-top:14px"><table>
          <thead><tr><th>Class</th><th style="text-align:right">n</th><th style="text-align:right">Class</th><th style="text-align:right">Step</th></tr></thead>
          <tbody>${e.per_class.map((c) => `<tr><td class="mono">${esc(c.failure_class)}</td><td class="num">${c.n}</td>
            <td class="num">${c.class_accuracy}%</td><td class="num">${c.step_accuracy}%</td></tr>`).join("")}</tbody></table></div>
        </div></div>
      <div class="card">${cardHead("Misses", "alert", `<span class="hint">${e.misses.length} traces</span>`)}
        <div class="card-body">
          <p class="note" style="margin-bottom:10px">Two scenarios are <b>semantic</b> on purpose (wrong city, a
          "direct flight" claim that contradicts the data). Arguments are valid and nothing errors, so rules cannot see them.
          That gap is what the Claude investigator exists to close.</p>
          <div class="table-wrap"><table><thead><tr><th>Run</th><th>Scenario</th><th>Expected</th><th>Got</th></tr></thead>
          <tbody>${misses || `<tr><td colspan="4" class="note">No misses.</td></tr>`}</tbody></table></div>
        </div></div>
    </div>`;
}

async function pageIntegrations() {
  const example = {
    id: "my-run-001", agent_name: "support-bot", task: "Refund order 4417", status: "failed",
    tools: [{ name: "get_order", params: { order_id: "str" }, required: ["order_id"] }],
    steps: [{ index: 0, type: "tool", name: "get_order", input: { id: "4417" }, error: "missing argument order_id" }],
    final_output: "Sorry, I could not find your order.",
  };
  const nodes = [
    ["triage", "7 deterministic detectors"], ["researcher", "BM25 RAG: playbooks + past incidents"],
    ["investigator", "hypotheses + evidence (Claude or rules)"], ["critic", "rejects ungrounded evidence"],
    ["fixer", "maps root cause to a guard"], ["replayer", "re-runs with the fix in a sandbox"],
    ["test_writer", "pytest regression test"],
  ];
  return `
    <div class="page-head"><div><h1>Integrations</h1>
      <p class="sub">Pull failed traces from your observability stack, investigate them here, and push the verdict back.</p></div></div>
    <div class="grid two">
      <div class="stack">
        <div class="card"><div class="card-body integration">
          <span class="logo-tile" style="background:linear-gradient(135deg,#eb6834,#e34948)">LF</span>
          <div><div style="display:flex;gap:8px;align-items:center;margin-bottom:4px"><h2>Langfuse</h2><span class="chip">REST API</span></div>
            <p class="note">Set <code>LANGFUSE_PUBLIC_KEY</code>, <code>LANGFUSE_SECRET_KEY</code> and optionally <code>LANGFUSE_HOST</code> in <code>.env</code>.
            Verdicts are written back as a categorical score named <code>faultline_root_cause</code>.</p>
            <div class="actions" style="margin-top:12px"><button class="btn" data-import="langfuse">${icon("upload")} Import failed traces</button></div>
          </div></div></div>
        <div class="card"><div class="card-body integration">
          <span class="logo-tile" style="background:linear-gradient(135deg,#1baf7a,#2a78d6)">LS</span>
          <div><div style="display:flex;gap:8px;align-items:center;margin-bottom:4px"><h2>LangSmith</h2><span class="chip">Python SDK</span></div>
            <p class="note">Install <code>langsmith</code>, set <code>LANGSMITH_API_KEY</code> and <code>LANGSMITH_PROJECT</code>.
            Verdicts are written back as run feedback.</p>
            <div class="actions" style="margin-top:12px"><button class="btn" data-import="langsmith">${icon("upload")} Import failed traces</button></div>
          </div></div></div>
        <div class="card">${cardHead("Investigation graph", "graph", `<span class="hint">LangGraph StateGraph</span>`)}
          <div class="card-body pipeline">
            ${nodes.map(([n, d], i) => `${i ? `<span class="arrow">→</span>` : ""}<div class="node" data-tip="${esc(d)}"><b>${n}</b><small>${esc(d)}</small></div>`).join("")}
            <p class="note small" style="width:100%;margin-top:8px">critic → investigator loops back (max 2 attempts) when the evidence cannot be found in the trace.</p>
          </div></div>
      </div>
      <div class="card">${cardHead("Upload a trace", "upload", `<span class="hint">Faultline JSON format</span>`)}
        <div class="card-body">
          <textarea id="upload-json">${esc(JSON.stringify(example, null, 2))}</textarea>
          <div class="actions" style="margin-top:10px">
            <input type="file" id="upload-file" accept=".json" class="note small">
            <button class="btn" id="upload-btn">Upload &amp; investigate</button>
          </div>
        </div></div>
    </div>`;
}

// ---------- router ----------

async function route() {
  const hash = location.hash || "#/";
  const [path, query] = hash.slice(1).split("?");
  const params = new URLSearchParams(query || "");
  const parts = path.split("/").filter(Boolean);
  const page = parts[0] || "overview";

  document.querySelectorAll("[data-nav]").forEach((a) => {
    const active = a.dataset.nav === page || (page === "trace" && a.dataset.nav === "traces");
    a.classList.toggle("active", active);
  });

  view.innerHTML = `<p class="note"><span class="spinner"></span> Loading…</p>`;
  try {
    if (page === "traces") view.innerHTML = await pageTraces(params);
    else if (page === "trace") view.innerHTML = await pageTrace(decodeURIComponent(parts[1]));
    else if (page === "eval") view.innerHTML = await pageEval();
    else if (page === "integrations") view.innerHTML = await pageIntegrations();
    else view.innerHTML = await pageOverview();
    document.title = "Faultline · " + (page === "trace" ? parts[1] : page[0].toUpperCase() + page.slice(1));
    window.scrollTo(0, 0);
  } catch (err) {
    view.innerHTML = emptyState("Something went wrong", err.message);
  }
}

// One click handler for the whole app (event delegation).
document.addEventListener("click", async (e) => {
  const row = e.target.closest("tr[data-href]");
  if (row && !e.target.closest("a")) { location.hash = row.dataset.href; return; }

  const toggle = e.target.closest("[data-toggle]");
  if (toggle) { toggle.parentElement.classList.toggle("open"); return; }

  const jump = e.target.closest("[data-jump]");
  if (jump) {
    const el = document.getElementById("step-" + jump.dataset.jump);
    if (el) {
      el.classList.add("open", "flash");
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(() => el.classList.remove("flash"), 1400);
    }
    return;
  }

  const btn = e.target.closest("button");
  if (!btn) return;

  if (btn.id === "seed-btn") {
    await withBusy(btn, "Loading…", async () => {
      await api("/api/seed", { method: "POST" });
      toast("Demo data loaded");
      route();
    });
  } else if (btn.id === "analyze-all-btn") {
    await withBusy(btn, "Investigating…", async () => {
      const r = await api("/api/analyze-all", { method: "POST" });
      toast(`Investigated ${r.analyzed} runs`);
      route();
    });
  } else if (btn.id === "analyze-btn") {
    const id = decodeURIComponent(location.hash.split("/")[2]);
    await withBusy(btn, "Investigating…", async () => {
      await api(`/api/traces/${encodeURIComponent(id)}/analyze`, { method: "POST" });
      route();
    });
  } else if (btn.id === "push-btn") {
    const id = decodeURIComponent(location.hash.split("/")[2]);
    await withBusy(btn, "Pushing…", async () => {
      await api(`/api/traces/${encodeURIComponent(id)}/push`, { method: "POST" });
      toast("Verdict pushed");
    });
  } else if (btn.id === "copy-test") {
    await navigator.clipboard.writeText(document.getElementById("test-code").textContent);
    toast("Test copied");
  } else if (btn.id === "eval-rules" || btn.id === "eval-llm") {
    const mode = btn.id === "eval-llm" ? "llm" : "rules";
    await withBusy(btn, "Evaluating…", async () => {
      await api("/api/eval?mode=" + mode, { method: "POST" });
      route();
    });
  } else if (btn.dataset.import) {
    await withBusy(btn, "Importing…", async () => {
      const r = await api("/api/import/" + btn.dataset.import, { method: "POST" });
      toast(`Imported ${r.imported} traces`);
    });
  } else if (btn.id === "upload-btn") {
    await withBusy(btn, "Uploading…", async () => {
      const trace = JSON.parse(document.getElementById("upload-json").value);
      trace.source = trace.source || "upload";
      const r = await api("/api/traces", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(trace),
      });
      await api(`/api/traces/${encodeURIComponent(r.id)}/analyze`, { method: "POST" });
      location.hash = "#/trace/" + r.id;
    });
  } else if (btn.id === "theme-toggle") {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("faultline-theme", root.dataset.theme); } catch (err) { /* storage blocked */ }
  }
});

document.addEventListener("change", async (e) => {
  if (e.target.id === "upload-file" && e.target.files[0]) {
    document.getElementById("upload-json").value = await e.target.files[0].text();
  }
  if (e.target.id === "f-status" || e.target.id === "f-cls") updateFilters();
});
document.addEventListener("keydown", (e) => {
  if (e.target.id === "f-q" && e.key === "Enter") updateFilters();
});

function updateFilters() {
  const params = new URLSearchParams();
  const q = document.getElementById("f-q").value.trim();
  const status = document.getElementById("f-status").value;
  const cls = document.getElementById("f-cls").value;
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  if (cls) params.set("cls", cls);
  location.hash = "#/traces" + (params.toString() ? "?" + params : "");
}

async function boot() {
  try {
    const saved = localStorage.getItem("faultline-theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch (err) { /* storage blocked */ }
  try {
    CONFIG = await api("/api/config");
    const label = CONFIG.mode === "llm" ? `Claude · ${CONFIG.model}` : "Rules (offline)";
    document.getElementById("mode-badge").innerHTML = `<span class="live"></span>Investigator: <b>${esc(label)}</b><br><span class="note small">v${esc(CONFIG.version)}</span>`;
  } catch (err) { /* API down: pages show the error */ }
  window.addEventListener("hashchange", route);
  route();
}

boot();
