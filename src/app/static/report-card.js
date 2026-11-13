/* ReportCard: renders one report (a normalised item from /api/submissions or /api/reports/{reference}) as HTML.

   Usage:
     <link rel="stylesheet" href="/static/report-card.css">
     <script src="/static/report-card.js"></script>
     el.innerHTML = ReportCard.render(item, { audience: "staff" });    // council triage view
     el.innerHTML = ReportCard.render(item, { audience: "resident" }); // confirmation for the person who reported

   Item fields (see submissions.py _from_mock/_from_report/_from_usage): source, form, reference, submitted_at, title,
   location, details, problem, anonymous, lat, lon, raw. Every value is escaped; the output is safe for innerHTML.
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

  /** {level: "high"|"low"|"normal", label, note} or null if the report doesn't say. */
  function severity(item) {
    const f = fieldsOf(item);
    const depth = f.rad_road_pothole_depth || f.rad_path_pothole_depth;
    if (depth) {
      return /^greater/i.test(depth)
        ? { level: "high", label: "Above intervention depth", note: `${depth}: likely to be repaired as a priority` }
        : { level: "low", label: "Below intervention depth", note: `${depth}: monitored, may not need a repair yet` };
    }
    if (f.rad_tree_blocking === "Yes") return { level: "high", label: "Blocking", note: "Tree is blocking the road or path" };
    if (f.rad_tree_problem || f.rad_tree_location) return { level: "normal", label: "Not blocking", note: "" };
    return null;
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
      .map(([key, label]) => row(label, esc(f[key])));
  }

  function render(item, opts) {
    const audience = (opts && opts.audience) === "resident" ? "resident" : "staff";
    if (!item) return `<article class="report-card rc-empty"><p>Report not found.</p></article>`;
    const formName = (opts && opts.forms && opts.forms[item.form]) || FORM_NAMES[item.form] || item.form || "Report";
    const sev = severity(item);
    const when = fmtTime(item.submitted_at);
    const resident = audience === "resident";

    const where = item.location || (located(item) ? `${item.lat.toFixed(5)}, ${item.lon.toFixed(5)}` : "");
    const rows = [];
    if (where) {
      rows.push(row("Location", esc(where) + (located(item)
        ? ` <a href="${osm(item)}" target="_blank" rel="noopener">view on map</a>` : "")
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

    return `<article class="report-card rc-${audience}" aria-label="${esc(formName)} report ${esc(item.reference)}">
  <header class="rc-head">
    <div>
      <p class="rc-form">${esc(formName)}</p>
      <h3 class="rc-title">${esc(item.title || formName)}</h3>
      ${when ? `<p class="rc-when"><time datetime="${esc(item.submitted_at)}">${esc(when)}</time></p>` : ""}
    </div>
    <div class="rc-ref">
      <span class="rc-ref-label">Reference</span>
      <span class="rc-ref-value">${esc(item.reference) || "–"}</span>
    </div>
  </header>
  ${sev ? `<p class="rc-sev rc-sev-${sev.level}"><strong>${esc(sev.label)}</strong>${sev.note ? ` <span>${esc(sev.note)}</span>` : ""}</p>` : ""}
  ${rows.length ? `<dl class="rc-fields">${rows.join("")}</dl>` : ""}
  ${item.details ? `<div class="rc-details"><h4>${resident ? "What you told us" : "Details"}</h4><p>${esc(item.details)}</p></div>` : ""}
  ${resident && dup ? `<p class="rc-note"><strong>You're not the only one.</strong> ${esc(dup.others)} other report${dup.others === 1 ? " has" : "s have"} been made about a similar problem nearby. They're grouped together so the council can see how many people it affects.</p>` : ""}
  ${resident
    ? `<p class="rc-note">Keep the reference number to follow up on this report. <strong>This is an unofficial hackathon prototype: the report has not been sent to Sheffield City Council.</strong> For urgent road hazards, phone the council on 0114 273 4567; if someone is in immediate danger, call 999.</p>`
    : `<details class="rc-raw"><summary>Raw record</summary><pre>${esc(JSON.stringify(item.raw, null, 2))}</pre></details>`}
</article>`;
  }

  global.ReportCard = { render, severity, fieldsOf, FIELDS, FORM_NAMES };
})(typeof window !== "undefined" ? window : globalThis);
