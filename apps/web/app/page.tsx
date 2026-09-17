async function getApiHealth() {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/health`, { cache: "no-store" });
    if (!res.ok) return { status: "unreachable" };
    return res.json();
  } catch {
    return { status: "unreachable" };
  }
}

export default async function HomePage() {
  const health = await getApiHealth();

  return (
    <main style={{ padding: 32, maxWidth: 640 }}>
      <h1>Mchttasarım Marketing OS</h1>
      <p>Sprint 0 iskeleti — bölge/sektör seçimi ve işletme keşfi Sprint 1&apos;de eklenecek.</p>
      <p>
        API durumu: <strong>{health.status}</strong>
        {health.env ? ` (${health.env})` : ""}
      </p>
    </main>
  );
}
