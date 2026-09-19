import "./globals.css";
import { AuthGate, AuthProvider } from "./_components/auth";
import AppHeader from "./_components/app-header";
import SessionBootstrap from "./_components/session-bootstrap";

export const metadata = {
  title: "Mchttasarım Satış Operasyon",
  description: "Mchttasarım Reklam Ajansı için işletme keşfi, Google profili ve web sitesi analizi ile satış fırsatı tespiti ve CRM",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body style={{ fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", margin: 0 }} className="app-body">
        <SessionBootstrap />
        <AuthProvider>
          <AppHeader />
          <div className="app-main"><AuthGate>{children}</AuthGate></div>
        </AuthProvider>
        <footer className="app-footer">Bu uygulama Mchttasarım Reklam Ajansı tarafından geliştirilmiştir.</footer>
      </body>
    </html>
  );
}
