import type { Metadata } from "next";
import Providers from "@/components/Providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Verolytics — verified data analysis",
  description:
    "Verolytics turns raw data into a cleaned dataset, interactive charts, KPIs and a verified report — every number traced to executed code.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" style={{ colorScheme: "dark" }} suppressHydrationWarning>
      <body>
        {/* ambient Verolytics backdrop — drifting aurora orbs over a faint grid */}
        <div className="nx-backdrop" aria-hidden>
          <div className="nx-grid" />
        </div>
        <div className="relative z-[1]">
          <Providers>{children}</Providers>
        </div>
      </body>
    </html>
  );
}
