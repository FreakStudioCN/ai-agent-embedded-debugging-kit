import { distance, homePoint, inverse, validateLine } from './kinematics.mjs';

function parseLine(text) {
  const source = text.replace(/\([^)]*\)/g, '').split(';')[0].replace(/\s/g, '').toUpperCase();
  if (!source) return null;
  const head = source.match(/^([GM])(\d+)/);
  if (!head) throw new Error('需要 G 或 M 指令');
  let remaining = source.slice(head[0].length);
  const parameters = {};
  while (remaining) {
    const match = remaining.match(/^([XYZFIJS])([+-]?(?:\d+(?:\.\d*)?|\.\d+))/);
    if (!match) throw new Error(`无法解析参数 ${remaining}`);
    if (match[1] in parameters) throw new Error(`参数 ${match[1]} 重复`);
    const value = Number(match[2]);
    if (!Number.isFinite(value)) throw new Error('参数必须是有限数值');
    parameters[match[1]] = value;
    remaining = remaining.slice(match[0].length);
  }
  return { code: head[1] + Number(head[2]), parameters };
}

function checkParameters(parameters, allowed) {
  for (const key of Object.keys(parameters)) {
    if (!allowed.includes(key)) throw new Error(`此指令不支持 ${key} 参数`);
  }
}

export function compileProgram(text, start, config, defaultSpeed = 20, options = {}) {
  let grip = options.initialGrip ?? .7;
  const gripperDuration = options.gripperDuration ?? 0;
  if (!Number.isFinite(grip) || grip < 0 || grip > 1
    || !Number.isFinite(gripperDuration) || gripperDuration < 0 || gripperDuration > 10) {
    throw new Error('夹爪初始开度或预览时长无效');
  }
  const lines = text.split(/\r?\n/);
  if (lines.length > 2000) throw new Error('程序最多支持 2000 行');
  let point = { ...start };
  let speed = defaultSpeed;
  let duration = 0;
  let motionCount = 0;
  let gripperCount = 0;
  const segments = [];
  const trail = [{ ...point }];
  for (let index = 0; index < lines.length; index++) {
    try {
      const parsed = parseLine(lines[index]);
      if (!parsed) continue;
      const { code, parameters: p } = parsed;
      let segment;
      if (code === 'G0' || code === 'G1' || code === 'G28') {
        checkParameters(p, code === 'G28' ? '' : 'XYZFIJ');
        if (p.F !== undefined) {
          if (p.F < 5 || p.F > 1000) throw new Error('预览速度 F 应在 5–1000 mm/s 内');
          speed = p.F;
        }
        for (const key of ['I', 'J']) {
          if (p[key] !== undefined && (p[key] < 0 || p[key] > 180)) {
            throw new Error('舵机目标角度应在 0–180° 内');
          }
        }
        const end = code === 'G28' ? homePoint(config) : {
          x: p.X ?? point.x, y: p.Y ?? point.y, z: p.Z ?? point.z,
        };
        let samples;
        if (code === 'G28') {
          inverse(end, config);
          samples = [end];
        } else {
          samples = validateLine(point, end, config);
        }
        const length = distance(point, end);
        const seconds = code === 'G28' ? 0 : length / speed;
        segment = { type: code === 'G28' ? 'reference' : 'move', start: { ...point }, end,
          duration: seconds, speed, parameters: p, line: index + 1, code };
        if (code === 'G28') trail.push(null);
        trail.push(...samples);
        if (trail.length > 100000) throw new Error('轨迹采样超过 100000 点');
        point = { ...end };
        if (length > 0) motionCount++;
      } else if (code === 'G4') {
        checkParameters(p, 'S');
        if (p.S === undefined || p.S < 0 || p.S > 3600) throw new Error('G4 的 S 应在 0–3600 秒内');
        segment = { type: 'dwell', start: { ...point }, end: { ...point }, duration: p.S,
          parameters: p, line: index + 1, code };
      } else if (code === 'M3' || code === 'M5') {
        checkParameters(p, '');
        const endGrip = code === 'M3' ? 0 : 1;
        const change = Math.abs(endGrip - grip);
        segment = { type: 'gripper', start: { ...point }, end: { ...point },
          startGrip: grip, endGrip, duration: change * gripperDuration,
          parameters: p, line: index + 1, code };
        if (change > 0) gripperCount++;
        grip = endGrip;
      } else if (['M1', 'M2', 'M6', 'M7', 'M17', 'M18', 'M121', 'M122', 'M123'].includes(code)) {
        checkParameters(p, '');
        segment = { type: 'event', start: { ...point }, end: { ...point }, duration: 0,
          parameters: p, line: index + 1, code };
      } else {
        throw new Error(`暂不支持 ${code}`);
      }
      segment.startTime = duration;
      duration += segment.duration;
      segment.endTime = duration;
      segments.push(segment);
    } catch (error) {
      throw new Error(`第 ${index + 1} 行 · ${error.message}`);
    }
  }
  if (!segments.length) throw new Error('请输入至少一条指令');
  return { segments, trail, duration, motionCount, gripperCount,
    start: { ...start }, end: point, endGrip: grip };
}
