/*
 * Agent Optimization Console — view logic (ADR-0010 agents × dimensions surface).
 * Renders the scorecard, discovered opportunities, and the C1–C5 governed actions.
 * Data access lives in api.js; styles in console.css. This file only builds the DOM.
 */
import { OptimizationApi } from "./api.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (n) => `$${Number(n || 0).toFixed(4)}`;

let api = null;

function toast(msg, kind = "good") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

function setError(msg) { $("error").innerHTML = msg ? `<div class="err">${esc(msg)}</div>` : ""; }

// --- scorecard ---
export function renderScorecard(data) {
  const el = $("scorecard");
  const agents = data.agents || [];
  if (!agents.length) {
    el.innerHTML = `<div class="panel muted">No node-grain telemetry for this tenant yet. Drive some turns, then Refresh.</div>`;
    return;
  }
  const pending = agents[0].pending_dimensions || {};
  el.innerHTML = agents.map((a) => {
    const dims = Object.entries(a.dimensions || {}).map(([name, d]) => `
      <div class="dim-cell">
        <div class="dn">${esc(name.replace(/_/g, " "))} <span class="badge ${esc(d.status)}">${esc(d.status)}</span></div>
        <div class="dh">${esc(d.headline)}</div>
      </div>`).join("");
    return `<div class="card">
      <div class="row">
        <h3 style="margin:0">${esc(a.agent)}</h3>
        <span class="badge ${esc(a.status)}">${esc(a.status)}</span>
        <span class="spacer"></span>
        <span class="muted">${money(a.cost)} · ${(a.cost_share * 100).toFixed(0)}% of spend · ${a.executions} exec / ${a.turns} turn</span>
      </div>
      <div class="dims">${dims}</div>
    </div>`;
  }).join("") +
  `<div class="note">Not yet scored (needs more signal): ${Object.keys(pending).map((k) => `<code>${esc(k)}</code>`).join(" ")}</div>`;
}

// --- opportunities (C1, C2, C4) ---
export function renderOpportunities(data) {
  const el = $("opportunities");
  const opps = data.opportunities || [];
  $("slo-summary").textContent =
    `SLO ${data.slo.slo} · min-confidence ${data.slo.min_confidence} · min-effect ${data.slo.min_effect} · total spend ${money(data.total_spend)}`;
  if (!opps.length) {
    el.innerHTML = `<div class="panel muted">No opportunities discovered from the current telemetry.</div>`;
    return;
  }
  el.innerHTML = opps.map((o) => {
    const staged = o.apply_mode !== "auto";
    return `<div class="card">
      <div class="row">
        <h3 style="margin:0">${esc(o.opportunity_id)}</h3>
        <span class="badge ${esc(o.governed_state)}">${esc(o.governed_state)}</span>
        <span class="badge ${o.clears_slo ? "ok" : "na"}">${o.clears_slo ? "clears SLO" : "below SLO"}</span>
      </div>
      <div class="dim">${esc(o.agent)} · ${esc(o.dimension)} · seam <code>${esc(o.seam)}</code> → <code>${esc(o.target)}</code></div>
      <div class="ev">
        <div><span class="evk">Engine-computed saving</span><span class="evv">${money(o.saving)}</span></div>
        <div><span class="evk">Effect (of spend)</span><span class="evv">${(o.effect * 100).toFixed(1)}%</span></div>
        <div><span class="evk">Apply mode</span><span class="evv">${esc(o.apply_mode)}</span></div>
        <div><span class="evk">Autonomy ceiling</span><span class="evv">${esc(o.autonomy_ceiling)}</span></div>
      </div>
      ${staged ? `<div class="caveat">Staged change — human-attested, never auto-applied.</div>` : ""}
      <div class="actions">
        <button class="ghost" data-act="diff" data-oid="${esc(o.opportunity_id)}">Review diff</button>
        <button class="good" data-act="approve" data-oid="${esc(o.opportunity_id)}">Approve</button>
        <button class="ghost" data-act="reject" data-oid="${esc(o.opportunity_id)}">Reject</button>
        <button data-act="attest" data-oid="${esc(o.opportunity_id)}">Attest deploy</button>
        <button class="danger" data-act="confirm-revert" data-oid="${esc(o.opportunity_id)}">Confirm revert</button>
      </div>
      <pre data-diff="${esc(o.opportunity_id)}" style="display:none"></pre>
    </div>`;
  }).join("");

  el.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.addEventListener("click", () => onOpportunityAction(btn.dataset.act, btn.dataset.oid));
  });
}

async function onOpportunityAction(act, oid) {
  try {
    if (act === "diff") {
      const pre = document.querySelector(`pre[data-diff="${CSS.escape(oid)}"]`);
      if (pre.style.display === "block") { pre.style.display = "none"; return; }
      const d = await api.diff(oid);
      pre.textContent = d.diff || JSON.stringify(d.policy_doc || d, null, 2);
      pre.style.display = "block";
      return;
    }
    const by = $("actor").value || "console";
    await api.decide(oid, act, by, null);
    toast(`Recorded "${act}" on ${oid} by ${by}`);
    await loadOpportunities();
    await loadDecisions();
  } catch (e) { toast(e.message, "bad"); }
}

// --- SLO policy (C3) ---
function renderSlo(slo) {
  $("slo-slo").value = slo.slo;
  $("slo-conf").value = slo.min_confidence;
  $("slo-effect").value = slo.min_effect;
}

async function onSaveSlo() {
  try {
    const saved = await api.setSlo(
      parseFloat($("slo-slo").value), parseFloat($("slo-conf").value),
      parseFloat($("slo-effect").value), $("actor").value || "console");
    toast(`SLO policy saved (min-effect ${saved.min_effect})`);
    await loadOpportunities();   // the engine re-gates opportunities against the new policy
  } catch (e) { toast(e.message, "bad"); }
}

// --- schema declaration (C5) ---
async function onDeclareSchema() {
  try {
    const payload = JSON.parse($("schema-json").value);
    payload.by = $("actor").value || "learner";
    const res = await api.declareSchema(payload);
    $("schema-result").textContent = JSON.stringify(res, null, 2);
    $("schema-result").style.display = "block";
    toast(res.accepted ? `Schema "${res.domain}" declared & bound (${res.binding_status})`
                        : `Schema declared; binding: ${res.binding_status}`, res.accepted ? "good" : "bad");
    await loadSchemas();
  } catch (e) { toast(e.message, "bad"); }
}

// --- audit trail ---
export function renderDecisions(data) {
  const rows = data.decisions || [];
  $("audit").innerHTML = rows.length
    ? `<table><thead><tr><th>When</th><th>Action</th><th>Opportunity</th><th>By</th><th>Note</th></tr></thead><tbody>${
        rows.map((d) => `<tr><td>${esc((d.timeStamp || "").replace("T", " ").slice(0, 19))}</td>
          <td><span class="badge ${esc(d.kind)}">${esc(d.kind)}</span></td>
          <td>${esc(d.subject)}</td><td>${esc(d.by)}</td><td>${esc(d.payload?.note || "")}</td></tr>`).join("")
      }</tbody></table>`
    : `<div class="muted">No governed decisions recorded yet.</div>`;
}

export function renderSchemas(data) {
  const rows = data.schemas || [];
  $("schemas").innerHTML = rows.length
    ? rows.map((s) => {
        const knobs = (s.manifest && s.manifest[s.domain] && s.manifest[s.domain].knobs) || [];
        return `<div class="dim-cell"><div class="dn">${esc(s.domain)}</div>
          <div class="dh muted">knobs: ${esc(knobs.join(", ")) || "—"}</div></div>`;
      }).join("")
    : `<div class="muted">No learner-declared schemas yet.</div>`;
}

// --- loaders ---
async function loadScorecard() { renderScorecard(await api.scorecard()); }
async function loadOpportunities() { renderOpportunities(await api.opportunities()); }
async function loadDecisions() { renderDecisions(await api.decisions()); }
async function loadSlo() { renderSlo(await api.slo()); }
async function loadSchemas() { renderSchemas(await api.schemas()); }

async function refreshAll() {
  setError("");
  api = new OptimizationApi($("api").value, $("tenant").value);
  try {
    await Promise.all([loadSlo(), loadScorecard(), loadOpportunities(), loadDecisions(), loadSchemas()]);
  } catch (e) { setError(e.message); }
}

function wire() {
  $("refresh").addEventListener("click", refreshAll);
  $("tenant").addEventListener("keydown", (e) => { if (e.key === "Enter") refreshAll(); });
  $("slo-save").addEventListener("click", onSaveSlo);
  $("schema-declare").addEventListener("click", onDeclareSchema);
  refreshAll();
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", wire);
}
