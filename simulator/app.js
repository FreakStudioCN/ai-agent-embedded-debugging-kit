import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { STLLoader } from './vendor/STLLoader.js';
import { DEFAULT_CONFIG, forward, homePoint, inverse, lerpPoint, validateConfig } from './kinematics.mjs';
import { compileProgram } from './program.mjs';
import { loadGripperModel } from './gripper-model.js';
import { GRIPPER_MOUNT_BASIS } from './gripper-kinematics.mjs';

const $ = id => document.getElementById(id);
const DEG = Math.PI / 180;
const CAD_PATH = './models/upstream/CAD Files/';
const GRIPPER_DURATION = .65; // Full-stroke preview duration, independent of servo calibration.
const A = new THREE.Vector3(100, -49, 62.5);
const B = new THREE.Vector3(11.6879, -49, 143.7420);
const C = new THREE.Vector3(119.5386, -49, 196.3517);
const REST_LOWER = Math.atan2(B.z - A.z, B.x - A.x);
const REST_UPPER = Math.atan2(C.z - B.z, C.x - B.x);
let config = { ...DEFAULT_CONFIG };
let current = homePoint(config);
let joints = inverse(current, config);
let grip = 0.7;
let servoTargets = { i: null, j: null };
let loaded = false;
let playback = null;
let lastTimestamp = 0;

function status(message, kind = '') {
  $('status').textContent = message;
  $('status').className = kind;
}

const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0x182131, 900, 1600);
const camera = new THREE.PerspectiveCamera(38, 1, 0.5, 2500);
camera.up.set(0, 0, 1);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.3;
$('viewport').appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.minDistance = 100;
controls.maxDistance = 1400;
controls.maxPolarAngle = Math.PI * 0.94;

scene.add(new THREE.HemisphereLight(0xd8e6ff, 0x564858, 2.4));
const key = new THREE.DirectionalLight(0xfff5e8, 3.3);
key.position.set(-150, 200, 550);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
Object.assign(key.shadow.camera, { left: -360, right: 360, top: 360, bottom: -360, near: 1, far: 1000 });
key.shadow.bias = -0.0005;
scene.add(key);
const fill = new THREE.DirectionalLight(0x9dbeff, 2.0);
fill.position.set(300, -200, 250);
scene.add(fill);

const materials = {
  body: new THREE.MeshStandardMaterial({ color: 0x535967, roughness: 0.58, metalness: 0.15 }),
  link: new THREE.MeshStandardMaterial({ color: 0x879db8, roughness: 0.5, metalness: 0.24 }),
  base: new THREE.MeshStandardMaterial({ color: 0x7360b2, roughness: 0.5, metalness: 0.13 }),
  wheel: new THREE.MeshStandardMaterial({ color: 0x7b92b0, roughness: 0.62, metalness: 0.18 }),
  metal: new THREE.MeshStandardMaterial({ color: 0xb3bfce, roughness: 0.24, metalness: 0.85 }),
  black: new THREE.MeshStandardMaterial({ color: 0x252b35, roughness: 0.65, metalness: 0.2 }),
  rubber: new THREE.MeshStandardMaterial({ color: 0x181b22, roughness: 0.95 }),
};
const floor = new THREE.Mesh(new THREE.PlaneGeometry(1400, 1400),
  new THREE.MeshStandardMaterial({ color: 0x263144, roughness: 0.92, metalness: 0.05 }));
floor.receiveShadow = true;
scene.add(floor);
const grid = new THREE.GridHelper(1000, 40, 0x5c6680, 0x39475d);
grid.rotation.x = Math.PI / 2;
grid.material.transparent = true;
grid.material.opacity = 0.5;
scene.add(grid);
const axes = new THREE.AxesHelper(70);
scene.add(axes);

const yawGroup = new THREE.Group();
scene.add(yawGroup);
function cadRoot(parent) {
  const group = new THREE.Group();
  group.rotation.z = Math.PI / 2;
  group.position.set(-49, -100, -62.5);
  parent.add(group);
  return group;
}
const moving = cadRoot(yawGroup);
const fixed = cadRoot(scene);
const models = new Map();
const loader = new STLLoader();
const pivotHardware = [];
const gripperMount = new THREE.Group();
gripperMount.name = 'Downward gripper mount';
gripperMount.setRotationFromMatrix(new THREE.Matrix4().makeBasis(
  ...GRIPPER_MOUNT_BASIS.map(axis => new THREE.Vector3(...axis))));
moving.add(gripperMount);
let customGripper;

function mesh(geometry, material, parent = moving) {
  const object = new THREE.Mesh(geometry, material);
  object.castShadow = true;
  object.receiveShadow = true;
  parent.add(object);
  return object;
}

async function loadPart(keyName, file, material, parent = moving) {
  const geometry = await loader.loadAsync(CAD_PATH + file);
  geometry.computeVertexNormals();
  const object = mesh(geometry, material, parent);
  models.set(keyName, object);
  return object;
}

function box(size, center, material, parent = moving) {
  const object = mesh(new THREE.BoxGeometry(...size), material, parent);
  object.position.set(...center);
  return object;
}

function createHardware() {
  // NEMA17 envelopes, belt paths and fasteners are visual approximations.
  for (const y of [-95, -3]) {
    box([42, 38, 42], [100, y, 23.5], materials.black);
    box([42, 5, 42], [100, y < -49 ? -74 : -24, 23.5], materials.metal);
  }
  box([42, 42, 38], [64, -49, -46], materials.black, fixed);
  box([42, 42, 5], [64, -49, -25], materials.metal, fixed);
  const baseCover = box([108, 115, 30], [100, -49, -52.7], materials.base, fixed);
  baseCover.name = 'Simplified base cover';
  for (const y of [-68.8, -36]) {
    const points = [];
    for (let i = 0; i <= 36; i++) {
      const angle = i / 36 * Math.PI;
      points.push(new THREE.Vector3(100 + Math.cos(angle) * 29.3, y, 62.5 + Math.sin(angle) * 29.3));
    }
    for (let i = 0; i <= 24; i++) {
      const angle = Math.PI + i / 24 * Math.PI;
      points.push(new THREE.Vector3(100 + Math.cos(angle) * 6.5, y, 23.5 + Math.sin(angle) * 6.5));
    }
    const curve = new THREE.CatmullRomCurve3(points, true, 'centripetal');
    mesh(new THREE.TubeGeometry(curve, 90, 1.0, 5, true), materials.rubber);
  }
  for (let index = 0; index < 5; index++) {
    const group = new THREE.Group();
    const shaft = mesh(new THREE.CylinderGeometry(3, 3, 48, 18), materials.metal, group);
    shaft.position.y = 0;
    for (const y of [-23, 16]) {
      const bearing = mesh(new THREE.TorusGeometry(5.6, 1.4, 8, 28), materials.metal, group);
      bearing.rotation.x = Math.PI / 2;
      bearing.position.y = y;
    }
    moving.add(group);
    pivotHardware.push(group);
  }
}

function pose(object, oldPivot, newPivot, oldAngle, angle, scale = 1, yShift = 0) {
  const matrix = new THREE.Matrix4().makeTranslation(newPivot.x, newPivot.y + yShift, newPivot.z);
  matrix.multiply(new THREE.Matrix4().makeRotationY(-angle));
  matrix.multiply(new THREE.Matrix4().makeScale(scale, 1, 1));
  matrix.multiply(new THREE.Matrix4().makeRotationY(oldAngle));
  matrix.multiply(new THREE.Matrix4().makeTranslation(-oldPivot.x, -oldPivot.y, -oldPivot.z));
  object.matrixAutoUpdate = false;
  object.matrix.copy(matrix);
}

const tcp = mesh(new THREE.SphereGeometry(3.2, 18, 12),
  new THREE.MeshBasicMaterial({ color: 0xe6bb6e }), scene);
const contactMarker = mesh(new THREE.SphereGeometry(2.4, 16, 10),
  new THREE.MeshBasicMaterial({ color: 0x76e4df }), scene);
const contactPosition = new THREE.Vector3();
const targetMarker = mesh(new THREE.SphereGeometry(5.5, 16, 10),
  new THREE.MeshBasicMaterial({ color: 0xdac190, wireframe: true }), scene);
targetMarker.visible = false;
const pathGroup = new THREE.Group();
scene.add(pathGroup);

function drawPath(samples) {
  for (const child of [...pathGroup.children]) {
    child.geometry.dispose();
    child.material.dispose();
    pathGroup.remove(child);
  }
  let points = [];
  function addLine() {
    if (points.length > 1) {
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: 0xf3c67c, transparent: true, opacity: 0.85 }));
      pathGroup.add(line);
    }
    points = [];
  }
  for (const point of samples) {
    if (point === null) addLine();
    else points.push(new THREE.Vector3(point.x, point.y, point.z));
  }
  addLine();
}

function updateModel() {
  if (!loaded) return;
  const theta = joints.shoulder * DEG;
  const beta = (joints.shoulder + joints.elbow) * DEG;
  const newB = new THREE.Vector3(A.x + config.lowerLength * Math.cos(theta), A.y,
    A.z + config.lowerLength * Math.sin(theta));
  const newC = new THREE.Vector3(newB.x + config.upperLength * Math.cos(beta), A.y,
    newB.z + config.upperLength * Math.sin(beta));
  const offset = new THREE.Vector3(15, 0, 20);
  const lowerAnchor = A.clone().add(new THREE.Vector3(-30, 0, 12));
  pose(models.get('lower'), A, A, REST_LOWER, theta, config.lowerLength / 120);
  pose(models.get('lowerLink'), lowerAnchor, lowerAnchor, REST_LOWER, theta, config.lowerLength / 120);
  pose(models.get('lowerLink2'), lowerAnchor, lowerAnchor, REST_LOWER, theta, config.lowerLength / 120, 44);
  pose(models.get('triplate'), B, newB, 0, 0);
  pose(models.get('upper'), B, newB, REST_UPPER, beta, config.upperLength / 120);
  pose(models.get('upperLink'), B.clone().add(offset), newB.clone().add(offset), REST_UPPER, beta, config.upperLength / 120);
  pose(models.get('upperLink2'), B.clone().add(offset), newB.clone().add(offset), REST_UPPER, beta, config.upperLength / 120, 39);
  pose(models.get('lever'), A, A, REST_UPPER, beta);
  const leverOld = A.clone().add(new THREE.Vector3(-40 * Math.cos(REST_UPPER), 0, -40 * Math.sin(REST_UPPER)));
  const leverNew = A.clone().add(new THREE.Vector3(-40 * Math.cos(beta), 0, -40 * Math.sin(beta)));
  pose(models.get('pleuel'), leverOld, leverNew, REST_LOWER, theta, config.lowerLength / 120);
  pose(models.get('tool'), C, newC, 0, 0);
  pose(models.get('pulley'), A, A, 0, theta - REST_LOWER);
  pose(models.get('pulley2'), A, A, 0, beta - REST_UPPER, 1, 27.5);
  const anchors = [A, newB, newC, newB.clone().add(offset), newC.clone().add(offset)];
  anchors.forEach((anchor, index) => pivotHardware[index].position.copy(anchor));
  const metrics = customGripper.setOpening(grip);
  // The rear flange sits on top of the wrist shelf, as shown in the close-up.
  // Keep the entire flange clear of the raised wrist lugs. The mating faces
  // have 0.2 mm display clearance, verified against the actual STL meshes.
  gripperMount.position.set(newC.x + (config.gripperMountX ?? DEFAULT_CONFIG.gripperMountX),
    newC.y, newC.z + (config.gripperMountZ ?? DEFAULT_CONFIG.gripperMountZ));
  yawGroup.rotation.z = -joints.base * DEG;
  contactPosition.set(0, metrics.reach, metrics.contactHeight);
  gripperMount.localToWorld(contactPosition);
  contactMarker.position.copy(contactPosition);
  $('grip-gap').textContent = metrics.gap.toFixed(1) + ' mm';
  $('grip-contact').textContent = ['x', 'y', 'z'].map(axis => contactPosition[axis].toFixed(1)).join(' / ');
  // Keep physical table placement adjustable without changing the firmware origin.
  floor.position.z = -config.shoulderHeight - 0.7;
  grid.position.z = -config.shoulderHeight;
  tcp.position.set(current.x, current.y, current.z);
}

function syncFields(updateTarget = false) {
  for (const axis of ['x', 'y', 'z']) {
    $('actual-' + axis).textContent = current[axis].toFixed(1);
    if (updateTarget) $('target-' + axis).value = current[axis].toFixed(2);
  }
  for (const name of ['base', 'shoulder', 'elbow']) {
    $(name).value = joints[name];
    $(name + '-value').value = joints[name].toFixed(1) + '°';
  }
  $('grip').value = grip;
  $('grip-value').value = Math.round(grip * 100) + '%';
  $('servo-targets').textContent = ['i', 'j'].map((key, index) =>
    `舵机${index + 1} ${servoTargets[key] === null ? '—' : servoTargets[key].toFixed(1) + '°'}`).join(' · ');
  updateModel();
}

function stopPlayback(message = '') {
  playback = null;
  $('pause').disabled = true;
  $('stop').disabled = true;
  $('pause').textContent = '暂停';
  if (message) status(message);
}

function startProgram(program) {
  stopPlayback();
  drawPath(program.trail);
  playback = { program, index: 0, segmentTime: 0, elapsed: 0, paused: false, entered: false };
  $('pause').disabled = false;
  $('stop').disabled = false;
  targetMarker.position.set(program.end.x, program.end.y, program.end.z);
  targetMarker.visible = true;
  status('正在播放 · 恒定进给时间估算');
}

function applyEvent(segment) {
  if (segment.parameters.I !== undefined) servoTargets.i = segment.parameters.I;
  if (segment.parameters.J !== undefined) servoTargets.j = segment.parameters.J;
}

function tickPlayback(delta) {
  if (!playback || playback.paused) return;
  let remaining = delta;
  const state = playback;
  while (state.index < state.program.segments.length) {
    const segment = state.program.segments[state.index];
    if (!state.entered) {
      applyEvent(segment);
      state.gripStart = grip;
      state.entered = true;
    }
    const available = Math.max(0, segment.duration - state.segmentTime);
    const advance = Math.min(remaining, available);
    state.segmentTime += advance;
    state.elapsed += advance;
    remaining -= advance;
    const progress = segment.duration > 0 ? state.segmentTime / segment.duration : 1;
    if (segment.type === 'gripper') {
      grip = state.gripStart + (segment.endGrip - state.gripStart) * progress;
    }
    current = lerpPoint(segment.start, segment.end, progress);
    joints = inverse(current, config);
    syncFields();
    $('program-progress').textContent = `${state.elapsed.toFixed(1)} / ${state.program.duration.toFixed(1)} s · 第 ${segment.line} 行`;
    $('timeline-progress').style.width = `${state.program.duration ? 100 * state.elapsed / state.program.duration : 100}%`;
    if (state.segmentTime < segment.duration - 0.000001) break;
    state.index++;
    state.segmentTime = 0;
    state.entered = false;
    if (remaining <= 0 && state.index < state.program.segments.length
      && state.program.segments[state.index].duration > 0) break;
  }
  if (state.index === state.program.segments.length) {
    syncFields(true);
    stopPlayback('播放完成 · 已到达预览终点');
    $('timeline-progress').style.width = '100%';
  }
}

function readSpeed() {
  const value = Number($('speed').value);
  if (!Number.isFinite(value) || value < 5 || value > 1000) throw new Error('预览速度应在 5–1000 mm/s 内');
  return value;
}

function compileCurrentProgram(source) {
  return compileProgram(source, current, config, readSpeed(), {
    initialGrip: grip, gripperDuration: GRIPPER_DURATION,
  });
}

function previewTarget() {
  if (!loaded) return;
  try {
    const values = ['x', 'y', 'z'].map(axis => {
      const input = $('target-' + axis);
      if (input.value.trim() === '') throw new Error('请填写完整 XYZ 目标');
      return Number(input.value);
    });
    const point = { x: values[0], y: values[1], z: values[2] };
    inverse(point, config);
    const source = `G1 X${point.x.toFixed(6)} Y${point.y.toFixed(6)} Z${point.z.toFixed(6)} F${readSpeed()}`;
    startProgram(compileCurrentProgram(source));
  } catch (error) { status(error.message, 'error'); }
}

function referencePose() {
  stopPlayback();
  const point = homePoint(config);
  try {
    const result = inverse(point, config);
    current = point;
    joints = result;
    grip = customGripper?.model.parameters.default_open_fraction ?? .7;
    servoTargets = { i: null, j: null };
    syncFields(true);
    drawPath([]);
    targetMarker.visible = false;
    $('timeline-progress').style.width = '0%';
    $('program-progress').textContent = '0.0 / 0.0 s';
    status('参考姿态 · 大臂竖直、小臂水平', 'success');
  } catch (error) { status(error.message, 'error'); }
}

function setView(name = 'perspective') {
  const radius = Math.max(config.lowerLength + config.upperLength + config.toolOffset, 280);
  const center = new THREE.Vector3(0, 55, 30);
  const offsets = {
    perspective: [radius * 1.3, radius * 1.5, radius * 0.95],
    front: [0, radius * 2.25, 15],
    side: [radius * 2.25, 0, 15],
    top: [0, 0.01, radius * 2.25],
  };
  camera.position.copy(center).add(new THREE.Vector3(...offsets[name]));
  controls.target.copy(center);
  controls.update();
  document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === name));
}

$('preview-target').onclick = previewTarget;
$('reference-pose').onclick = referencePose;
$('reset-view').onclick = () => setView();
document.querySelectorAll('[data-view]').forEach(button => { button.onclick = () => setView(button.dataset.view); });
document.querySelectorAll('[data-jog]').forEach(button => {
  button.onclick = () => {
    if (!loaded) return;
    const [axis, direction] = button.dataset.jog.split(',');
    syncFields(true);
    $('target-' + axis).value = current[axis] + Number(direction) * Number($('jog-step').value);
    previewTarget();
  };
});
for (const name of ['base', 'shoulder', 'elbow']) {
  $(name).oninput = () => {
    if (!loaded) return;
    try {
      const next = { ...joints, [name]: Number($(name).value) };
      const point = forward(next, config);
      const checked = inverse(point, config);
      if (Math.abs(checked.shoulder - next.shoulder) > 0.01) throw new Error('该关节组合超出当前解算分支');
      stopPlayback();
      joints = next;
      current = point;
      syncFields(true);
      drawPath([]);
      targetMarker.visible = false;
      status('关节姿态可达', 'success');
    } catch (error) { syncFields(); status(error.message, 'error'); }
  };
}
$('grip').oninput = () => {
  if (!loaded) return;
  if (playback?.program.segments[playback.index]?.type === 'gripper') {
    stopPlayback('已切换为手动夹爪调节');
  }
  grip = Number($('grip').value);
  syncFields();
};
for (const [id, command] of [['close-gripper', 'M3'], ['open-gripper', 'M5']]) {
  $(id).onclick = () => {
    if (!loaded) return;
    try { startProgram(compileCurrentProgram(command)); }
    catch (error) { status(error.message, 'error'); }
  };
}
$('show-path').onchange = event => { pathGroup.visible = event.target.checked; };
$('show-axes').onchange = event => { axes.visible = event.target.checked; };
$('pause').onclick = () => {
  if (!playback) return;
  playback.paused = !playback.paused;
  $('pause').textContent = playback.paused ? '继续' : '暂停';
  status(playback.paused ? '播放已暂停' : '正在播放');
};
$('stop').onclick = () => { stopPlayback('已停止 · 保留当前预览姿态'); syncFields(true); };
const demo = $('program').value;
$('load-demo').onclick = () => { $('program').value = demo; status('已载入示例，从当前预览姿态开始检查'); };
function checkProgram(play = false) {
  if (!loaded) return;
  try {
    const result = compileCurrentProgram($('program').value);
    drawPath(result.trail);
    $('program-progress').textContent = `0.0 / ${result.duration.toFixed(1)} s`;
    status(`检查通过 · ${result.motionCount} 段移动 · ${result.gripperCount} 次开合 · ${result.duration.toFixed(1)} 秒`, 'success');
    if (play) startProgram(result);
  } catch (error) { status(error.message, 'error'); }
}
$('check-program').onclick = () => checkProgram();
$('play-program').onclick = () => checkProgram(true);
$('export-program').onclick = () => {
  try {
    if (!loaded) throw new Error('模型尚未加载完成');
    compileCurrentProgram($('program').value);
    const p = current;
    const preamble = `; RobotArm simulation preview\n; Start XYZ ${p.x.toFixed(3)}, ${p.y.toFixed(3)}, ${p.z.toFixed(3)}\n; L1=${config.lowerLength} L2=${config.upperLength} toolOffset=${config.toolOffset}\n; Gripper start=${grip.toFixed(3)} mountX=${config.gripperMountX ?? DEFAULT_CONFIG.gripperMountX} mountZ=${config.gripperMountZ ?? DEFAULT_CONFIG.gripperMountZ}; preview full stroke=${GRIPPER_DURATION}s\n`;
    const blob = new Blob([preamble + $('program').value + '\n'], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'robot_arm_preview.gcode';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status('已导出程序，文件包含预览起点和模型参数');
  } catch (error) { status(error.message, 'error'); }
};

function applyConfig(next) {
  validateConfig(next);
  inverse(homePoint(next), next);
  stopPlayback();
  config = { ...next };
  for (const name of ['base', 'elbow']) {
    $(name).min = config[name + 'Min'];
    $(name).max = config[name + 'Max'];
  }
  referencePose();
  setView();
  status('参数已应用，已恢复参考姿态', 'success');
}
$('apply-config').onclick = () => {
  try {
    const next = {};
    document.querySelectorAll('[data-config]').forEach(input => {
      next[input.dataset.config] = input.value.trim() === '' ? NaN : Number(input.value);
    });
    applyConfig(next);
  } catch (error) { status(error.message, 'error'); }
};
$('restore-config').onclick = () => {
  document.querySelectorAll('[data-config]').forEach(input => { input.value = DEFAULT_CONFIG[input.dataset.config]; });
  applyConfig(DEFAULT_CONFIG);
};
let cameraTimer = null;
async function checkCamera() {
  try {
    const response = await fetch('/api/camera-status', { cache: 'no-store' });
    const state = await response.json();
    if ($('camera-panel').hidden) return;
    if (state.healthy) {
      if (!$('camera-image').hasAttribute('src')) {
        $('camera-image').src = 'http://127.0.0.1:8766/stream.mjpg?t=' + Date.now();
      }
      $('camera-message').textContent = '实时画面';
    } else {
      $('camera-image').removeAttribute('src');
      $('camera-message').textContent = '摄像头采集不可用，请检查 USB 连接及摄像头服务';
    }
  } catch {
    if (!$('camera-panel').hidden) $('camera-message').textContent = '摄像头状态获取失败';
  }
}
function toggleCamera(show) {
  $('camera-panel').hidden = !show;
  clearInterval(cameraTimer);
  if (show) {
    $('camera-message').textContent = '正在连接摄像头…';
    checkCamera();
    cameraTimer = setInterval(checkCamera, 2500);
  } else $('camera-image').removeAttribute('src');
}
$('camera-toggle').onclick = () => toggleCamera($('camera-panel').hidden);
$('camera-close').onclick = () => toggleCamera(false);
$('camera-image').onerror = () => {
  $('camera-image').removeAttribute('src');
  $('camera-message').textContent = '画面连接中断，正在检查摄像头';
};

async function init() {
  const parts = [
    ['ring', 'robot_belt_arm basering.stl', 'base', fixed],
    ['leg', 'robot_belt_arm leg.stl', 'metal', fixed],
    ['socket', 'robot_belt_arm socket.stl', 'body'],
    ['turntable', 'robot_belt_arm rotategear.stl', 'wheel'],
    ['body', 'robot_belt_arm main_body.stl', 'body'],
    ['endstop', 'robot_belt_arm endstop.stl', 'black'],
    ['stabilizer', 'robot_belt_arm stabilizer.stl', 'metal'],
    ['lower', 'robot_belt_arm lower_shank.stl', 'body'],
    ['lowerLink', 'robot_belt_arm pleuel_bend_lower.stl', 'link'],
    ['triplate', 'robot_belt_arm triplate.stl', 'body'],
    ['upper', 'robot_arm upper_shank.stl', 'body'],
    ['upperLink', 'robot_belt_arm pleuel_bend_upper.stl', 'link'],
    ['pleuel', 'robot_belt_arm pleuel.stl', 'link'],
    ['lever', 'robot_belt_arm lever.stl', 'wheel'],
    ['tool', 'robot_belt_arm manipulator.stl', 'body'],
    ['pulley', 'robot_belt_arm gear_body.stl', 'wheel'],
  ];
  let count = 0;
  await Promise.all(parts.map(async ([name, file, material, parent]) => {
    await loadPart(name, file, materials[material], parent);
    $('loading').textContent = `正在加载真实 STL 零件 ${++count} / ${parts.length}`;
  }));
  for (const [original, copy] of [['lowerLink', 'lowerLink2'], ['upperLink', 'upperLink2'], ['pulley', 'pulley2']]) {
    const object = models.get(original).clone();
    moving.add(object);
    models.set(copy, object);
  }
  const leg = models.get('leg');
  for (const shift of [[-39, 72, 0], [0, 72, 0], [-39, 0, 0]]) {
    const clone = leg.clone();
    clone.position.set(...shift);
    fixed.add(clone);
  }
  $('loading').textContent = '正在装配照片重建夹爪…';
  customGripper = await loadGripperModel();
  gripperMount.add(customGripper.group);
  grip = customGripper.model.parameters.default_open_fraction;
  createHardware();
  loaded = true;
  for (const id of ['preview-target', 'reference-pose', 'check-program', 'play-program', 'close-gripper', 'open-gripper']) $(id).disabled = false;
  $('loading').remove();
  referencePose();
  setView();
}

const resize = new ResizeObserver(entries => {
  const { width, height } = entries[0].contentRect;
  if (!width || !height) return;
  renderer.setSize(width, height);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
});
resize.observe($('viewport'));
function animate(timestamp) {
  requestAnimationFrame(animate);
  const delta = lastTimestamp ? Math.max(0, (timestamp - lastTimestamp) / 1000) : 0;
  lastTimestamp = timestamp;
  try { tickPlayback(Math.min(delta, 0.2)); }
  catch (error) { stopPlayback(); status('播放中断 · ' + error.message, 'error'); }
  controls.update();
  renderer.render(scene, camera);
}
setView();
requestAnimationFrame(animate);
init().catch(error => { $('loading').textContent = '模型加载失败\n' + error.message; status('模型加载失败', 'error'); });
