const { chromium } = require('/opt/node-tools/node_modules/playwright');
(async () => {
  const url = process.argv[2], out = process.argv[3], setup = process.argv[4] || '';
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 1280, height: 720 } });
  p.on('console', (m) => console.log('console:', m.type(), m.text().slice(0, 600)));
  p.on('pageerror', (e) => console.log('pageerror:', e.message));
  await p.goto(url);
  await p.evaluate(() => { window.__lowres = 1; });
  const iv = setInterval(async () => { try { console.log('msg:', await p.evaluate(() => document.getElementById('loadmsg').textContent + ' ' + JSON.stringify(window.__stats||{}))); } catch (e) {} }, 10000);
  await p.waitForFunction(() => window.__stats && window.__stats.terrainPending === 0, null, { timeout: 240000 }).catch((e) => console.log('timeout', e.message));
  if (setup) { await p.evaluate(setup); }
  await p.waitForTimeout(3000);
  await p.waitForFunction(() => window.__stats && window.__stats.terrainPending === 0, null, { timeout: 120000 }).catch(() => {});
  await p.waitForTimeout(1500);
  console.log(JSON.stringify(await p.evaluate(() => window.__stats)));
  console.log(await p.evaluate(() => document.getElementById('stats').innerText + '\n' + document.getElementById('info').innerText));
  await p.screenshot({ path: out, timeout: 180000 });
  clearInterval(iv); await b.close();
})();
