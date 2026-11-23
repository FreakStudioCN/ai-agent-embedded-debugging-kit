import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import * as THREE from './vendor/three.module.js';
import { DEFAULT_CONFIG, forward, homePoint } from './kinematics.mjs';
import { gripperMetrics, gripperPartPose, GRIPPER_MOUNT_BASIS } from './gripper-kinematics.mjs';
import { compileProgram } from './program.mjs';

const model = JSON.parse(await readFile(new URL('./../mechanical/photo_reconstruction/model.json', import.meta.url), 'utf8'));
const p = model.parameters;
const servo = model.parts.find(part => part.name === 'servo_case');
assert.equal(servo.motion, 'fixed');
assert.deepEqual(servo.position, [0, 0, 0]);
assert.ok(p.servo_slot_length > p.servo_slot_width);
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-7, `${a} != ${b}`);
close(gripperMetrics(p, 0).gap, 0);
assert.ok(gripperMetrics(p, 1).gap > 52 && gripperMetrics(p, 1).gap < 53);
for (const opening of [0, .25, .7, 1]) {
  const byName = new Map(model.parts.map(part => [part.name, gripperPartPose(part, p, opening)]));
  const left = byName.get('sector_arm_left');
  const right = byName.get('sector_arm_right');
  close(left.rotation, -right.rotation);
  for (const side of ['left', 'right']) {
    const gear = byName.get('sector_arm_' + side);
    const link = byName.get('parallel_link_' + side);
    const finger = byName.get('finger_' + side);
    const endpoint = new THREE.Vector3(0, p.crank_length, 0)
      .applyAxisAngle(new THREE.Vector3(0, 0, 1), gear.rotation);
    close(gear.position[0] + endpoint.x, finger.position[0]);
    close(gear.position[1] + endpoint.y, finger.position[1]);
    close(link.rotation, gear.rotation);
    close(Math.abs(link.position[0] - gear.position[0]), p.parallel_offset);
    close(finger.rotation, 0);
  }
  for (const base of [-60, 0, 60]) {
    const config = { ...DEFAULT_CONFIG, gripperMountZ: -8 };
    const joints = { base, shoulder: 85, elbow: -90 };
    const theta = joints.shoulder * Math.PI / 180;
    const beta = (joints.shoulder + joints.elbow) * Math.PI / 180;
    const wrist = new THREE.Vector3(100 + config.lowerLength * Math.cos(theta) + config.upperLength * Math.cos(beta),
      -49, 62.5 + config.lowerLength * Math.sin(theta) + config.upperLength * Math.sin(beta));
    const yaw = new THREE.Group();
    yaw.rotation.z = -base * Math.PI / 180;
    const cad = new THREE.Group();
    cad.rotation.z = Math.PI / 2;
    cad.position.set(-49, -100, -62.5);
    yaw.add(cad);
    const mount = new THREE.Group();
    mount.setRotationFromMatrix(new THREE.Matrix4().makeBasis(...GRIPPER_MOUNT_BASIS.map(axis => new THREE.Vector3(...axis))));
    const metrics = gripperMetrics(p, opening);
    mount.position.set(wrist.x + config.gripperMountX, wrist.y, wrist.z + config.gripperMountZ);
    cad.add(mount);
    const actual = mount.localToWorld(new THREE.Vector3(0, metrics.reach, metrics.contactHeight));
    const reference = forward(joints, config);
    const radialShift = config.gripperMountX + metrics.contactHeight - config.toolOffset;
    const expected = {
      x: reference.x + radialShift * Math.sin(base * Math.PI / 180),
      y: reference.y + radialShift * Math.cos(base * Math.PI / 180),
      z: reference.z + config.gripperMountZ - metrics.reach,
    };
    for (const axis of ['x', 'y', 'z']) close(actual[axis], expected[axis]);
  }
}
// The flange sits above the shelf. Local Y increases downward.
// Clear the raised wrist lugs (X=21) and shelf top (Z=-1) by 0.2 mm.
close(DEFAULT_CONFIG.gripperMountX + p.base_thickness - p.mount_height, 21.2);
close(DEFAULT_CONFIG.gripperMountZ - p.mount_thickness, -.8);
assert.throws(() => gripperMetrics(p, NaN));
assert.throws(() => gripperMetrics(p, 1.1));
const config = { ...DEFAULT_CONFIG };
const options = { initialGrip: .7, gripperDuration: .65 };
const program = compileProgram('M5\nG1 X20 F20\nM3\nG4 S0.2\nG1 X0\nM5', homePoint(config), config, 20, options);
assert.equal(program.gripperCount, 3);
assert.equal(program.motionCount, 2);
close(program.duration, .3 * .65 + 1 + .65 + .2 + 1 + .65);
assert.equal(program.endGrip, 1);
const commands = program.segments.filter(segment => segment.type === 'gripper');
close(commands[0].startGrip, .7);
close(commands[0].endGrip, 1);
close(commands[1].endGrip, 0);
assert.deepEqual(commands[1].start, commands[1].end);
const repeated = compileProgram('M3\nM3\nM5', homePoint(config), config, 20, options);
close(repeated.segments[1].duration, 0);
close(repeated.duration, 1.7 * .65);
assert.equal(repeated.gripperCount, 2);
console.log('PASS gripper linkage, downward mounting, TCP transforms and combined G-code timeline');
