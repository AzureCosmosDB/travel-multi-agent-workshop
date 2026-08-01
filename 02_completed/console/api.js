/*
 * OptimizationApi — a thin client for the agent-centric optimization endpoints
 * (src/app/optimization_agent_api.py). Kept separate from the view logic so the
 * console stays small and each file has one job.
 */
export class OptimizationApi {
  constructor(base, tenant) {
    this.base = base.replace(/\/$/, "");
    this.tenant = tenant;
  }

  _agent(path) {
    return `${this.base}/optimizations/agent/${encodeURIComponent(this.tenant)}${path}`;
  }

  async _get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${await r.text()}`);
    return r.json();
  }

  async _post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${await r.text()}`);
    return r.json();
  }

  // --- reads ---
  scorecard() { return this._get(this._agent("/scorecard")); }
  opportunities() { return this._get(this._agent("/opportunities")); }
  diff(oid) { return this._get(this._agent(`/opportunity/${encodeURIComponent(oid)}/diff`)); }
  decisions(subject) {
    const q = subject ? `?subject=${encodeURIComponent(subject)}` : "";
    return this._get(this._agent(`/decisions${q}`));
  }
  slo() { return this._get(this._agent("/slo")); }
  schemas() { return this._get(this._agent("/schema")); }

  // --- governed actions (C1, C3, C4, C5) ---
  decide(oid, action, by, note) {
    return this._post(this._agent("/decision"),
      { opportunity_id: oid, action, by: by || "console", note: note || null });
  }
  setSlo(slo, minConfidence, minEffect, by) {
    return this._post(this._agent("/slo"),
      { slo, min_confidence: minConfidence, min_effect: minEffect, by: by || "console" });
  }
  declareSchema(payload) { return this._post(this._agent("/schema"), payload); }
}
