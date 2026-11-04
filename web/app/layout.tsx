import type { Metadata } from 'next';
import '@livekit/components-styles';
import './globals.css';

export const metadata: Metadata = {
  title: 'Persona Voice · 实时语音助手',
  description: '基于 LiveKit、千问与 DeepSeek 的中文咨询与实时语音工作台',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
