import assert from 'node:assert/strict';
import { DEFAULT_CONFIG as config, forward, homePoint, inverse, validateLine } from './kinematics.mjs';
import { compileProgram } from './program.mjs';

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-7, `${a} != ${b}`);
const home = homePoint(config);
const homeAngles = inverse(home, config);
close(homeAngles.base, 0);
close(homeAngles.shoulder, 90);
close(homeAngles.elbow, -90);
let checked = 0;
for (let base = -80; base <= 80; base += 20) {
  for (let shoulder = 20; shoulder <= 140; shoulder += 15) {
    for (let elbow = -140; elbow <= -40; elbow += 10) {
      const expected = { base, shoulder, elbow };
      const point = forward(expected, config);
      let actual;
      try { actual = inverse(point, config); }
      catch { continue; }
      close(actual.base, base);
      close(actual.shoulder, shoulder);
      close(actual.elbow, elbow);
      const roundtrip = forward(actual, config);
      for (const axis of ['x', 'y', 'z']) close(roundtrip[axis], point[axis]);
      checked++;
    }
  }
}
assert.ok(checked > 300);
assert.throws(() => inverse({ x: 0, y: 999, z: 0 }, config), /可达/);
assert.throws(() => inverse({ x: NaN, y: 100, z: 100 }, config), /有限/);
assert.throws(() => inverse({ x: 0, y: -174, z: 120 }, config), /前半/);
// Valid endpoints can still pass through an invalid inner region.
assert.throws(() => validateLine({ x: -180, y: 0, z: 80 }, { x: 180, y: 0, z: 80 }, config));
const program = compileProgram('g1x10f5\nG1 Y180\nG4 S0.5\nM3\nM5', home, config);
close(program.end.x, 10);
close(program.end.y, 180);
close(program.end.z, 120);
assert.equal(program.motionCount, 2);
close(program.duration, 3.7);
assert.throws(() => compileProgram('G91', home, config), /第 1 行/);
assert.throws(() => compileProgram('G1 X10 X20', home, config), /重复/);
assert.throws(() => compileProgram('G4 S-1', home, config), /0–3600/);
assert.throws(() => compileProgram('M18 X10', home, config), /不支持 X/);
assert.throws(() => compileProgram('G1 X999', home, config), /第 1 行/);
assert.throws(() => compileProgram('G1 F4', home, config), /5–1000/);
const reference = compileProgram('G1 X10 F5\nG28\nG1 X5', home, config);
close(reference.end.x, 5);
close(reference.end.y, 174);
assert.ok(reference.trail.includes(null));
console.log(`PASS ${checked} FK/IK round trips, boundary checks, path checks and G-code cases`);
