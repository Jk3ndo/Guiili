import { getBackendHealth } from "@/lib/api";

export default async function HealthPage() {
  let status: string;
  try {
    const health = await getBackendHealth();
    status = health.status;
  } catch (err) {
    status = `unreachable (${(err as Error).message})`;
  }

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif" }}>
      <h1>Backend health</h1>
      <p>
        Status: <strong>{status}</strong>
      </p>
    </main>
  );
}
