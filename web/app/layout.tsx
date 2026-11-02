import type { Metadata } from 'next';
import '@livekit/components-styles';
import './globals.css';

export const metadata: Metadata = {
  title: 'Persona Voice · 实时语音助手',
  description: '基于 LiveKit、ElevenLabs 与 DeepSeek 的实时中文语音助手',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
