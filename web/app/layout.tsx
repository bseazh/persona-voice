import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = { title: 'Persona Voice', description: 'AI 外呼工作台' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}

