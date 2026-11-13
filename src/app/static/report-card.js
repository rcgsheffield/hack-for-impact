/* ReportCard: renders one report (a normalised item from /api/submissions or /api/reports/{reference}) as HTML.

   Usage:
     <link rel="stylesheet" href="/ui/report-card.css">
     <script src="/ui/report-card.js"></script>
     el.innerHTML = ReportCard.render(item, { audience: "staff" });    // council triage view
     el.innerHTML = ReportCard.render(item, { audience: "resident" }); // confirmation for the person who reported
     el.innerHTML = ReportCard.hero(item) + ReportCard.render(item, { audience: "resident", hero: true }); // success page
   Needs /ui/ui.css (--ct-* tokens, ct-* classes) on the page.

   Item fields (see submissions.py _from_mock/_from_report/_from_usage): source, form, reference, submitted_at, title,
   location, details, problem, anonymous, lat, lon, triage, raw. Every value is escaped; the output is safe for innerHTML.
*/
(function (global) {
  "use strict";

  const FORM_NAMES = { report_pothole_crack: "Pothole or crack", report_tree: "Tree problem",
                       "road-report-agent": "Road report (prototype)" };
  const SOURCE_LABEL = { form_agent: "Form agent", chat_agent: "Chat agent", browser: "Filled in by hand" };

  // Form fields worth showing, in display order. Anything else is only in the staff view's raw record.
  // "staff: true" fields are council-internal identifiers that mean nothing to a resident.
  const FIELDS = [
    ["rad_problem_location", "Surface"],
    ["rad_road_pothole_depth", "Depth"],
    ["rad_path_pothole_depth", "Depth"],
    ["rad_tree_location", "Where the tree is"],
    ["rad_tree_problem", "Problem with the tree"],
    ["rad_tree_blocking", "Blocking the road or path"],
    ["txt_street_name_about_the_location", "Street"],
    ["txt_postcode_about_the_location", "Postcode"],
    ["txt_file_name_image_of_defect", "Photo"],
    ["txt_responsibility", "Responsibility", { staff: true }],
    ["txt_feature_type", "Feature type", { staff: true }],
    ["txt_usrn_about_the_location", "USRN", { staff: true }],
    ["txt_uprn_about_the_location", "UPRN", { staff: true }],
  ];

  const esc = s => String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** The form fields of a report: raw.fields (form agent) or raw.form_payload (chat agent). */
  function fieldsOf(item) {
    const raw = item.raw || {};
    return raw.fields || raw.form_payload || {};
  }

  // Stored triage (src/app/triage.py, served as item.triage): P1-P4 with a label and a response target.
  const LEVEL = { P1: "high", P2: "high", P3: "normal", P4: "low" };
  // Reasons that describe our process, not the problem; residents don't need them.
  const INTERNAL_REASON = /needs (manual )?review|triage failed|no immediate risk reported/i;
  const URGENT = "If it's still dangerous, phone the council now on 0114 273 4567, or 999 if anyone is in danger.";

  /** {level, priority, label, note, reasons} from the report's stored triage, or null if it has none.
      label + note read as e.g. "Emergency: made safe within 24 hours". No scores or engine. */
  function severity(item) {
    const t = item && item.triage;
    if (!t || !t.priority || !t.label) return null;
    const target = String(t.response_target || "");
    return {
      level: LEVEL[t.priority] || "normal", priority: t.priority, label: t.label,
      note: target ? target.charAt(0).toLowerCase() + target.slice(1) : "",
      reasons: (t.reasons || []).map(String).filter(r => !INTERNAL_REASON.test(r)),
    };
  }

  const ICON = { P1: "⚠", P2: "▲", P3: "●", P4: "↪" };
  const pcls = p => (ICON[p] ? `ct-${p.toLowerCase()}` : "ct-p4");

  /** Priority chip (ct-prio): colour + icon + text. Staff see "P1 Emergency", residents just "Emergency". */
  function chip(sev, opts) {
    if (!sev) return "";
    const text = opts && opts.code === false ? sev.label : `${sev.priority} ${sev.label}`;
    return `<span class="ct-prio ${pcls(sev.priority)}${opts && opts.lg ? " ct-prio--lg" : ""}"><span class="ct-prio__icon" aria-hidden="true">${ICON[sev.priority] || "↪"}</span>${esc(text)}</span>`;
  }

  // Staff views (/dashboard) show the full triage beside the card, so the card shows it only to residents
  // unless opts.triage is true.
  function severityHtml(sev, resident, inHero) {
    if (!sev) return "";
    const target = sev.note ? `<span class="ct-triage__target">${esc(sev.note.charAt(0).toUpperCase() + sev.note.slice(1))}</span>` : "";
    const reasons = resident && sev.reasons.length
      ? `<p class="rc-why-label">Why we suggested this</p><ul class="ct-triage__reasons">${sev.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : "";
    return `<section class="ct-triage ${pcls(sev.priority)} rc-sev rc-sev-${sev.level}" aria-label="Suggested priority">
    ${inHero ? "" : `<div class="ct-triage__head">${chip(sev, { code: !resident })}${target}</div>`}
    ${reasons}
    ${resident && sev.priority === "P1" ? `<p class="rc-urgent"><strong>${esc(URGENT)}</strong></p>` : ""}
    ${resident ? `<p class="ct-triage__foot">This is a suggestion only: the council decides after inspection.</p>` : ""}
  </section>`;
  }

  /** Resident success hero: big reference with a Copy button (data-copy) and the suggested priority. */
  function hero(item, opts) {
    const formName = (opts && opts.forms && opts.forms[item.form]) || FORM_NAMES[item.form] || item.form || "report";
    const sev = severity(item);
    const street = fieldsOf(item).txt_street_name_about_the_location;
    const what = formName.replace(/\s*\(prototype\)$/i, "").toLowerCase();
    return `<section class="ct-hero rc-hero" aria-labelledby="rc-hero-title">
  <div class="ct-hero__icon" aria-hidden="true">✓</div>
  <p class="ct-eyebrow">Report recorded</p>
  <h1 class="ct-hero__title" id="rc-hero-title">Thanks, we've got it</h1>
  <p class="ct-hero__lead">Your ${esc(what)}${street ? ` on ${esc(street)}` : ""} has been recorded. Keep this reference to follow it up.</p>
  <div class="ct-ref rc-hero-ref">
    <span class="ct-ref__label" id="rc-ref-label">Your reference</span>
    <span class="ct-ref__row"><span class="ct-ref__value" aria-labelledby="rc-ref-label">${esc(item.reference) || "–"}</span><button class="ct-copy" type="button" data-copy="${esc(item.reference)}">Copy</button></span>
  </div>
  ${sev ? `<div class="ct-hero__actions">${chip(sev, { code: false, lg: true })}${sev.note ? `<span class="ct-badge ct-pill">Usually ${esc(sev.note)}</span>` : ""}</div>` : ""}
</section>`;
  }

  function fmtTime(s) {
    const t = new Date(s);
    if (!s || isNaN(t)) return "";
    return t.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric",
                                         hour: "2-digit", minute: "2-digit" });
  }

  const located = i => typeof i.lat === "number" && typeof i.lon === "number";
  const osm = i => `https://www.openstreetmap.org/?mlat=${i.lat}&mlon=${i.lon}#map=18/${i.lat}/${i.lon}`;
  const row = (k, v) => `<div class="rc-row"><dt>${esc(k)}</dt><dd>${v}</dd></div>`;

  function fieldRows(item, audience) {
    const f = fieldsOf(item);
    return FIELDS.filter(([key, , opt]) => f[key] && !(opt && opt.staff && audience !== "staff"))
      // The photo itself is shown below; its stored file name means nothing to people.
      .filter(([key]) => !(key === "txt_file_name_image_of_defect" && item.photo_url))
      .map(([key, label]) => row(label, esc(f[key])));
  }

  function render(item, opts) {
    const audience = (opts && opts.audience) === "resident" ? "resident" : "staff";
    if (!item) return `<article class="report-card rc-empty"><div class="ct-empty"><p class="ct-empty__title">Report not found</p></div></article>`;
    const formName = (opts && opts.forms && opts.forms[item.form]) || FORM_NAMES[item.form] || item.form || "Report";
    const sev = severity(item);
    const when = fmtTime(item.submitted_at);
    const resident = audience === "resident";

    const where = item.location || (located(item) ? `${item.lat.toFixed(5)}, ${item.lon.toFixed(5)}` : "");
    const rows = [];
    if (where) {
      rows.push(row("Location", esc(where) + (located(item)
        ? ` <a class="ct-link" href="${osm(item)}" target="_blank" rel="noopener">view on map</a>` : "")
        + (located(item) && item.geo_source && !["form", "device"].includes(item.geo_source)
          ? ` <span class="rc-muted">(map position approximate, from the address as typed)</span>` : "")));
    }
    const fields = fieldRows(item, audience);
    // The problem summary repeats the form fields; show it only when there are none (e.g. hand submissions).
    if (item.problem && !fields.length) rows.push(row("Problem", esc(item.problem)));
    rows.push(...fields);
    // Duplicate group (dedup.py). Staff see the group; residents only a count, never other reports' details.
    const dup = item.duplicate && item.duplicate.group_size > 1 ? item.duplicate : null;
    if (dup && !resident) {
      rows.push(row("Repeated problem", `${dup.group_size} reports in this group`
        + (dup.is_first ? " (this is the first)" : ` · first ${esc(dup.first_reference)}`
          + (dup.distance_m != null ? `, ${esc(dup.distance_m)} m away` : dup.match === "street" ? ", same street (approximate)" : ""))));
    }
    if (!resident) {
      rows.push(row("Received from", esc(SOURCE_LABEL[item.source] || item.source || "")));
      if (item.anonymous === true || item.anonymous === false) {
        rows.push(row("Reporter", item.anonymous ? "Anonymous" : "Named (details not stored)"));
      }
      const cat = (item.raw || {}).suggested_category;
      if (cat !== undefined && cat !== null) rows.push(row("Suggested category", esc(cat)));
    }

    const showRef = !(opts && opts.hero);
    return `<article class="report-card rc-${audience}" aria-label="${esc(formName)} report ${esc(item.reference)}">
  <header class="rc-head">
    <div class="rc-head-text">
      <p class="ct-eyebrow rc-form">${esc(formName)}</p>
      <h3 class="rc-title">${esc(item.title || formName)}</h3>
      ${when ? `<p class="rc-when"><time datetime="${esc(item.submitted_at)}">${esc(when)}</time></p>` : ""}
    </div>
    ${showRef ? `<div class="rc-ref">
      <span class="ct-ref__label">Reference</span>
      <span class="rc-ref-value">${esc(item.reference) || "–"}</span>
    </div>` : ""}
  </header>
  ${resident || (opts && opts.triage) ? severityHtml(sev, resident, !showRef) : ""}
  ${rows.length ? `<dl class="ct-dl rc-fields">${rows.join("")}</dl>` : ""}
  ${/^\/photos\/[0-9a-f]{32}\.jpg$/.test(item.photo_url || "")
    ? `<figure class="rc-photo"><a href="${esc(item.photo_url)}" target="_blank" rel="noopener"><img src="${esc(item.photo_url)}" alt="Photo of the reported problem" loading="lazy"></a>
       <figcaption>${resident ? "Your photo" : "Photo from the resident"} (location and camera details removed)</figcaption></figure>` : ""}
  ${item.details ? `<div class="rc-details"><h4>${resident ? "What you told us" : "Details"}</h4><p>${esc(item.details)}</p></div>` : ""}
  ${resident && dup ? `<div class="ct-dup-note rc-dup"><span class="ct-dup-note__icon" aria-hidden="true">⧉</span><div><strong>You're not the only one.</strong> ${esc(dup.others)} other report${dup.others === 1 ? " has" : "s have"} been made about a similar problem nearby. They're grouped together so the council can see how many people it affects.</div></div>` : ""}
  ${resident
    ? `<div class="ct-notice ct-notice--prototype rc-proto"><span class="ct-notice__icon" aria-hidden="true">!</span><div><strong>Not sent to Sheffield City Council.</strong> This is an unofficial hackathon prototype. Keep the reference number to follow up. For urgent road hazards, phone the council on 0114 273 4567; if someone is in immediate danger, call 999.</div></div>`
    : `<details class="rc-raw"><summary>Raw record</summary><pre>${esc(JSON.stringify(item.raw, null, 2))}</pre></details>`}
</article>`;
  }

  global.ReportCard = { render, hero, chip, severity, fieldsOf, FIELDS, FORM_NAMES };
})(typeof window !== "undefined" ? window : globalThis);
