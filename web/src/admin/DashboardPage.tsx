/** Super admin home: payments, commission and earnings across hotels (DECISIONS D19). */
import { Reports } from "../components/Reports";

export function AdminDashboardPage() {
  return (
    <div className="flex flex-col gap-5 bg-page/40 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-sm text-muted">Payments, commission and earnings. Filter by period and hotel.</p>
      </div>
      <Reports scope="admin" />
    </div>
  );
}
