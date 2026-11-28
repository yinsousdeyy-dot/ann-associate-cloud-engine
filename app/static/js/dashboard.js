"use strict";
/* Operations hub behaviour. Loaded as an external script because the CSP forbids inline scripts.
   Data from the API is only ever written with textContent or setAttribute, never innerHTML. */

(function () {
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const FX = Number(document.body.dataset.fx) || 4000;
  const DEMO = document.body.dataset.demo === "true";
  const JSON_HEADERS = { "Content-Type": "application/json", "X-Firm-CSRF": "1" };

  /* ---------- small helpers ---------- */

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v === null || v === undefined || v === false) return;
      if (k === "text") node.textContent = v;
      else node.setAttribute(k, v === true ? "" : v);
    });
    (children || []).forEach((c) => node.append(c));
    return node;
  }

  function cell(value, cls) {
    return el("td", { class: cls, text: value === null || value === undefined || value === "" ? "-" : String(value) });
  }

  function pill(text, kind) {
    return el("span", { class: "pill" + (kind ? " pill-" + kind : ""), text });
  }

  function money(n) {
    return "$" + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  const timePart = (s) => (s ? String(s).slice(11, 16) : "");

  let toastTimer = 0;
  function toast(message, isError) {
    const t = $("#toast");
    t.textContent = message;
    t.classList.toggle("is-error", !!isError);
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, isError ? 8000 : 4500);
  }

  async function api(path, options) {
    const res = await fetch(path, Object.assign({ credentials: "same-origin" }, options));
    if (res.status === 403 && !path.startsWith("/api/v1/simulate") && !path.startsWith("/webhooks")) {
      window.location.assign("/dashboard");
      throw new Error("Your session has ended. Sign in again.");
    }
    let body = {};
    try { body = await res.json(); } catch (e) { /* non-JSON error body */ }
    if (!res.ok) {
      const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail;
      throw new Error(detail || body.reason || "The request failed (" + res.status + ").");
    }
    return body;
  }

  function post(path, payload) {
    return api(path, { method: "POST", headers: JSON_HEADERS, body: payload === undefined ? undefined : JSON.stringify(payload) });
  }

  function fillTable(id, rows, build, emptyText) {
    const body = $("#" + id + " tbody");
    const cols = $("#" + id + " thead th").length || 1;
    body.replaceChildren();
    if (!rows || !rows.length) {
      body.append(el("tr", {}, [el("td", { class: "empty", colspan: cols, text: emptyText })]));
      return;
    }
    rows.forEach((r) => body.append(build(r)));
  }

  /* ---------- panels ---------- */

  const panels = $$(".panel");
  const navItems = $$(".nav-item");

  function showPanel(id, moveFocus) {
    if (!panels.some((p) => p.id === id)) id = "overview";
    panels.forEach((p) => { p.hidden = p.id !== id; });
    navItems.forEach((n) => {
      if (n.dataset.panel === id) n.setAttribute("aria-current", "page");
      else n.removeAttribute("aria-current");
    });
    if (location.hash !== "#" + id) history.replaceState(null, "", "#" + id);
    document.title = $("#" + id + "-title").textContent + " - Operations hub";
    if (moveFocus) $("#" + id + "-title").focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }

  $$("[data-panel]").forEach((b) => b.addEventListener("click", () => showPanel(b.dataset.panel, true)));
  window.addEventListener("hashchange", () => showPanel(location.hash.slice(1), false));

  /* ---------- data ---------- */

  let receiptFiles = [];

  function receiptLink(receiptNo) {
    const file = receiptFiles.find((f) => f.startsWith(receiptNo + "_"));
    if (!file) return cell("");
    return el("td", {}, [el("a", { href: "/receipts/" + encodeURIComponent(file), target: "_blank", rel: "noopener", text: "Open A5 receipt" })]);
  }

  function invoiceRow(r, withSplitAmounts) {
    const tr = el("tr", {}, [
      el("td", {}, [el("strong", { text: r.receipt_no })]),
      el("td", {}, [document.createTextNode(r.khmer_name), el("span", { class: "sub", text: r.latin_name })]),
      cell(r.course_title, "wrap"),
    ]);
    if (withSplitAmounts) {
      tr.append(cell(money(r.total_usd), "num"), cell(Number(r.total_khr).toLocaleString(), "num"), cell(r.payment_method));
    } else {
      tr.append(cell(money(r.total_usd), "num"));
    }
    tr.append(cell(String(r.issued_at).slice(0, 16)), receiptLink(r.receipt_no));
    return tr;
  }

  function statusPill(flag) {
    return pill(String(flag).replace("_", " ").toLowerCase(), flag === "ON_TIME" ? "ok" : "late");
  }

  function renderFigures(k) {
    $("#fig-revenue").textContent = money(k.revenue_usd);
    $("#fig-revenue-note").textContent = Number(k.revenue_khr || 0).toLocaleString() + " KHR across " + (k.invoice_count || 0) + " invoices";
    $("#fig-rating").textContent = k.survey_count ? Number(k.avg_rating).toFixed(1) + " / 5" : "None yet";
    $("#fig-rating-note").textContent = (k.survey_count || 0) + " survey responses";
    $("#fig-scans").textContent = k.scans_today || 0;
    const q = $("#fig-quarantine");
    q.textContent = k.quarantine_count || 0;
    q.classList.toggle("is-alert", !!k.quarantine_count);
    const nav = $("#nav-quarantine");
    nav.textContent = k.quarantine_count || 0;
    nav.classList.toggle("is-alert", !!k.quarantine_count);
  }

  function fileItem(name, meta, href) {
    return el("li", {}, [
      el("span", {}, [el("span", { class: "file-name", text: name }), meta ? el("span", { class: "file-meta", text: "  " + meta }) : document.createTextNode("")]),
      el("a", { class: "btn btn-secondary btn-sm", href, download: name, text: "Download" }),
    ]);
  }

  function renderFiles(listId, items, empty) {
    const ul = $("#" + listId);
    ul.replaceChildren();
    if (!items.length) ul.append(el("li", { class: "file-empty", text: empty }));
    items.forEach((i) => ul.append(i));
  }

  let botUsersLoaded = false;
  function renderBotUsers(users) {
    if (botUsersLoaded || !users) return;
    botUsersLoaded = true;
    const sel = $("#tg-user");
    sel.replaceChildren();
    users.forEach((u) => {
      const scope = u.department === "ALL" ? "all departments" : u.department;
      sel.append(el("option", { value: u.chat_id, text: u.full_name + " (" + u.role + ", " + scope + ")" }));
    });
    sel.append(el("option", { value: "999999999", text: "Unregistered account (access denied)" }));
  }

  async function loadOverview() {
    const d = await api("/api/v1/data/overview");
    receiptFiles = d.receipts || [];
    renderFigures(d.kpi || {});
    renderBotUsers(d.bot_users);
    $("#updated-at").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    fillTable("tbl-recent", (d.invoices || []).slice(0, 5), (r) => invoiceRow(r, false), "No invoices yet.");
    fillTable("tbl-invoices", d.invoices, (r) => invoiceRow(r, true), "No invoices yet.");

    fillTable("tbl-attendance", d.attendance, (r) => el("tr", {}, [
      el("td", {}, [el("strong", { text: r.employee_code })]), cell(r.employee_name), cell(r.role_type), cell(r.department),
      cell(timePart(r.check_in_at)), cell(r.check_out_at ? timePart(r.check_out_at) : "Present"),
      cell(Number(r.hours_worked).toFixed(2), "num"), el("td", {}, [statusPill(r.status_flag)]),
    ]), "Nobody has scanned in today.");

    fillTable("tbl-surveys", d.surveys, (r) => el("tr", {}, [
      el("td", {}, [el("strong", { text: r.respondent_name })]), cell(r.organization), cell(r.chamber), cell(r.event_name, "wrap"),
      cell(r.requested_topic), el("td", {}, [pill(Number(r.rating).toFixed(1) + " / 5", Number(r.rating) < 3.5 ? "alert" : "ok")]),
      cell(r.feedback, "wrap"), cell(String(r.loaded_at).slice(0, 10)),
    ]), "No survey responses yet.");

    fillTable("tbl-ops", d.ops, (r) => el("tr", {}, [
      el("td", {}, [el("strong", { text: r.client_name })]), cell(r.email), cell(r.phone_e164), cell(r.practice_area),
      el("td", {}, [pill(r.urgency, r.urgency === "Urgent" ? "alert" : r.urgency === "High" ? "late" : "")]), cell(String(r.loaded_at).slice(0, 16)),
    ]), "No consultation requests yet.");

    fillTable("tbl-quarantine", d.quarantine, (r) => el("tr", {}, [
      cell("#" + r.quarantine_id), el("td", {}, [pill(r.category, "alert")]), cell(r.rejection_reason, "wrap"),
      el("td", { class: "wrap" }, [el("code", { text: r.raw_payload })]), cell(r.logged_at),
    ]), "Nothing in quarantine. Every submission passed validation.");

    fillTable("tbl-runs", d.pipeline_runs, (r) => el("tr", {}, [
      cell("#" + r.run_id), cell(r.run_timestamp), cell(r.trigger_source),
      el("td", {}, [pill(String(r.status).startsWith("SUCCESS") ? "Succeeded" : "Failed", String(r.status).startsWith("SUCCESS") ? "ok" : "alert")]),
      cell(r.invoice_count, "num"), cell(money(r.invoice_revenue_usd), "num"), cell(r.survey_count, "num"),
      cell(r.active_scans_today, "num"), cell(r.quarantine_count, "num"), cell(r.backup_file, "wrap"),
    ]), "No sync has run yet.");

    renderFiles("list-backups", (d.backups || []).map((b) => fileItem(b.name, b.size_kb + " KB", "/backups/" + encodeURIComponent(b.name))),
      "No backups yet. Create one with the button above.");
    renderFiles("list-datasets", (d.datasets || []).map((n) => fileItem(n, "", "/datasets/" + encodeURIComponent(n))),
      "No datasets exported yet. A backup exports them.");
  }

  function reloadCharts(fresh) {
    const stamp = Date.now();
    $("#img-survey").src = "/charts/survey_analytics_all.png?" + (fresh ? "fresh=true&" : "") + "t=" + stamp;
    $("#img-revenue").src = "/charts/firm_revenue_attendance.png?" + (fresh ? "fresh=true&" : "") + "t=" + stamp;
  }

  async function refreshAll(announce) {
    try {
      await loadOverview();
      reloadCharts(true);
      if (announce) toast("Dashboard refreshed.");
    } catch (e) {
      toast(e.message, true);
    }
  }

  /* ---------- forms ---------- */

  const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const PHONE_DIGITS = /^(\+?855|0)?\d{8,9}$/;

  function clearErrors(form) {
    $$(".field-error", form).forEach((n) => n.remove());
    $$("[aria-invalid]", form).forEach((n) => n.removeAttribute("aria-invalid"));
  }

  function fieldError(input, message) {
    const id = input.id + "-error";
    input.setAttribute("aria-invalid", "true");
    const hint = input.getAttribute("aria-describedby");
    input.setAttribute("aria-describedby", hint && !hint.includes(id) ? hint + " " + id : id);
    input.closest(".field").append(el("p", { class: "field-error", id, text: message }));
  }

  function validate(form, rules) {
    clearErrors(form);
    let first = null;
    rules.forEach(([id, test, message]) => {
      const input = $("#" + id);
      if (!test(input.value.trim())) {
        fieldError(input, message);
        first = first || input;
      }
    });
    if (first) first.focus();
    return !first;
  }

  const notBlank = (v) => v.length > 0;

  function setStatus(form, text, kind, link) {
    const s = $(".form-status", form);
    s.className = "form-status" + (kind ? " is-" + kind : "");
    s.textContent = text;
    if (link) s.append(document.createTextNode(" "), link);
  }

  function wireForm(id, rules, buildPayload, endpoint, onDone) {
    const form = $("#" + id);
    form.setAttribute("novalidate", "");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!validate(form, rules)) {
        setStatus(form, "Fix the highlighted fields and try again.", "error");
        return;
      }
      const button = $("button[type=submit]", form);
      button.disabled = true;
      setStatus(form, "Saving.", "");
      try {
        const res = await post(endpoint, buildPayload());
        if (res.status === "ok") {
          onDone(form, res);
          await refreshAll(false);
        } else {
          setStatus(form, "Not saved: " + (res.reason || "the entry was rejected") + ". It was logged under Quarantine.", "error");
          toast("Entry rejected: " + (res.reason || "invalid data"), true);
          await refreshAll(false);
        }
      } catch (e) {
        setStatus(form, e.message, "error");
      } finally {
        button.disabled = false;
      }
    });
  }

  wireForm(
    "form-scan",
    [
      ["scan-code", notBlank, "Enter the staff code."],
      ["scan-name", notBlank, "Enter the staff member's full name."],
    ],
    () => ({
      employee_code: $("#scan-code").value.trim(),
      employee_name: $("#scan-name").value.trim(),
      role_type: $("#scan-role").value,
      department: $("#scan-dept").value,
      action: $("#scan-action").value,
      scanned_at: new Date().toISOString(),
    }),
    "/webhooks/qr-scan",
    (form, r) => {
      const hours = r.action === "CHECK_OUT" ? " " + Number(r.hours_worked).toFixed(2) + " hours logged." : "";
      setStatus(form, r.employee_name + ": " + r.action.replace("_", " ").toLowerCase() + " recorded, " + String(r.status_flag).replace("_", " ").toLowerCase() + "." + hours, "ok");
    },
  );

  wireForm(
    "form-academy",
    [
      ["ac-km", notBlank, "Enter the trainee's name in Khmer."],
      ["ac-en", notBlank, "Enter the trainee's name in Latin letters."],
      ["ac-email", (v) => EMAIL.test(v), "Enter a valid email address."],
      ["ac-phone", (v) => PHONE_DIGITS.test(v.replace(/[\s-]/g, "")), "Enter a Cambodian phone number, for example 012 345 678."],
      ["ac-price", (v) => v !== "" && Number(v) >= 0 && Number(v) <= Number($("#ac-price").max), "Enter a fee between 0 and " + $("#ac-price").max + " USD."],
    ],
    () => ({
      khmer_name: $("#ac-km").value.trim(),
      latin_name: $("#ac-en").value.trim(),
      email: $("#ac-email").value.trim(),
      phone: $("#ac-phone").value.trim(),
      course_title: $("#ac-course").value,
      payment_method: $("#ac-method").value,
      price_usd: Number($("#ac-price").value),
    }),
    "/webhooks/google-form/academy",
    (form, r) => {
      const file = String(r.receipt_path || "").split(/[\\/]/).pop();
      const link = file ? el("a", { href: "/receipts/" + encodeURIComponent(file), target: "_blank", rel: "noopener", text: "Open receipt" }) : null;
      setStatus(form, "Receipt " + r.record.receipt_no + " issued for " + money(r.record.total_usd) + ".", "ok", link);
      form.reset();
      updateKhr();
    },
  );

  wireForm(
    "form-survey",
    [
      ["sv-name", notBlank, "Enter the respondent's name."],
      ["sv-event", notBlank, "Enter the event name."],
      ["sv-rating", (v) => v !== "" && Number(v) >= 1 && Number(v) <= 5, "Enter a rating from 1 to 5."],
    ],
    () => ({
      respondent_name: $("#sv-name").value.trim(),
      organization: $("#sv-org").value.trim() || "Independent",
      chamber: $("#sv-chamber").value,
      event_name: $("#sv-event").value.trim(),
      department: $("#sv-dept").value,
      rating: Number($("#sv-rating").value),
      requested_topic: $("#sv-topic").value,
      feedback: $("#sv-feedback").value.trim(),
    }),
    "/webhooks/google-form/surveys",
    (form, r) => {
      setStatus(form, r.is_low_rating ? "Recorded. The low rating was flagged to the firm's Telegram subscribers." : "Recorded.", "ok");
      form.reset();
    },
  );

  wireForm(
    "form-ops",
    [
      ["ops-name", notBlank, "Enter the client or company name."],
      ["ops-email", (v) => EMAIL.test(v), "Enter a valid email address."],
      ["ops-phone", (v) => PHONE_DIGITS.test(v.replace(/[\s-]/g, "")), "Enter a Cambodian phone number, for example 077 889 900."],
    ],
    () => ({
      client_name: $("#ops-name").value.trim(),
      email: $("#ops-email").value.trim(),
      phone: $("#ops-phone").value.trim(),
      practice_area: $("#ops-area").value,
      urgency: $("#ops-urgency").value,
    }),
    "/webhooks/google-form/ops",
    (form, r) => {
      setStatus(form, "Request saved for " + r.record.client_name + " (" + r.record.phone_e164 + ").", "ok");
      form.reset();
    },
  );

  function updateKhr() {
    const usd = Number($("#ac-price").value);
    $("#ac-khr").value = usd > 0 ? Math.round(usd * FX).toLocaleString() + " KHR" : "";
  }
  $("#ac-price").addEventListener("input", updateKhr);

  /* ---------- actions ---------- */

  async function runSync(button, statusEl) {
    button.disabled = true;
    const note = statusEl || $("#backup-status");
    note.textContent = "Building the backup. This can take a few seconds.";
    try {
      const r = await post("/api/v1/pipeline/run");
      note.textContent = "Backup " + r.backup_zip + " created and verified. " + r.drive_status;
      toast("Backup created: " + r.backup_zip);
      await refreshAll(false);
    } catch (e) {
      note.textContent = "Backup failed: " + e.message;
      toast("Backup failed: " + e.message, true);
    } finally {
      button.disabled = false;
    }
  }

  $("#btn-sync").addEventListener("click", (e) => { showPanel("vault", false); runSync(e.currentTarget); });
  $("#btn-backup").addEventListener("click", (e) => runSync(e.currentTarget));
  $("#btn-refresh").addEventListener("click", () => refreshAll(true));
  $("#btn-charts").addEventListener("click", () => { reloadCharts(true); toast("Charts refreshed."); });

  if (DEMO && $("#btn-demo")) {
    $("#btn-demo").addEventListener("click", async (e) => {
      if (!confirm("Load sample records into the live database?")) return;
      const button = e.currentTarget;
      button.disabled = true;
      try {
        const r = await post("/api/v1/seed-sample-data");
        toast("Sample data loaded: " + (r.academy.ok || 0) + " invoices, " + (r.surveys.ok || 0) + " surveys, " + (r.ops.ok || 0) + " requests.");
        await refreshAll(false);
      } catch (err) {
        toast(err.message, true);
      } finally {
        button.disabled = false;
      }
    });
  }

  /* ---------- Telegram console ---------- */

  async function runCommand(command) {
    const out = $("#tg-out");
    const keys = $("#tg-keys");
    try {
      const r = await post("/api/v1/simulate/telegram", { chat_id: $("#tg-user").value, command });
      out.textContent = r.message || "Command executed.";
      const attach = [r.photo ? "Chart attached: " + r.photo : "", r.document ? "File attached: " + r.document : ""].filter(Boolean).join("  ");
      $("#tg-attach").textContent = attach;
      keys.replaceChildren();
      ((r.reply_markup && r.reply_markup.inline_keyboard) || []).forEach((row) => row.forEach((b) => {
        const btn = el("button", { type: "button", class: "btn btn-secondary btn-sm", text: b.text });
        btn.addEventListener("click", () => runCommand(b.callback_data));
        keys.append(btn);
      }));
    } catch (e) {
      out.textContent = e.message;
    }
  }

  $$("[data-cmd]").forEach((b) => b.addEventListener("click", () => runCommand(b.dataset.cmd)));
  $("#tg-user").addEventListener("change", () => runCommand("/start"));

  /* ---------- start ---------- */

  showPanel(location.hash.slice(1) || "overview", false);
  refreshAll(false);
})();
