'use strict';
// Rebuild the served root index.html from the edited frontend/index.html template
// WITHOUT a database, by lifting the existing <script id="wrestling-data"> core
// payload out of the current root index.html and re-injecting it into the new
// template (exactly what src/export_to_html.py:inject does). Match data is
// unchanged; this only propagates template/UI edits into the served bundle.
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const BUILT = path.join(ROOT, 'index.html');
const TEMPLATE = path.join(ROOT, 'frontend', 'index.html');

const built = fs.readFileSync(BUILT, 'utf8');
const template = fs.readFileSync(TEMPLATE, 'utf8');

const m = built.match(/<script id="wrestling-data" type="application\/json">[\s\S]*?<\/script>\n?/);
if (!m) throw new Error('no wrestling-data tag in current index.html');
const tag = m[0];

const idx = template.indexOf('<script>');
if (idx < 0) throw new Error('no <script> tag found in frontend/index.html template');
const out = template.slice(0, idx) + tag + template.slice(idx);

fs.writeFileSync(BUILT, out);
console.log(`rebuilt index.html (${(out.length / 1024 / 1024).toFixed(2)} MB, data tag ${(tag.length / 1024 / 1024).toFixed(2)} MB)`);
