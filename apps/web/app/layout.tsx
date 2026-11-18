import type { Metadata } from "next";
import { ApolloProvider } from "../src/apollo-client";
import { Shell } from "../src/public-ui";
import "./style.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.SITE_URL || "http://localhost:3000"),
  title: { default: "Open Source Radar", template: "%s · Open Source Radar" },
  description: "Каталог Python-библиотек",
  robots: { index: Boolean(process.env.SITE_URL), follow: true },
};

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" data-scroll-behavior="smooth">
      <body>
        <ApolloProvider>
          <Shell>{children}</Shell>
        </ApolloProvider>
      </body>
    </html>
  );
}
