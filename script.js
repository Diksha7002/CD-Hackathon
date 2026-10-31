// GrammarFix front-end: plain JavaScript, no libraries.
// It sends the code to Flask (/api/analyze) and draws the JSON that comes back.
// All text is inserted with textContent, so user input can never inject HTML.

"use strict";

const $ = (id) => document.getElementById(id);

// small helper: create an element with optional class and text
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function colorClass(id) {
  return "c" + ((id - 1) % 6);
}

/* ------------------------------------------------------------------ */
/* Talking to the server                                               */
/* ------------------------------------------------------------------ */

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    throw new Error("The server sent an unexpected reply.");
  }
  if (!response.ok || !data.ok) {
    throw new Error(data && data.error ? data.error : "Request failed.");
  }
  return data;
}

async function analyze() {
  const code = $("code").value;
  const button = $("analyzeBtn");
  hideError();
  button.disabled = true;
  button.textContent = "Analyzing…";
  try {
    const data = await postJSON("/api/analyze", { code: code });
    showResult(data);
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    const message = err instanceof TypeError
      ? "Could not reach the server. Is `python app.py` still running?"
      : err.message;
    showError(message);
  } finally {
    button.disabled = false;
    button.textContent = "Analyze";
  }
}

function showError(message) {
  const box = $("errorBox");
  box.textContent = message;
  box.classList.remove("hidden");
}

function hideError() {
  $("errorBox").classList.add("hidden");
}

/* ------------------------------------------------------------------ */
/* Drawing the tree                                                    */
/* ------------------------------------------------------------------ */

function treeNode(n) {
  const li = el("li");
  let cls = "node " + n.kind;
  if (n.color) cls += " " + colorClass(n.color);
  const box = el("div", cls);
  box.appendChild(el("span", "label", n.label));
  if (n.sub) box.appendChild(el("span", "sub", n.sub));
  li.appendChild(box);
  if (n.children && n.children.length > 0) {
    const ul = el("ul");
    n.children.forEach((child) => ul.appendChild(treeNode(child)));
    li.appendChild(ul);
  }
  return li;
}

function buildTree(root) {
  const scroll = el("div", "tree-scroll");
  const wrap = el("div", "tree");
  const ul = el("ul");
  ul.appendChild(treeNode(root));
  wrap.appendChild(ul);
  scroll.appendChild(wrap);
  return scroll;
}

function buildCode(lines) {
  const box = el("div", "codebox");
  lines.forEach((line) => {
    const row = el("div", "codeline");
    row.appendChild(el("span", "code", line.text));
    if (line.note) {
      row.appendChild(el("span", "note " + colorClass(line.color), line.note));
    }
    box.appendChild(row);
  });
  return box;
}

/* ------------------------------------------------------------------ */
/* Showing the analysis                                                */
/* ------------------------------------------------------------------ */

function showResult(data) {
  // --- section 2: verdict + stats ---
  $("resultEmpty").classList.add("hidden");
  $("resultBody").classList.remove("hidden");

  const verdict = $("verdict");
  verdict.className = "verdict " + (data.verdict.ambiguous ? "amb" : "ok");
  verdict.replaceChildren(
    el("p", "v-title", (data.verdict.ambiguous ? "⚠ " : "✔ ") + data.verdict.title),
    el("p", null, data.verdict.message)
  );

  const stats = $("stats");
  stats.replaceChildren();
  [
    [data.counts.ifs, "if statements"],
    [data.counts.elses, "else clauses"],
    [data.counts.original_trees, "parse trees (original grammar)"],
    [data.counts.resolved_trees, "parse tree (transformed grammar)"],
  ].forEach((pair) => {
    const box = el("div", "stat");
    box.appendChild(el("div", "big", String(pair[0])));
    box.appendChild(el("div", "lbl", pair[1]));
    stats.appendChild(box);
  });

  // --- table of ifs ---
  const tbody = $("ifTable").querySelector("tbody");
  tbody.replaceChildren();
  data.ifs.forEach((info) => {
    const row = el("tr");
    const idCell = el("td");
    idCell.appendChild(el("span", "badge grey", "IF" + info.id));
    row.appendChild(idCell);

    const condCell = el("td");
    condCell.style.paddingLeft = (10 + info.depth * 14) + "px";
    condCell.appendChild(el("code", null, info.cond));
    row.appendChild(condCell);

    const statusCell = el("td");
    statusCell.appendChild(el("span", "badge " + (info.class === "M" ? "green" : "amber"), info.class));
    statusCell.appendChild(document.createTextNode(" " + info.status));
    row.appendChild(statusCell);

    row.appendChild(el("td", null, info.else_id ? "else #" + info.else_id : "—"));
    tbody.appendChild(row);
  });

  // --- the two interpretations of an else ---
  const dBox = $("danglingBox");
  const dList = $("danglingList");
  dList.replaceChildren();
  if (data.dangling.length > 0) {
    data.dangling.forEach((d) => {
      const names = d.candidates.map((c) => "IF" + c).join(" or ");
      const li = el("li");
      li.appendChild(el("strong", null, "else #" + d.else));
      li.appendChild(document.createTextNode(
        " can belong to " + names + ". The nearest-unmatched-if rule chooses IF" + d.chosen + "."));
      dList.appendChild(li);
    });
    dBox.classList.remove("hidden");
  } else {
    dBox.classList.add("hidden");
  }

  // --- section 4: trees BEFORE ---
  $("beforeEmpty").classList.add("hidden");
  const before = $("beforeTrees");
  before.replaceChildren();
  data.interpretations.forEach((interp) => {
    const card = el("div", "tree-card" + (interp.is_nearest ? " chosen" : ""));
    const title = el("h4", null, interp.label);
    if (data.verdict.ambiguous) {
      title.appendChild(el("span", "badge " + (interp.is_nearest ? "green" : "red"),
        interp.is_nearest ? "nearest if – kept" : "removed by new grammar"));
    }
    card.appendChild(title);
    card.appendChild(el("p", "summary", interp.summary || "There is no else clause."));
    card.appendChild(buildCode(interp.code));
    card.appendChild(buildTree(interp.tree));
    before.appendChild(card);
  });
  const more = $("beforeMore");
  if (data.hidden_interpretations > 0) {
    more.textContent = "… and " + data.hidden_interpretations +
      " more parse trees are possible (only the first " + data.interpretations.length + " are drawn).";
    more.classList.remove("hidden");
  } else {
    more.classList.add("hidden");
  }

  // --- section 4: tree AFTER ---
  $("afterEmpty").classList.add("hidden");
  const after = $("afterTree");
  after.replaceChildren();
  const afterCard = el("div", "tree-card chosen");
  afterCard.appendChild(el("h4", null, "The one parse tree"));
  afterCard.appendChild(el("p", "summary", data.resolved.summary));
  afterCard.appendChild(buildCode(data.resolved.code));
  afterCard.appendChild(buildTree(data.resolved.tree));
  after.appendChild(afterCard);

  // --- section 6: explanation ---
  $("explainEmpty").classList.add("hidden");
  const explain = $("explainBody");
  explain.replaceChildren();
  data.explanation.forEach((part) => {
    const item = el("div", "explain-item");
    item.appendChild(el("h4", null, part.title));
    item.appendChild(el("p", null, part.text));
    explain.appendChild(item);
  });
}

/* ------------------------------------------------------------------ */
/* Test cases and samples                                              */
/* ------------------------------------------------------------------ */

function loadAndAnalyze(code) {
  $("code").value = code;
  analyze();
}

async function loadTests() {
  const samples = $("samples");
  const summary = $("testSummary");
  try {
    const response = await fetch("/api/tests");
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error("bad reply");

    // sample chips
    samples.replaceChildren();
    data.tests.forEach((test) => {
      const chip = el("button", "chip", test.name);
      chip.type = "button";
      chip.addEventListener("click", () => {
        $("code").value = test.code;
        hideError();
      });
      samples.appendChild(chip);
    });

    // test table
    const tbody = $("testTable").querySelector("tbody");
    tbody.replaceChildren();
    let passed = 0;
    data.tests.forEach((test) => {
      if (test.passed) passed += 1;
      const row = el("tr");
      row.appendChild(el("td", null, String(test.id)));
      row.appendChild(el("td", null, test.name));
      const codeCell = el("td");
      codeCell.appendChild(el("pre", null, test.code));
      row.appendChild(codeCell);

      const expectedCell = el("td");
      expectedCell.appendChild(el("span", "badge " + (test.expected === "ambiguous" ? "amber" : "green"), test.expected));
      row.appendChild(expectedCell);

      const gotCell = el("td");
      gotCell.appendChild(el("span", "badge " + (test.result === "ambiguous" ? "amber" : test.result === "error" ? "red" : "green"), test.result));
      gotCell.appendChild(document.createTextNode(test.passed ? " ✔" : " ✘"));
      row.appendChild(gotCell);

      row.appendChild(el("td", null, String(test.trees)));

      const runCell = el("td");
      const runBtn = el("button", "btn ghost small", "Run");
      runBtn.type = "button";
      runBtn.addEventListener("click", () => loadAndAnalyze(test.code));
      runCell.appendChild(runBtn);
      row.appendChild(runCell);
      tbody.appendChild(row);
    });

    summary.textContent = passed + " of " + data.tests.length + " test cases match the expected answer.";
    summary.className = "test-summary " + (passed === data.tests.length ? "pass" : "fail");
  } catch (err) {
    samples.textContent = "Could not load samples. Is the Flask server running?";
    summary.textContent = "Could not load the test cases.";
    summary.className = "test-summary fail";
  }
}

/* ------------------------------------------------------------------ */
/* Wiring the buttons                                                  */
/* ------------------------------------------------------------------ */

$("analyzeBtn").addEventListener("click", analyze);

$("clearBtn").addEventListener("click", () => {
  $("code").value = "";
  hideError();
  $("code").focus();
});

$("code").addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter") {
    event.preventDefault();
    analyze();
  }
});

loadTests();
