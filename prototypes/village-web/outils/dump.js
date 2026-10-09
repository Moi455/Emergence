const { chromium } = require('/opt/node-tools/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const p = await b.newPage({ viewport: { width: 1280, height: 720 } });
  p.on('pageerror', (e) => console.log('pageerror:', e.message));
  await p.goto(process.argv[2]);
  await p.waitForFunction(() => window.__stats && window.__stats.terrainPending === 0, null, { timeout: 300000 });
  await p.waitForTimeout(9000);
  // one destruction, to time the remesh
  await p.evaluate(() => { const g = window.__game; g.player.fly = false; });
  await p.waitForTimeout(1500);
  const dug = await p.evaluate(async () => {
    const g = window.__game;
    // stand in front of a wall: take a house instance and step back from it
    const big = g.instances.filter((i) => i.mod && i.mod.dy > 20).sort((a, b) => b.mod.dy - a.mod.dy)[0];
    if (big) { g.player.x = big.x + 40; g.player.z = big.z + 40; g.player.y = g.heightAt(g.player.x | 0, g.player.z | 0) + 18; }
    let k = 0;
    for (let a = 0; a < 16; a++) {
      g.player.yaw = a * Math.PI / 8;
      for (const pi of [-0.3, 0, 0.3]) { g.player.pitch = pi; await new Promise((r) => requestAnimationFrame(r)); for (let i = 0; i < 4; i++) if (g.dig()) k++; }
      if (k > 6) break;
    }
    return k;
  });
  console.log('dig hits', dug);
  await p.waitForTimeout(6000);
  const o = await p.evaluate(() => ({
    info: document.getElementById('info').innerText,
    stats: document.getElementById('stats').innerText,
    s: window.__stats,
  }));
  console.log(o.info); console.log('---'); console.log(o.stats); console.log('---');
  console.log(JSON.stringify({ mem: o.s.mem, pre: o.s.pre, tris: o.s.tris, draws: o.s.draws, sunY: o.s.sunY, tod: o.s.tod }, null, 1));
  await b.close();
})().catch((e) => { console.log('ERR', e.message); process.exit(1); });
