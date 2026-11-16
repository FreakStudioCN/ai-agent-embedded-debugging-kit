import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { loadGripperModel } from './gripper-model.js';

const $ = id => document.getElementById(id);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(36, 1, .1, 1500);
camera.up.set(0, 0, 1);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.15;
$('viewport').appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.minDistance = 50;
controls.maxDistance = 700;
scene.add(new THREE.HemisphereLight(0xdce6ff, 0x595064, 2.5));
const key = new THREE.DirectionalLight(0xfff1df, 3.2);
key.position.set(-70, 60, 180);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
Object.assign(key.shadow.camera, { left: -120, right: 120, top: 150, bottom: -90, near: 1, far: 400 });
key.shadow.bias = -.0005;
scene.add(key);
const fill = new THREE.DirectionalLight(0x99bfff, 2.1);
fill.position.set(90, -70, 70);
scene.add(fill);
const undersideLight = new THREE.DirectionalLight(0xdce6ff, 1.5);
undersideLight.position.set(-40, 80, -120);
scene.add(undersideLight);
const floor = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), new THREE.MeshStandardMaterial({ color: 0x283448, roughness: .9 }));
floor.position.z = -20;
floor.receiveShadow = true;
scene.add(floor);
const grid = new THREE.GridHelper(300, 30, 0x697187, 0x3c4b63);
grid.rotation.x = Math.PI / 2;
grid.position.z = -19.95;
grid.material.transparent = true;
grid.material.opacity = .45;
scene.add(grid);

let model;
let opening = .7;
let explode = 0;
let animating = false;
let phase = 0;
let previousTime = 0;
let objects = [];
let gripperModel;

function update() {
  if (!gripperModel) return;
  const { angle, gap, reach } = gripperModel.setOpening(opening, explode);
  $('gap').textContent = Math.max(0, gap).toFixed(1);
  $('reach').textContent = reach.toFixed(1);
  $('angle').textContent = (angle * 180 / Math.PI).toFixed(1);
  $('opening').value = opening;
  $('opening-value').value = Math.round(opening * 100) + '%';
  $('explode-value').value = Math.round(explode * 100) + '%';
}

function setView(name = 'perspective') {
  const positions = { perspective: [125, 160, 140], top: [0, 35, 240], bottom: [75, 150, -160], front: [0, 270, 32] };
  grid.visible = name !== 'bottom';
  floor.visible = name !== 'bottom';
  camera.position.set(...positions[name]);
  controls.target.set(0, 35, explode > 0 ? 20 : 0);
  controls.update();
  document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === name));
}
function stopAnimation() {
  animating = false;
  $('animate-grip').textContent = '演示开合';
}
$('opening').oninput = event => { stopAnimation(); opening = Number(event.target.value); update(); };
$('explode').oninput = event => { explode = Number(event.target.value); update(); };
$('close-grip').onclick = () => { stopAnimation(); opening = 0; update(); };
$('open-grip').onclick = () => { stopAnimation(); opening = 1; update(); };
$('animate-grip').onclick = () => {
  animating = !animating;
  phase = Math.acos(Math.max(-1, Math.min(1, 1 - 2 * opening)));
  $('animate-grip').textContent = animating ? '暂停演示' : '演示开合';
};
$('reset-view').onclick = () => setView();
document.querySelectorAll('[data-view]').forEach(button => { button.onclick = () => setView(button.dataset.view); });
document.querySelectorAll('[data-role]').forEach(input => {
  input.onchange = () => { for (const item of objects) if (item.part.motion === input.dataset.role) item.object.visible = input.checked; };
});
$('wireframe').onchange = event => { for (const item of objects) item.object.material.wireframe = event.target.checked; };

async function init() {
  gripperModel = await loadGripperModel();
  model = gripperModel.model;
  objects = gripperModel.objects;
  scene.add(gripperModel.group);
  opening = model.parameters.default_open_fraction;
  const p = model.parameters;
  const rows = [
    ['底板宽 × 长', `${p.base_width} × ${p.base_length}`], ['底板厚度', p.base_thickness],
    ['安装翻边厚度', p.mount_thickness], ['支撑肋宽 × 凸起高', `${p.servo_rail_width} × ${p.servo_rail_height}`],
    ['安装翻边高度', p.mount_height], ['安装孔中心距', p.mount_hole_pitch],
    ['齿轮轴距', p.pivot_spacing], ['连杆孔距', p.crank_length],
    ['爪指长度', p.jaw_length], ['爪指厚度', p.jaw_height],
  ];
  for (const [label, value] of rows) {
    const row = document.createElement('tr');
    for (const text of [label, value]) { const cell = document.createElement('td'); cell.textContent = text; row.appendChild(cell); }
    $('dimensions').appendChild(row);
  }
  floor.position.z = p.base_thickness - p.mount_height - .5;
  grid.position.z = floor.position.z + .05;
  update();
  $('loading').remove();
  $('status').textContent = '模型就绪 · STEP 回读与实体有效性检查通过';
  $('status').className = 'success';
}
new ResizeObserver(entries => {
  const { width, height } = entries[0].contentRect;
  if (!width || !height) return;
  renderer.setSize(width, height);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}).observe($('viewport'));
function animate(timestamp) {
  requestAnimationFrame(animate);
  const delta = previousTime ? Math.min((timestamp - previousTime) / 1000, .1) : 0;
  previousTime = timestamp;
  if (animating && model) {
    phase += delta * 1.1;
    opening = (1 - Math.cos(phase)) / 2;
    update();
  }
  controls.update();
  renderer.render(scene, camera);
}
setView();
requestAnimationFrame(animate);
init().catch(error => { $('loading').textContent = '模型加载失败 · ' + error.message; $('status').textContent = error.message; });
