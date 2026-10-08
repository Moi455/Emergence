// usage: node shots.js url outprefix views.json
const { chromium } = require('/opt/node-tools/node_modules/playwright');
const fs = require('fs');
(async () => {
  const [url, out, vf] = process.argv.slice(2);
  const views = JSON.parse(fs.readFileSync(vf, 'utf8'));
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 1280, height: 720 } });
  p.on('console', (m) => { if (m.type() !== 'log') console.log('console:', m.type(), m.text().slice(0, 800)); });
  p.on('pageerror', (e) => console.log('pageerror:', e.message));
  await p.goto(url);
  await p.waitForFunction(() => window.__stats && window.__stats.terrainPending === 0, null, { timeout: 300000 });
  await p.evaluate(() => { document.getElementById('hud').classList.add('hidden'); document.getElementById('help').style.display = 'none'; });
  for (let i = 0; i < views.length; i++) {
    const v = views[i];
    await p.evaluate((v) => { const g = window.__game; Object.assign(g.player, v.p); if (v.js) eval(v.js); }, v);
    await p.waitForTimeout(2500);
    await p.waitForFunction(() => window.__stats.terrainPending === 0, null, { timeout: 200000 }).catch(() => {});
    await p.waitForTimeout(v.wait || 6000);
    const st = await p.evaluate(() => window.__stats);
    console.log(i, v.name, JSON.stringify(st.st), 'tvbo', st.tvbo, 'gpu', st.gpuMs.toFixed(0));
    await p.screenshot({ path: `${out}_${v.name}.png`, timeout: 240000 });
  }
  await b.close();
})().catch((e) => { console.log('ERR', e.message); process.exit(1); });
