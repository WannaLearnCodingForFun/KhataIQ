import type { Metadata } from "next";

import { Providers } from "@/components/providers";
import { Shell } from "@/components/shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "KhataIQ",
  description: "Cash-flow evidence for small-business lending",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN">
      <body>
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
