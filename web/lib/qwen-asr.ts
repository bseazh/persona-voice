import { spawn } from 'node:child_process';

// Inspect the decoded PCM, not compressed upload size: an encoded file may be silent.
export function wavMetrics(wav: Buffer) {
  for (let offset = 12; offset + 8 <= wav.length;) {
    const size = wav.readUInt32LE(offset + 4);
    if (wav.toString('ascii', offset, offset + 4) === 'data') {
      const end = Math.min(wav.length, offset + 8 + size);
      let sum = 0, peak = 0, count = 0;
      for (let i = offset + 8; i + 2 <= end; i += 2) {
        const value = wav.readInt16LE(i) / 32768;
        sum += value * value;
        peak = Math.max(peak, Math.abs(value));
        count++;
      }
      return { seconds: Number((count / 16000).toFixed(2)),
        rmsDb: Number((20 * Math.log10(Math.max(1e-8, Math.sqrt(sum / Math.max(count, 1))))).toFixed(1)),
        peakDb: Number((20 * Math.log10(Math.max(1e-8, peak))).toFixed(1)) };
    }
    offset += 8 + size + (size % 2);
  }
  return null;
}

export async function toWav(audio: Buffer): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const child = spawn('ffmpeg', ['-v', 'error', '-i', 'pipe:0', '-t', '60', '-ac', '1', '-ar', '16000', '-f', 'wav', 'pipe:1']);
    const chunks: Buffer[] = [];
    const timer = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('录音格式转换超时')); }, 15_000);
    child.on('error', () => { clearTimeout(timer); reject(new Error('服务器音频转换器不可用')); });
    child.stdout.on('data', (data: Buffer) => chunks.push(data));
    child.stderr.resume();
    child.stdin.on('error', () => {});
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code !== 0) reject(new Error('无法解析录音格式，请重新录制'));
      else resolve(Buffer.concat(chunks));
    });
    child.stdin.end(audio);
  });
}
