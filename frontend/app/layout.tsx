import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Control Center",
    template: "%s · Control Center",
  },
  description:
    "Poste de pilotage pour auditer et suivre le marketing agentique des sites connectés à Google.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="fr"
      className={`${GeistSans.variable} ${GeistMono.variable} dark`}
      suppressHydrationWarning
    >
      <body>
        {children}
        <Toaster position="bottom-right" />
      </body>
    </html>
  );
}
