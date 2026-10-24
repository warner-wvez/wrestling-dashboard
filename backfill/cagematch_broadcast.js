// Cagematch's broadcast date for a list of TV events, read in a browser tab.
//
// Cagematch's results lists (the July cache the backfill reads) give a taped
// show's taping night only; each event's own page also gives "Broadcast date".
// The site answers scripts with a JavaScript redirect, so this runs in an open
// cagematch.net tab, one page every 3 seconds, like a person paging through.
//
// Usage: open https://www.cagematch.net/ in Chrome, set window.CM_NRS to the
// event numbers, paste this into the console, and save the printed JSON to
// backfill/cache/cagematch_broadcast.json (merge with what is there).
(async () => {
  const out = {};
  for (const nr of window.CM_NRS || []) {
    try {
      const html = await (await fetch(`/?id=1&nr=${nr}`, { credentials: 'include' })).text();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const box = {};
      for (const row of doc.querySelectorAll('.InformationBoxRow')) {
        const k = row.querySelector('.InformationBoxTitle');
        const v = row.querySelector('.InformationBoxContents');
        if (k && v) box[k.innerText.replace(/:\s*$/, '').trim()] = v.innerText.trim();
      }
      out[nr] = box;
    } catch (e) {
      out[nr] = { error: String(e) };
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  console.log(JSON.stringify(out));
  return out;
})();
