// usage: node dump_instances.js url out.json — writes the village plan (module name, pivot in voxels, quarter turns)
const { chromium } = require('/opt/node-tools/node_modules/playwright');
const fs = require('fs');
(async () => {
  const [url, out] = process.argv.slice(2);
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 640, height: 360 } });
  await p.goto(url);
  await p.waitForFunction(() => window.__game, null, { timeout: 300000 });
  const list = await p.evaluate(() => window.__game.instances.map((i) => [i.mod.name, i.x, i.y, i.z, i.r]));
  fs.writeFileSync(out, JSON.stringify(list));
  console.log('instances', list.length);
  await b.close();
})().catch((e) => { console.log('ERR', e.message); process.exit(1); });
