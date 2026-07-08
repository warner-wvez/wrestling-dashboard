'use strict';
// Parse a SmackDown Hotel wrestler profile page (Joomla custom-field markup) into
// a structured object. Pure function over an HTML string; no network. The page
// uses two repeatable-field shapes:
//   - <ul>/<li> lists   (Roles, Finishers, Signature Moves, Theme Songs, Tag Teams, Managers, Rivals)
//   - <table class="fields-container"> grids with a <thead> of column names and
//     <tbody> rows (Promotions History, Face/Heel Turns, Card Positions)
// Everything is defensive: any missing section just yields an empty value.
const { parse } = require('node-html-parser');

const clean = (s) => (s || '').replace(/ /g, ' ').replace(/\s+/g, ' ').trim();

// "(June 2, 2022 - Present)" trailing a list item -> {from, to, text-without-dates}
function splitTrailingDates(text) {
  const m = text.match(/\s*\(([^()]*?)\s*[-–]\s*([^()]*?)\)\s*$/);
  if (m && /\d{4}|present/i.test(m[1] + m[2])) {
    return { body: clean(text.slice(0, m.index)), from: clean(m[1]), to: clean(m[2]) };
  }
  return { body: clean(text), from: null, to: null };
}

// Read a <table class="fields-container"> into [{col: value, ...}] rows keyed by
// the thead labels (lowercased, spaces->_). from/to date columns preserved.
function parseTable(node) {
  const table = node.tagName === 'TABLE' ? node : node.querySelector('table');
  if (!table) return [];
  const cols = table.querySelectorAll('thead th').map((th) => clean(th.text).toLowerCase());
  return table.querySelectorAll('tbody tr').map((tr) => {
    const cells = tr.querySelectorAll('td');
    const row = {};
    cells.forEach((td, i) => { row[cols[i] || `col${i}`] = clean(td.text); });
    return row;
  }).filter((r) => Object.values(r).some(Boolean));
}

// A section's <li> items as plain strings. Inline field-labels (e.g. the
// "Theme Song" caption repeated in each row) are stripped so only the value
// text remains.
function listItems(node) {
  if (!node) return [];
  const lis = node.querySelectorAll('li');
  const src = lis.length ? lis : node.querySelectorAll('.field-entry');
  return src.map((li) => {
    li.querySelectorAll('.field-label').forEach((l) => l.remove());
    return clean(li.text);
  }).filter(Boolean);
}

// "\"The Time Is Now\" by John Cena & Tha Trademarc - Single" -> {title, artist}
function parseTheme(text) {
  let { body, from, to } = splitTrailingDates(text);
  // Strip music-metadata / stable annotations: "- Single", "- with LWO - Team".
  body = body
    .replace(/\s*[-–]\s*with\b[^]*$/i, '')
    .replace(/\s*[-–]\s*(Single|Team|EP|Album)\s*$/i, '')
    .replace(/\s+Single\s*$/i, '')
    .trim();
  const cleanArtist = (a) => clean(a).replace(/\s*[-–]\s*(Single|Team|EP|Album)$/i, '');
  let m = body.match(/^["“]?(.+?)["”]?\s+by\s+(.+)$/i);
  if (m) return { title: clean(m[1]), artist: cleanArtist(m[2]), from, to };
  // No "by": SDH sometimes renders `"Title" Artist feat. ...`.
  m = body.match(/^["“]([^"”]+)["”]\s*(.*)$/);
  if (m) return { title: clean(m[1]), artist: m[2] ? cleanArtist(m[2]) : null, from, to };
  return { title: clean(body.replace(/^["“]|["”]$/g, '')), artist: null, from, to };
}

// Promotions History table: the promotion is a logo <img title="...">, the brand
// (if any) shows as "Brand <name>" text in the same cell. from/to are plain cols.
const PROMO_SHORT = {
  'World Wrestling Entertainment': 'WWE', 'World Wrestling Federation': 'WWF',
  'Ohio Valley Wrestling': 'OVW', 'Ultimate Pro Wrestling': 'UPW',
};
function parsePromotions(node) {
  const table = node && (node.tagName === 'TABLE' ? node : node.querySelector('table'));
  if (!table) return [];
  return table.querySelectorAll('tbody tr').map((tr) => {
    const tds = tr.querySelectorAll('td');
    const cell = tds[0];
    let promotion = null, brand = null;
    if (cell) {
      const img = cell.querySelector('img');
      const title = img && (img.getAttribute('title') || img.getAttribute('alt'));
      promotion = title ? (PROMO_SHORT[title] || title) : null;
      if (!promotion) {
        const c = cell.cloneNode(true);
        c.querySelectorAll('.field-label').forEach((l) => l.remove());
        promotion = clean(c.text) || null;
      }
      const bt = clean(cell.text).match(/Brand\s*(SmackDown|Raw|NXT|ECW|205 Live|Main Event|Heat|Velocity)/i);
      if (bt) brand = bt[1];
    }
    return { promotion, brand, from: tds[1] ? clean(tds[1].text) : null, to: tds[2] ? clean(tds[2].text) : null };
  }).filter((r) => r.promotion || r.from);
}

// First value of a multi-value dated measurement field ("251 lbs (114 kg) (date) 240 lbs...").
function firstMeasure(raw, re) {
  if (!raw) return null;
  const m = raw.match(re);
  return m ? clean(m[1]) : clean(raw.split(/\s*\(\w+ \d/)[0]) || null;
}

const MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December';
// Cut a multi-value dated text field to its first-listed (most recent) value:
// "Death Valley (November 19, 1990 - Present)Houston, Texas (...)" -> "Death Valley"
function firstDatedValue(raw) {
  if (!raw) return raw;
  const m = raw.match(new RegExp(`\\s*\\((?:${MONTHS})\\s+\\d`, 'i'));
  return m ? clean(raw.slice(0, m.index)) : clean(raw);
}

// Drop repeated entries (SDH sometimes lists a move/theme once per era grouping).
function dedupeBy(arr, keyFn) {
  const seen = new Set();
  return arr.filter((x) => { const k = keyFn(x); if (seen.has(k)) return false; seen.add(k); return true; });
}

// "Attitude Adjustment / F-U - Standing Fireman's Carry..." -> {name, description}
function parseMove(text) {
  const { body, from, to } = splitTrailingDates(text);
  const m = body.match(/^(.+?)\s+[-–]\s+(.+)$/);
  if (m) return { name: clean(m[1]), description: clean(m[2]), from, to };
  return { name: clean(body), description: null, from, to };
}

// Ring Names & Gimmicks: each <li> carries a 200x200 gimmick thumbnail
// (img.field-value-icon), the ring name, and a from/to date range. Returns the
// remote image src (absolutized) so a downloader can localise it.
const SDH_ORIGIN = 'https://www.thesmackdownhotel.com';
function parseRingNames(node) {
  if (!node) return [];
  return node.querySelectorAll('li').map((li) => {
    const img = li.querySelector('img.field-value-icon') || li.querySelector('img');
    let src = img && img.getAttribute('src');
    if (src && src.startsWith('/')) src = SDH_ORIGIN + src;
    const nameEl = li.querySelector('.field-entry.name .field-value') || li.querySelector('.name .field-value');
    const from = li.querySelector('.from-date .field-value');
    const to = li.querySelector('.to-date .field-value');
    const name = nameEl ? clean(nameEl.text) : clean(li.text).replace(/\s*\([^)]*\)\s*$/, '');
    return { name, from: from ? clean(from.text) : null, to: to ? clean(to.text) : null, src: src || null };
  }).filter((r) => r.name);
}

// Images History: dated look-snapshots (".roster" cells with an <img> whose
// title/alt is a "Mon YYYY" date). This tracks LOOK changes over time (biker vs
// deadman Undertaker), which Ring Names (name changes only) misses, so it's the
// right source for a time-accurate headshot. Returns newest-first entries with a
// sortable YYYY-MM-01 date and the absolutized image src.
const MON = { jan: '01', feb: '02', mar: '03', apr: '04', may: '05', jun: '06', jul: '07', aug: '08', sep: '09', oct: '10', nov: '11', dec: '12' };
function monYearToISO(label) {
  const m = String(label || '').match(/([A-Za-z]{3})[a-z]*\.?\s+(\d{4})/);
  if (!m) return null;
  const mm = MON[m[1].toLowerCase()];
  return mm ? `${m[2]}-${mm}-01` : null;
}
function parseImagesHistory(node) {
  if (!node) return [];
  const cells = node.querySelectorAll('.roster');
  const src = cells.length ? cells : node.querySelectorAll('img');
  return src.map((cell) => {
    const img = cell.tagName === 'IMG' ? cell : cell.querySelector('img');
    if (!img) return null;
    let s = img.getAttribute('src');
    if (s && s.startsWith('/')) s = SDH_ORIGIN + s;
    const label = img.getAttribute('title') || img.getAttribute('alt') || '';
    return { date: clean(label), iso: monYearToISO(label), src: s || null };
  }).filter((r) => r && r.src);
}

function parseProfile(html, opts = {}) {
  const root = parse(html);
  const art = root.querySelector('.item-page') || root;
  const out = {};

  // ---- Profile Info: flat label/value bio pairs -------------------------
  // Grab the whole bio block, then map each label we care about. Labels repeat
  // across the page (Promotion/Brand), so scope to the Profile Info container.
  const infoHead = art.querySelectorAll('h2').find((h) => /Profile Info/i.test(h.text));
  const bio = {};
  if (infoHead && infoHead.nextElementSibling) {
    const container = infoHead.nextElementSibling;
    container.querySelectorAll('.field-entry').forEach((fe) => {
      const label = fe.querySelector('.field-label');
      const value = fe.querySelector('.field-value');
      if (label && value) {
        const k = clean(label.text).replace(/:$/, '');
        if (!(k in bio)) bio[k] = clean(value.text);
      }
    });
  }
  const pick = (k) => bio[k] || null;
  out.real_name = pick('Real Name');
  out.gender = pick('Gender');
  // "April 23, 1977 (age 49)" -> drop the volatile age
  out.born = (pick('Born') || '').replace(/\s*\(age[^)]*\)/i, '').trim() || null;
  out.nationality = pick('Nationality');
  out.birth_place = firstDatedValue(pick('Birth Place'));
  out.billed_from = firstDatedValue(pick('Billed From'));
  out.height = firstMeasure(pick('Height'), /([\d.,]+\s*ft[^)]*\([^)]*cm[^)]*\))/i);
  out.weight = firstMeasure(pick('Weight'), /([\d.,]+\s*lbs?[^)]*\([^)]*kg[^)]*\))/i);
  out.nicknames = (pick('Nicknames') || '').split(/;|•/).map(clean).filter(Boolean);

  // ---- Named H3 sections -------------------------------------------------
  const sectionNode = (re) => {
    const h = art.querySelectorAll('h2,h3').find((x) => re.test(clean(x.text)));
    return h ? h.nextElementSibling : null;
  };

  out.ring_names = parseRingNames(sectionNode(/^Ring Names/i));
  out.images_history = parseImagesHistory(sectionNode(/^Images History/i));
  out.roles = listItems(sectionNode(/^Roles$/i)).map((t) => {
    const { body, from, to } = splitTrailingDates(t);
    return { role: body, from, to };
  });
  out.finishers = dedupeBy(listItems(sectionNode(/^Finishers?$/i)).map(parseMove), (m) => m.name.toLowerCase());
  out.signature_moves = dedupeBy(listItems(sectionNode(/^Signature/i)).map(parseMove), (m) => m.name.toLowerCase());
  out.themes = dedupeBy(listItems(sectionNode(/^Theme Songs?$/i)).map(parseTheme), (t) => (t.title || '').toLowerCase());
  out.managers = listItems(sectionNode(/^Managers?$/i));
  out.rivals = listItems(sectionNode(/Rivals|Feuds/i));

  // Tag Teams & Stables: "The Nexus - <members> (from - to)"
  out.tag_teams = listItems(sectionNode(/^Tag Teams/i)).map((t) => {
    const { body, from, to } = splitTrailingDates(t);
    const m = body.match(/^(.+?)\s+[-–]\s+(.+)$/);
    return m ? { name: clean(m[1]), members: clean(m[2]), from, to } : { name: clean(body), members: null, from, to };
  });

  // Table-shaped sections
  out.promotions = parsePromotions(sectionNode(/^Promotions History/i));
  const align = sectionNode(/Face\s*\/\s*Heel/i);
  out.alignment_history = align ? parseTable(align) : [];
  const cards = sectionNode(/^Card Positions/i);
  out.card_positions = cards ? parseTable(cards) : [];

  // ---- Titles & Accomplishments: one <ul> per promotion h3 --------------
  // The Titles & Accomplishments H2 is followed by promotion-named H3s whose
  // sibling <ul> lists the reigns. Collect until the next H2.
  // The Titles & Accomplishments H2 is followed by a container DIV holding
  // promotion-named H3s each followed by a <ul> of reigns (plus a Career Awards
  // H3 handled separately). Walk h3/ul in document order within that container.
  out.titles = {};
  const titlesHead = art.querySelectorAll('h2').find((h) => /Titles\s*&\s*Accomplishments/i.test(h.text));
  const titlesBox = titlesHead && titlesHead.nextElementSibling;
  if (titlesBox) {
    let cur = null;
    titlesBox.querySelectorAll('h3, ul').forEach((el) => {
      if (el.tagName === 'H3') { cur = clean(el.text); return; }
      if (el.tagName === 'UL' && cur && !/Career Awards/i.test(cur)) {
        const items = el.childNodes.filter((n) => n.tagName === 'LI').map((li) => clean(li.text)).filter(Boolean);
        if (items.length) out.titles[cur] = (out.titles[cur] || []).concat(items);
      }
    });
  }
  out.career_awards = listItems(sectionNode(/^Career Awards/i));

  if (opts.url) out.source_url = opts.url;
  return out;
}

module.exports = { parseProfile };

// CLI: node parse-profile.js <file.html> [source-url]
if (require.main === module) {
  const fs = require('fs');
  const file = process.argv[2];
  if (!file) { console.error('usage: node parse-profile.js <file.html> [url]'); process.exit(1); }
  const obj = parseProfile(fs.readFileSync(file, 'utf8'), { url: process.argv[3] });
  console.log(JSON.stringify(obj, null, 2));
}
