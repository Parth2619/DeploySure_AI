/* App mode: connect a git repo, watch its commits, show which layer a change breaks.
   Loaded before the main script. It uses the helpers h, $, api, post, timeAgo, wireDialog and openDialog from there,
   but only inside functions, so nothing here runs until initAppMode() is called. */

const APP_AGENTS = [
  ["change_scan", "Change scan", "reads the diff and maps the app"], ["planner", "Planner", "chooses what to test first"],
  ["check_writing", "Check writer", "AI writes checks from the plan"], ["differential_run", "Differential run", "runs old and new side by side"],
  ["layer_attribution", "Layer attribution", "frontend, backend or connection"], ["risk_assessment", "Risk", "fixed formula"],
  ["decision", "Decision", "DEPLOY, HOLD or BLOCK"], ["critic", "Critic", "checks the decision against rules"],
];
const APP_PARTS = [["change_impact", "Change impact", 15], ["contract_break", "Page and API disagree", 40], ["api_regression", "API answers changed", 40],
  ["ui_regression", "Page looks broken", 40], ["not_verified", "Not fully verified", 10], ["start_failure", "New version won't start", 100]];
const POLL_MS = 4000;

let appCur = null;       // { id, detail } of the app being shown
let appSel = null;       // the selected commit
let appKnown = new Set();
let appNew = [];         // commits that appeared since the page opened
let appRun = null;       // AbortController of the analysis in progress
let appPoll = null, appClock = null;
let appQueue = [];       // new commits waiting for the running analysis to finish
let appState = {};       // merged node updates of the analysis on screen
let appVisit = 0;        // counts page visits, to drop answers that arrive after the user moved on
let appSteps = [];       // one entry per agent run: { node, output, input, ai, seconds }, for the pipeline details view
const AGENT_KIND = {
  planner: "AI reads the scan and chooses the focus", change_scan: "Plain code: git diff and an app map",
  check_writing: "AI proposes checks for the focus, code validates them", differential_run: "Plain code: runs the old and new app and a real browser, can send checks back",
  layer_attribution: "Plain code: fixed rules", risk_assessment: "Plain code: fixed formula",
  decision: "AI recommends, a rule floor limits it", critic: "Code rules decide PASS or FAIL, AI writes the sentence",
  replan: "Plain code: sends the decision back for another try", manual_review: "Plain code: stops after too many rejections",
};

/* ---------------- home: app cards ---------------- */
async function loadApps() {
  const box = $("app-cards");
  try {
    const apps = await api("/apps");
    box.replaceChildren(...(apps.length ? apps.map(appCard) : [h("div", { class: "emptybox" }, h("h2", {}, "No apps connected"),
      h("p", {}, "Connect a git repo that holds a web app. DeploySure compares each commit with the one before it."),
      h("button", { class: "btn", type: "button", onclick: openApp }, "Connect app"))]));
  } catch (err) { box.replaceChildren(h("p", { class: "empty" }, err.message)); }
}

function appCard(a) {
  if (a.error) return h("a", { class: "pcard acard", href: "#/a/" + a.id }, h("h2", {}, a.name), h("p", { class: "pmeta err" }, a.error));
  return h("a", { class: "pcard acard", href: "#/a/" + a.id },
    h("h2", {}, a.name), h("p", { class: "path" }, a.repo_path),
    h("p", { class: "latest" }, "Latest ", h("b", {}, a.latest.short), " " + a.latest.subject),
    h("p", { class: "pmeta" }, `${a.analyses} commit${a.analyses === 1 ? "" : "s"} analyzed${a.watch ? ", watching" : ""}`));
}

async function openApp() {
  openDialog("dlg-app");
  $("chooser").hidden = true;
  try {
    const list = await api("/app-examples");
    $("app-examples").replaceChildren(...list.map((e) => h("button", { class: "example", type: "button", onclick: () => {
      const form = $("dlg-app").querySelector("form");
      form.elements.name.value = e.name; form.elements.repo_path.value = e.path;
    } }, h("b", {}, e.name), h("span", {}, e.note), h("code", {}, e.path))));
  } catch { $("app-examples").replaceChildren(); }
}

/* ---------------- folder chooser in the Connect dialog ---------------- */
let chooserCur = { path: "", parent: null };

async function browseTo(path) {
  const error = $("dlg-app").querySelector(".form-error");
  try {
    let d;
    try { d = await api("/browse-folders?path=" + encodeURIComponent(path), { headers: { "X-DeploySure": "1" } }); }
    catch (err) { if (!path) throw err; d = await api("/browse-folders", { headers: { "X-DeploySure": "1" } }); }  // a typed path that does not exist: start from the drives
    chooserCur = d;
    error.textContent = "";
    $("chooser-path").textContent = d.path || "This computer";
    $("chooser-up").disabled = d.parent === null;
    $("chooser-use").disabled = !d.path;
    $("chooser-note").textContent = d.is_repo ? "This folder is a git repo." : d.path ? "No .git here yet. Open folders until you reach the one that contains .git." : "";
    $("chooser-list").replaceChildren(...(d.folders.length
      ? d.folders.map((f) => h("li", {}, h("button", { type: "button", onclick: () => browseTo(f.path) }, f.name)))
      : [h("li", { class: "empty" }, "No folders here")]));
  } catch (err) { error.textContent = err.message; }
}

/* ---------------- app page ---------------- */
function stopApp() {
  appVisit++;
  if (appRun) appRun.abort();
  appRun = null;
  clearInterval(appPoll); clearInterval(appClock);
  appCur = null; appQueue = [];
}

async function showApp(id) {
  $("view-home").hidden = true; $("view-project").hidden = true; $("view-app").hidden = false;
  const mine = ++appVisit;  // a slow answer for an app the user already left must not draw over the next page
  try {
    const detail = await api("/apps/" + id);
    if (mine !== appVisit) return;
    appCur = { id, detail };
    appKnown = new Set(detail.commits.map((c) => c.sha)); appNew = []; appQueue = [];
    document.title = detail.app.name + " | DeploySure AI";
    $("app-name").textContent = detail.app.name;
    $("app-repo").textContent = detail.app.source === "github" ? detail.app.url : detail.app.repo_path;
    showSync(detail);
    $("app-watch").checked = detail.app.watch; $("app-watch-box").classList.toggle("on", detail.app.watch);
    $("app-demo").hidden = !detail.demo;
    $("cmp-old").value = ""; $("cmp-new").value = "";
    const first = detail.commits.find((c) => c.parent);
    if (first) await selectCommit(first.sha); else resetAppStage("This repo has a single commit, so there is nothing to compare yet.");
    drawTimeline();
    clearInterval(appPoll);
    appPoll = setInterval(pollApp, POLL_MS);
  } catch (err) {
    if (mine !== appVisit) return;
    resetAppStage(err.message);
    $("app-commits").replaceChildren();
    $("app-name").textContent = id; $("app-repo").textContent = "";
  }
}

function showSync(detail) {
  const line = $("app-sync");
  line.hidden = detail.app.source !== "github";
  line.classList.toggle("problem", !!detail.sync_error);
  line.textContent = detail.sync_error ? "Could not reach GitHub: " + detail.sync_error : "Checking GitHub for new commits every few seconds.";
}

function drawTimeline() {
  const { commits } = appCur.detail;
  $("app-commit-count").textContent = commits.length + (commits.length === 100 ? "+" : "");
  $("app-commits").replaceChildren(...commits.map((c) => {
    const running = appRun && appSel && appSel.sha === c.sha;
    const tags = [...c.tags, ...c.branches];
    return h("li", { class: "commit", "data-v": c.analysis ? c.analysis.decision : "", "data-running": String(!!running), "aria-current": String(appSel?.sha === c.sha) },
      h("button", { type: "button", onclick: () => selectCommit(c.sha) },
        h("span", { class: "sha" }, c.short, " ", h("span", { class: "badges" }, appNew.includes(c.sha) ? h("span", { class: "badge new" }, "new") : null, tags.slice(0, 2).map((t) => h("span", { class: "badge" }, t)))),
        h("span", { class: "subject" }, c.subject),
        h("span", { class: "state" }, running ? "Analyzing" : c.analysis ? `${c.analysis.decision}, risk ${c.analysis.risk_score}, ${c.analysis.layer}` : c.parent ? "Not analyzed" : "First commit")));
  }));
}

async function selectCommit(sha) {
  if (appRun) return;  // do not swap the stage under a running analysis
  appSel = appCur.detail.commits.find((c) => c.sha === sha);
  drawTimeline();
  $("app-analyze").disabled = !appSel.parent;
  if (!appSel.parent) { resetAppStage("This is the first commit, so there is nothing before it to compare with."); return; }
  $("app-what").textContent = `${appSel.short} ${appSel.subject}, compared with ${appSel.parent.slice(0, 7)}`;
  if (appSel.analysis) {
    try { showReport(await api(`/apps/${appCur.id}/analyses/${appSel.parent}/${appSel.sha}`)); return; } catch { /* fall through to a blank stage */ }
  }
  resetAppStage("Not analyzed yet. Press Analyze and the agents compare this commit with the one before it.");
}

/* ---------------- new commit detection ---------------- */
async function pollApp() {
  if (!appCur) return;
  const id = appCur.id;
  let detail;
  try { detail = await api("/apps/" + id); } catch { return; }  // a network blip: try again next tick
  if (!appCur || appCur.id !== id) return;
  const fresh = detail.commits.filter((c) => !appKnown.has(c.sha));
  appCur.detail = detail;
  showSync(detail);
  if (fresh.length) {
    for (const c of fresh) { appKnown.add(c.sha); appNew.push(c.sha); }
    const list = fresh.slice().reverse();  // oldest first
    $("app-new").textContent = `${fresh.length} new commit${fresh.length > 1 ? "s" : ""}: ${list.map((c) => c.short + " " + c.subject).join("; ")}`;
    $("app-new").hidden = false;
    if ($("app-watch").checked) appQueue.push(...list.filter((c) => c.parent).map((c) => c.sha));
  }
  drawTimeline();
  runQueue();
}

function runQueue() {
  if (appRun || !appQueue.length) return;
  const sha = appQueue.shift();
  const c = appCur.detail.commits.find((x) => x.sha === sha);
  if (!c || c.analysis) return runQueue();
  appSel = c;
  analyzeRange(c.parent, c.sha, c);
}

/* ---------------- running an analysis ---------------- */
function resetAppStage(message) {
  appState = {}; appSteps = [];
  $("app-new").hidden = !appNew.length;
  $("a-verdict").removeAttribute("data-v");
  $("a-stamp").textContent = "Waiting"; $("a-vtitle").textContent = "Pick a commit";
  $("a-vtext").textContent = message || ""; $("a-vfacts").textContent = "";
  $("a-chain").hidden = true; $("a-log").replaceChildren();
  document.querySelectorAll("#view-app .panel").forEach((p) => reveal(p, h("p", { class: "empty" }, "Nothing yet.")));
  renderAppAgents();
}

function renderAppAgents(states = {}) {
  $("app-agents").replaceChildren(...APP_AGENTS.map(([id, name, how]) =>
    h("li", { class: "agent", "data-state": states[id] || "pending", id: "aag-" + id, role: "button", tabIndex: 0, title: "Show this agent's input and output",
              onclick: () => openPipeline(id), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPipeline(id); } } },
      h("i"), h("div", {}, h("b", {}, name), h("small", {}, how)))));
}
const setAppAgent = (id, state) => { const el = $("aag-" + id); if (el) el.dataset.state = state; };

function appLog(ev, line, cls) {
  $("a-log").append(h("div", { class: cls || "" }, h("time", {}, (ev.timestamp || "").slice(11, 23)), h("span", {}, line)));
  $("a-log").scrollTop = 1e9;
}

async function analyzeRange(oldRef, newRef, commit) {
  if (appRun || !appCur) return;
  resetAppStage("The agents are working through this change.");
  appSel = commit || null;
  appRun = new AbortController();
  $("app-analyze").disabled = true; $("app-analyze").textContent = "Analyzing";
  $("a-stamp").textContent = "Working"; $("a-vtitle").textContent = "Analysis in progress";
  const t0 = performance.now();
  appClock = setInterval(() => { $("app-elapsed").textContent = ((performance.now() - t0) / 1000).toFixed(1) + " s"; }, 100);
  setAppAgent("change_scan", "running");
  drawTimeline();
  const id = appCur.id;
  let error = "";
  try {
    const res = await fetch(`/apps/${id}/analyze`, { method: "POST", signal: appRun.signal,
      headers: { "X-DeploySure": "1", "Content-Type": "application/json" }, body: JSON.stringify({ old: oldRef, new: newRef }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, cut); buf = buf.slice(cut + 2);
        if (frame.startsWith("data: ")) error = onAppEvent(JSON.parse(frame.slice(6))) || error;
      }
    }
  } catch (err) {
    if (err.name === "AbortError") return;  // the user left the page
    error = err.message;
  }
  clearInterval(appClock);
  appRun = null;
  $("app-analyze").textContent = "Analyze again";
  if (error) {
    $("a-stamp").textContent = "Error"; $("a-vtitle").textContent = "The analysis did not finish";
    $("a-vtext").textContent = error; $("a-vfacts").textContent = "The live trace below has the details.";
    appLog({}, "Error: " + error, "err");
  }
  if (!appCur || appCur.id !== id) return;
  try { appCur.detail = await api("/apps/" + id); appKnown = new Set(appCur.detail.commits.map((c) => c.sha)); } catch { /* the timeline keeps its old rows */ }
  if (appSel) appSel = appCur.detail.commits.find((c) => c.sha === appSel.sha) || appSel;
  $("app-analyze").disabled = !appSel?.parent;
  drawTimeline();
  runQueue();
}

// Returns an error message when the event reports one.
function onAppEvent(ev) {
  if (ev.node === "error") return ev.state_update.error;
  if (ev.node === "final") { showReport(ev.final_report); return ""; }
  setAppAgent(ev.node, "done");
  appSteps.push({ node: ev.node, timestamp: ev.timestamp, output: ev.state_update, ...ev.io });
  Object.assign(appState, ev.state_update, { trace: undefined });
  for (const line of ev.state_update.trace || []) appLog(ev, line);
  renderView(viewFromState(appState));
  renderTalk();
  if (ev.node === "differential_run" && (ev.state_update.messages || []).some((m) => m.kind === "repair")) {
    setAppAgent("differential_run", "pending"); setAppAgent("check_writing", "running");  // it sent checks back to the Check writer
    return "";
  }
  const i = APP_AGENTS.findIndex((a) => a[0] === ev.node);
  if (i >= 0 && i < APP_AGENTS.length - 1) setAppAgent(APP_AGENTS[i + 1][0], "running");
  if (ev.node === "replan") { setAppAgent("decision", "running"); setAppAgent("critic", "pending"); }
  return "";
}

/* ---------------- one view shape for live updates and saved reports ---------------- */
function viewFromState(s) {
  const scan = s.scan || {};
  return { layers: scan.layers, contract: scan.contract_issues, endpoints: scan.endpoint_changes, config: scan.config_changes,
    deps: scan.dependency_changes, api: s.api_report?.results, apiSummary: s.api_report?.summary, browser: s.browser_report?.results,
    browserSummary: s.browser_report?.summary, startError: s.start_error, browserError: s.browser_error, verdict: s.layer_verdict,
    score: s.risk_score, level: s.risk_level, parts: s.risk_components, decision: s.decision, reason: s.decision_reason,
    critic: s.critic_result, criticReason: s.critic_reason, retries: s.retry_count, sources: s.check_sources };
}

function viewFromReport(r) {
  return { layers: r.layers_changed, contract: r.contract_issues, endpoints: r.endpoint_changes, config: r.config_changes, deps: r.dependency_changes,
    api: r.api_results, apiSummary: r.api_summary, browser: r.browser_results, browserSummary: r.browser_summary, startError: r.start_error,
    browserError: r.browser_error, verdict: r.layer_verdict, score: r.risk_score, level: r.risk_level, parts: r.risk_components,
    decision: r.decision, reason: r.decision_reason, critic: r.critic_result, criticReason: r.critic_reason, retries: r.retry_count, sources: r.check_sources };
}

function showReport(r) {
  appSteps = r.steps || [];  // analyses saved before this view existed have no steps
  renderAppAgents(Object.fromEntries(APP_AGENTS.map((a) => [a[0], "done"])));
  $("a-log").replaceChildren();
  for (const line of r.trace || []) appLog({}, line);
  $("app-what").textContent = `${r.new_sha.slice(0, 7)} compared with ${r.old_sha.slice(0, 7)}`;
  renderView(viewFromReport(r), true);
  renderTalk();
}

/* ---------------- rendering ---------------- */
function describeDiff(d) {
  switch (d.kind) {
    case "value_changed": return `${d.field} changed from ${JSON.stringify(d.old)} to ${JSON.stringify(d.new)}`;
    case "field_removed": return `field ${d.field} was removed`;
    case "field_added": return `field ${d.field} was added`;
    case "status_changed": return `status changed from ${d.old} to ${d.new}`;
    case "new_failed_request": return `request ${d.request} failed`;
    case "request_missing": return `request ${d.request} is no longer made`;
    case "broken_value": return `${d.field} now shows ${d.new}`;
    case "items_lost": return `${d.field} lost items`;
    default: return d.detail || d.kind;
  }
}

function renderView(v, final = false) {
  if (v.layers) renderChanged(v);
  if (v.contract) renderContract(v);
  if (v.api) renderChecks("ap-api", "API checks", v.api, v.apiSummary, v.sources?.api);
  if (v.browser) renderChecks("ap-browser", "Browser checks", v.browser, v.browserSummary, v.sources?.browser, v.browserError);
  if (v.verdict) renderChain(v);
  if (v.parts) renderRisk(v);
  if (v.critic) renderDecision(v);
  if (final) renderVerdictBanner(v);
}

function renderChanged(v) {
  const rows = [];
  for (const [layer, paths] of Object.entries(v.layers)) rows.push(h("li", {}, h("b", {}, layer + ": "), paths.join(", ")));
  for (const c of v.config || []) rows.push(h("li", {}, h("b", {}, "config: "), c.file + (c.status ? " (" + c.status + ")" : ` keys +${(c.added || []).length} -${(c.removed || []).length} ~${(c.changed || []).length}`)));
  for (const d of v.deps || []) rows.push(h("li", {}, h("b", {}, "dependencies: "), d.file + (d.status ? " (" + d.status + ")" : ` +${(d.added || []).length} -${(d.removed || []).length} ~${(d.changed || []).length}`)));
  for (const e of v.endpoints || []) rows.push(h("li", {}, h("b", {}, e.kind.replace("_", " ") + ": "), e.endpoint + (e.fields.length ? " " + e.fields.join(", ") : "")));
  reveal($("ap-changed"), rows.length ? h("ul", { class: "sentences" }, rows) : h("p", { class: "empty" }, "No tracked files changed."));
}

function renderContract(v) {
  const issues = v.contract;
  reveal($("ap-contract"), issues.length
    ? h("ul", { class: "sentences" }, issues.map((i) => h("li", { class: "bad" }, i.kind === "unknown_endpoint"
      ? `${i.file} calls ${i.call}, which the backend does not serve.`
      : `The page reads '${i.field}' from ${i.endpoint}, but the backend no longer returns it (${i.read_by.join(", ")}).`)))
    : h("p", {}, "Every call the page makes still matches a backend route, and every field it reads is still returned."));
}

function renderChecks(panelId, title, results, summary, source, note) {
  const counts = summary ? ["regression", "unchanged", "benign_change", "ui_changed", "unreliable"].filter((k) => summary[k]).map((k) => `${summary[k]} ${k.replace("_", " ")}`).join(", ") : "";
  reveal($(panelId),
    h("p", { class: "confidence" }, [counts || "No checks ran.", source ? ` Written by: ${source}.` : "", note ? ` ${note}` : ""].join("")),
    results.length ? h("ul", { class: "evi" }, results.map((r) => h("li", {},
      h("span", { class: "v " + r.verdict }, r.verdict.replace("_", " ")), h("span", { class: "name" }, r.name),
      r.differences.length ? h("ul", { class: "diffs" }, r.differences.slice(0, 3).map((d) => h("li", {}, describeDiff(d)))) : null))) : null);
}

function renderChain(v) {
  const lv = v.verdict, bad = new Set(lv.layers), changed = Object.keys(v.layers || {});
  $("a-chain").hidden = false;
  for (const [id, label] of [["frontend", "Frontend"], ["backend", "Backend"]]) {
    const n = $("n-" + id);
    n.dataset.s = bad.has(id) ? "fault" : changed.includes(id) ? "changed" : "";
    n.querySelector("small").textContent = bad.has(id) ? "has the fault" : changed.includes(id) ? "changed, no fault found" : "not changed";
    n.querySelector("b").textContent = label;
  }
  $("n-connection").dataset.s = bad.has("connection") ? "fault" : "";
  const env = $("n-environment");
  env.hidden = !bad.has("environment");
  env.textContent = bad.has("environment") ? "Environment: the new version could not start. Check configuration and dependencies." : "";
  $("a-why").replaceChildren(...lv.reasons.map((r) => h("li", { class: lv.layers.length ? "fault" : "" }, r)));
  const e = lv.evidence;
  $("a-confidence").replaceChildren(h("b", {}, "Confidence " + lv.confidence + ". "),
    `Evidence: ${e.static} contract issue${e.static === 1 ? "" : "s"}, ${e.api} API regression${e.api === 1 ? "" : "s"}, ${e.browser} page regression${e.browser === 1 ? "" : "s"}.`);
}

function renderRisk(v) {
  if (v.score == null) return;
  reveal($("ap-risk"),
    h("div", { class: "score", "data-l": v.level }, h("b", {}, v.score), h("span", {}, v.level)),
    h("div", { class: "meter", role: "img", "aria-label": "Risk " + v.score + " of 100" }, h("i"), h("i"), h("i"), h("i"), h("span", { class: "pin", style: "left:" + v.score + "%" })),
    h("div", { class: "scale" }, ["0", "30", "60", "80", "100"].map((n) => h("span", {}, n))),
    h("ul", { class: "parts" }, APP_PARTS.filter(([k]) => k in v.parts).map(([k, label, max]) =>
      h("li", {}, h("span", {}, label), h("span", { class: "bar" }, h("i", { style: "width:" + Math.min(100, 100 * v.parts[k] / max) + "%" })), h("em", {}, v.parts[k] + "/" + max)))));
}

function renderDecision(v) {
  const critic = v.critic === "PASS" ? "Critic approved" : "Critic rejected";
  reveal($("ap-decide"), h("div", { class: "decide" },
    h("div", { class: "row" }, h("b", {}, "Decision"), h("span", {}, `${v.decision}. ${v.reason}`)),
    h("div", { class: "row" }, h("b", {}, critic), h("span", {}, v.criticReason)),
    v.retries ? h("div", { class: "row" }, h("b", {}, "Retries"), h("span", {}, `${v.retries} earlier decision${v.retries > 1 ? "s were" : " was"} rejected by the Critic.`)) : null));
}

function renderVerdictBanner(v) {
  const box = $("a-verdict");
  box.dataset.v = v.decision;
  $("a-stamp").textContent = v.decision;
  $("a-vtitle").textContent = { DEPLOY: "Safe to ship", HOLD: "Hold for review", BLOCK: "Blocked from release" }[v.decision];
  $("a-vtext").textContent = v.reason;
  const where = v.verdict.layers.length ? "Fault in: " + v.verdict.primary + ". " : "No layer is at fault. ";
  const critic = v.critic === "PASS" ? (v.retries ? `The Critic rejected ${v.retries} earlier decision${v.retries > 1 ? "s" : ""} before approving this one. ` : "The Critic approved the first decision. ") : "The Critic never approved a decision, so a person must review this change. ";
  $("a-vfacts").textContent = `${where}${critic}Risk ${v.score} (${v.level}).`;
}

/* ---------------- pipeline details: what each agent received and produced ---------------- */
const agentName = (id) => (APP_AGENTS.find((a) => a[0] === id) || [id, id])[1];
const pretty = (value) => {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return text.length > 20000 ? text.slice(0, 20000) + "\n... (cut for display)" : text;
};

// The value an earlier agent produced, looked up from the steps before this one.
function producedValue(before, from, key) {
  for (let i = before - 1; i >= 0; i--) if (appSteps[i].node === from) return appSteps[i].output[key];
  return undefined;
}

// Every message the agents sent each other, in order.
const allMessages = () => appSteps.flatMap((s) => (s.output && s.output.messages) || []);

function talkList(messages) {
  return h("ul", { class: "talk" }, messages.map((m) => h("li", { "data-kind": m.kind },
    h("b", {}, agentName(m.from)), " to ", h("b", {}, agentName(m.to)), m.kind === "info" ? "" : h("span", { class: "tag" }, m.kind), ": ", m.text)));
}

function renderTalk() {
  const messages = allMessages();
  reveal($("ap-talk"), messages.length ? talkList(messages)
    : h("p", { class: "empty" }, appSteps.length ? "No messages." : "No messages were saved for this analysis. Analyze it again to record them."));
}

// Which agent writes and which reads each piece of shared data, read from what actually happened in this analysis.
const MATRIX_SKIP = new Set(["repo", "old", "new", "old_sha", "new_sha", "trace", "messages", "feedback", "check_round", "retry_count", "check_sources",
  "focus_reason", "decision_reason", "critic_reason", "critic_rules", "risk_components"]);

function sharingMatrix() {
  const rows = [];
  for (const step of appSteps) for (const key of Object.keys(step.output || {})) if (!MATRIX_SKIP.has(key) && !rows.includes(key)) rows.push(key);
  const cell = (node, key) => {
    const own = appSteps.filter((s) => s.node === node);
    const writes = own.some((s) => key in (s.output || {})), reads = own.some((s) => key in (s.input || {}));
    return h("td", { class: writes ? "w" : reads ? "r" : "", title: writes ? "writes it" : reads ? "reads it" : "" }, writes ? "writes" : reads ? "reads" : "");
  };
  return h("div", { class: "sharing-wrap" }, h("table", { class: "sharing" },
    h("thead", {}, h("tr", {}, h("th", {}, "Shared data"), APP_AGENTS.map(([id, name]) => h("th", {}, name)))),
    h("tbody", {}, rows.map((key) => h("tr", {}, h("th", { scope: "row" }, h("code", {}, key)), APP_AGENTS.map(([id]) => cell(id, key)))))));
}

function inputBlock(step, index) {
  const keys = Object.entries(step.input || {});
  const told = step.messages_in || [];
  const heard = told.length ? [h("h4", {}, "Messages received"), talkList(told)] : [];
  if (!keys.length) return [h("p", { class: "pl-note" }, "This agent reads nothing from earlier agents."), ...heard];
  return [...keys.map(([key, value]) => {
    if (value && typeof value === "object" && value.from) {
      const found = producedValue(index, value.from, key);
      return h("details", { class: "pl-in" }, h("summary", {}, h("code", {}, key), " from ", h("b", {}, agentName(value.from))),
        h("pre", {}, found === undefined ? "(not available)" : pretty(found)));
    }
    return h("p", { class: "pl-in" }, h("code", {}, key), ": ", value === "" ? "(empty)" : String(value));
  }), ...heard];
}

function aiBlock(step) {
  if (!(step.ai || []).length) return [];
  return step.ai.flatMap((call) => [
    h("h4", {}, `AI prompt sent (${call.task})`), h("pre", {}, call.prompt)]);
}

function outputBlock(step) {
  const { trace, ...rest } = step.output || {};
  const parts = [];
  for (const call of step.ai || []) {
    parts.push(h("h4", {}, `AI answer (${call.task})`));
    if (call.fallback) parts.push(h("p", { class: "pl-note pl-warn" }, "The AI was not used here, this is the fixed default. Reason: " + (call.error || "unknown")));
    parts.push(h("pre", {}, pretty(call.answer)));
  }
  parts.push(h("h4", {}, "What the agent wrote to the shared state"), h("pre", {}, Object.keys(rest).length ? pretty(rest) : "(nothing)"));
  if ((trace || []).length) parts.push(h("h4", {}, "Log lines"), h("ul", { class: "pl-logs" }, trace.map((t) => h("li", {}, t))));
  return parts;
}

function openPipeline(focus) {
  const dlg = $("dlg-pipeline"), body = $("pl-body");
  if (!appSteps.length) {
    body.replaceChildren(h("p", { class: "pl-note" }, "There are no saved details for this analysis. Analyze the commit again to record what each agent receives and produces."));
  } else {
    const shown = [];
    const rows = appSteps.map((step, index) => {
      const open = step.node === focus && !shown.includes(step.node);
      if (open) shown.push(step.node);
      return h("details", { class: "pl-step", id: "pl-" + step.node + "-" + index, open: open },
        h("summary", {}, `${index + 1}. ${agentName(step.node)}`, h("span", { class: "kind" }, AGENT_KIND[step.node] || ""),
          h("span", { class: "took" }, step.seconds != null ? step.seconds + " s" : "")),
        h("div", { class: "pl-grid" },
          h("div", { class: "pl-col" }, h("h3", {}, "Input"), ...inputBlock(step, index), ...aiBlock(step)),
          h("div", { class: "pl-col" }, h("h3", {}, "Output"), ...outputBlock(step))));
    });
    body.replaceChildren(
      h("details", { class: "pl-step", open: !focus }, h("summary", {}, "Who shares what", h("span", { class: "kind" }, "one shared state: each agent reads what others wrote")),
        h("div", { class: "pl-col" }, sharingMatrix(), h("p", { class: "pl-note" }, "writes = the agent put this in the shared state. reads = the agent used it as input."))),
      h("details", { class: "pl-step", open: !focus && allMessages().length > 0 }, h("summary", {}, "Messages between agents", h("span", { class: "kind" }, `${allMessages().length} in this analysis`)),
        h("div", { class: "pl-col" }, allMessages().length ? talkList(allMessages()) : h("p", { class: "pl-note" }, "No messages."))),
      ...rows);
  }
  if (!dlg.open) dlg.showModal();
  const target = focus && body.querySelector(`[id^="pl-${focus}-"][open]`);  // only the agent that was clicked opens, the overview sections stay closed
  if (target) target.scrollIntoView({ block: "start" });
}

/* ---------------- wiring ---------------- */
function initAppMode() {
  $("open-app").addEventListener("click", openApp);
  $("app-details").addEventListener("click", () => openPipeline(null));
  $("pl-close").addEventListener("click", () => $("dlg-pipeline").close());
  $("pick-folder").addEventListener("click", () => {
    const box = $("chooser");
    box.hidden = !box.hidden;
    if (!box.hidden) browseTo($("dlg-app").querySelector("form").elements.repo_path.value.trim());
  });
  $("chooser-up").addEventListener("click", () => browseTo(chooserCur.parent));
  $("chooser-use").addEventListener("click", () => {
    const form = $("dlg-app").querySelector("form");
    form.elements.repo_path.value = chooserCur.path;
    if (!form.elements.name.value.trim()) form.elements.name.value = chooserCur.path.split(/[\\/]/).filter(Boolean).pop() || "My app";
    $("chooser").hidden = true;
  });
  wireDialog("dlg-app", async (body) => {
    const note = $("connect-note");
    note.textContent = body.repo_url.trim() ? "Downloading from GitHub. This can take up to a minute." : "";
    try { const card = await post("/apps", body); location.hash = "#/a/" + card.id; }
    finally { note.textContent = ""; }
  });
  $("app-analyze").addEventListener("click", () => { if (appSel?.parent && !appRun) analyzeRange(appSel.parent, appSel.sha, appSel); });
  $("cmp-go").addEventListener("click", () => {
    const a = $("cmp-old").value.trim(), b = $("cmp-new").value.trim();
    if (a && b && !appRun) { appSel = null; analyzeRange(a, b, null); }
  });
  $("app-watch").addEventListener("change", async (e) => {
    const on = e.target.checked;
    $("app-watch-box").classList.toggle("on", on);
    try { await api(`/apps/${appCur.id}/watch`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ watch: on }) }); }
    catch (err) { e.target.checked = !on; $("app-watch-box").classList.toggle("on", !on); alert(err.message); }
  });
  $("app-remove-go").addEventListener("click", async () => {
    if (appRun || !confirm("Remove this app from DeploySure? The repo is not touched.")) return;
    try { await api("/apps/" + appCur.id, { method: "DELETE" }); location.hash = "#/"; } catch (err) { alert(err.message); }
  });
  $("demo-go").addEventListener("click", async () => {
    const button = $("demo-go");
    button.disabled = true;
    try {
      await api(`/apps/${appCur.id}/demo-commit`, { method: "POST", headers: { "Content-Type": "application/json", "X-DeploySure": "1" }, body: JSON.stringify({ change: $("demo-change").value }) });
      pollApp();
    } catch (err) { alert(err.message); } finally { button.disabled = false; }
  });
}
