import type { Trade } from "../api/types";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import { date, money, num, signed } from "../lib/format";

const cols: Column<Trade>[] = [
  { key: "symbol", header: "Symbol" },
  { key: "direction", header: "Side" },
  { key: "status", header: "Status" },
  { key: "entry_price", header: "Entry", align: "right", render: (t) => num(t.entry_price) },
  { key: "exit_price", header: "Exit", align: "right", render: (t) => num(t.exit_price) },
  { key: "r_multiple", header: "R", align: "right", render: (t) => signed(t.r_multiple) },
  {
    key: "net_pnl",
    header: "P&L",
    align: "right",
    render: (t) => (
      <span className={(t.net_pnl ?? 0) >= 0 ? "text-bull" : "text-bear"}>{money(t.net_pnl)}</span>
    ),
  },
  { key: "sector", header: "Sector", render: (t) => t.sector ?? "—" },
  { key: "entry_ts", header: "Entered", render: (t) => date(t.entry_ts) },
];

export default function TradeJournal() {
  const { data, error, loading } = useApi<Trade[]>("/trades?limit=300");
  return (
    <div>
      <PageTitle title="Trade Journal" subtitle="Every entry, exit and its R-multiple" />
      <Card>
        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorBox message={error} />
        ) : (
          <DataTable columns={cols} rows={data ?? []} empty="No trades recorded yet." />
        )}
      </Card>
    </div>
  );
}
