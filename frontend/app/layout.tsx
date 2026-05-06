import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Mykare Voice AI – Aria, your healthcare receptionist",
  description:
    "Talk to Aria, an AI voice receptionist that books, modifies and cancels appointments in real time.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
