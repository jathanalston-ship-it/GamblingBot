import { useState } from "react";

import type { ScanResult } from "../api/types";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import type { Column } from "../components/DataTable";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import { date, num, pct } from "../lib/format";

const cols: Column<ScanResult>[] = [
  { key: "rank", header: "#", align: "right", render: (r) => num(r.rank, 0) },
  { key: "symbol", header: "Symbol" },
  { key: "sector", header: "Sector", render: (r) => r.sector ?? "—" },
  { key: "momentum_score", header: "Momentum", align: "right", render: (r) => num(r.momentum_score, 3) },
  { key: "relative_volume", header: "Rel Vol", align: "right", render: (r) => num(r.relative_volume, 2) },
  { key: "distance_from_ath", header: "vs ATH", align: "right", render: (r) => pct(r.distance_from_ath) },
  {
    key: "passed",
    header: "Gate",
    render: (r) => (r.passed ? <Badge tone="bull">pass</Badge> : <Badge tone="bear">fail</Badge>),
  },
  { key: "as_of", header: "As Of", render: (r) => date(r.as_of) },
];

export default function Scanner() {
  const [passedOnly, setPassedOnly] = useState(false);
  const { data, error, loading } = useApi<ScanResult[]>(
    `/universe/scans?limit=300${passedOnly ? "&passed_only=true" : ""}`,
  );

  return (
    <div>
      <PageTitle title="Scanner" subtitle="Momentum-ranked tradeable universe">
        <label className="flex items-center gap-2 text-sm text-slate-400">
          <input
            type="checkbox"
            checked={passedOnly}
            onChange={(e) => setPassedOnly(e.target.checked)}
          />
          Passed only
        </label>
      </PageTitle>
      <Card>
        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorBox message={error} />
        ) : (
          <DataTable columns={cols} rows={data ?? []} empty="No scan results — run `mrp scan`." />
        )}
      </Card>
    </div>
  );
}
