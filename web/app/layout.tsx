import type { Metadata } from "next";
import "@fontsource-variable/vazirmatn";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"),
  title: {
    default: "مکالمه‌بان | هوش مکالمه برای تیم فروش",
    template: "%s | مکالمه‌بان",
  },
  description:
    "مرکز عملیات هوشمند برای تحلیل تماس، مربیگری فروشندگان و مدیریت پیگیری مشتریان",
  openGraph: {
    type: "website",
    locale: "fa_IR",
    title: "مکالمه‌بان | هوش مکالمه برای تیم فروش",
    description: "از هر تماس، یک تصمیم بهتر",
    images: [{ url: "/og-redesign.png", width: 1672, height: 941, alt: "مکالمه‌بان، دستیار هوشمند فروش" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "مکالمه‌بان | هوش مکالمه برای تیم فروش",
    description: "از هر تماس، یک تصمیم بهتر",
    images: ["/og-redesign.png"],
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fa" dir="rtl" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
