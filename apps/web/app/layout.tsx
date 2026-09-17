import "./globals.css";

export const metadata = {
  title: "Mchttasarım Marketing OS",
  description: "Mchttasarım Reklam Ajansı için AI destekli pazarlama operasyon platformu",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0 }}>{children}</body>
    </html>
  );
}
