// Dimensions and radial limits follow the pinned upstream v0.81 config.h.
export const DEFAULT_CONFIG = Object.freeze({
  lowerLength: 120,
  upperLength: 120,
  toolOffset: 54,
  gripperMountX: 34.2,
  gripperMountZ: 4.2,
  shoulderHeight: 130.2,
  baseMin: -90,
  baseMax: 90,
  elbowMin: -142.32,
  elbowMax: -39.21,
  zMin: -140,
  zMax: 150,
});

const radians = degrees => degrees * Math.PI / 180;
const degrees = radiansValue => radiansValue * 180 / Math.PI;
export const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
export const lerpPoint = (a, b, t) => ({
  x: a.x + (b.x - a.x) * t,
  y: a.y + (b.y - a.y) * t,
  z: a.z + (b.z - a.z) * t,
});

export function validateConfig(config) {
  for (const [name, value] of Object.entries(config)) {
    if (!Number.isFinite(value)) throw new Error(`${name} 必须是有限数值`);
  }
  for (const name of ['lowerLength', 'upperLength', 'shoulderHeight']) {
    if (config[name] < 20 || config[name] > 1000) throw new Error('连杆长度与肩轴高度应在 20–1000 mm 内');
  }
  if (config.toolOffset < 0 || config.toolOffset > 500) throw new Error('工具偏移应在 0–500 mm 内');
  for (const axis of ['X', 'Z']) {
    const value = config['gripperMount' + axis];
    if (value !== undefined && (value < -200 || value > 200)) {
      throw new Error('夹爪安装偏移应在 −200 至 200 mm 内');
    }
  }
  if (config.baseMin < -90 || config.baseMax > 90 || config.baseMin >= config.baseMax) {
    throw new Error('底座范围应位于 −90° 至 90°，下限小于上限');
  }
  if (config.elbowMin <= -180 || config.elbowMax >= 0 || config.elbowMin >= config.elbowMax) {
    throw new Error('肘部范围应位于 −180° 至 0°，下限小于上限');
  }
  if (config.zMin >= config.zMax) throw new Error('Z 下限必须小于上限');
  return config;
}

export function homePoint(config) {
  return { x: 0, y: config.upperLength + config.toolOffset, z: config.lowerLength };
}

export function forward(joints, config) {
  const base = radians(joints.base);
  const shoulder = radians(joints.shoulder);
  const upper = radians(joints.shoulder + joints.elbow);
  const radius = config.lowerLength * Math.cos(shoulder)
    + config.upperLength * Math.cos(upper) + config.toolOffset;
  return {
    x: radius * Math.sin(base),
    y: radius * Math.cos(base),
    z: config.lowerLength * Math.sin(shoulder) + config.upperLength * Math.sin(upper),
  };
}

export function inverse(point, config) {
  if (![point.x, point.y, point.z].every(Number.isFinite)) throw new Error('XYZ 必须是有限数值');
  const radius = Math.hypot(point.x, point.y);
  const armRadius = radius - config.toolOffset;
  if (armRadius <= 0) throw new Error('目标距离旋转中心过近，已进入工具偏移区域');
  if (point.y < -0.0001) throw new Error('参考运动学使用前半工作区，Y 应大于或等于 0');
  const cosine = (armRadius ** 2 + point.z ** 2 - config.lowerLength ** 2 - config.upperLength ** 2)
    / (2 * config.lowerLength * config.upperLength);
  if (cosine < -1.0000001 || cosine > 1.0000001) throw new Error('目标超出连杆几何可达范围');
  const elbow = -Math.acos(Math.max(-1, Math.min(1, cosine)));
  const shoulder = Math.atan2(point.z, armRadius)
    - Math.atan2(config.upperLength * Math.sin(elbow), config.lowerLength + config.upperLength * Math.cos(elbow));
  const result = { base: degrees(Math.atan2(point.x, point.y)), shoulder: degrees(shoulder), elbow: degrees(elbow) };
  if (result.base < config.baseMin - 0.001 || result.base > config.baseMax + 0.001) {
    throw new Error('底座角度超出参考范围');
  }
  if (result.elbow < config.elbowMin - 0.001 || result.elbow > config.elbowMax + 0.001) {
    throw new Error('两臂夹角超出参考固件的径向范围');
  }
  if (point.z < config.zMin - 0.001 || point.z > config.zMax + 0.001) {
    throw new Error('Z 超出参考固件的高度范围');
  }
  return result;
}

export function validateLine(start, end, config) {
  // Check the full Cartesian segment, including paths through unreachable space.
  const steps = Math.max(1, Math.ceil(distance(start, end) / 1));
  if (steps > 5000) throw new Error('单段轨迹过长');
  const samples = [];
  for (let i = 0; i <= steps; i++) {
    const point = lerpPoint(start, end, i / steps);
    inverse(point, config);
    samples.push(point);
  }
  return samples;
}
