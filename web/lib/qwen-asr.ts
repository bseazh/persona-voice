import { spawn } from 'node:child_process';

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
