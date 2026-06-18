-- Trade Intelligence — canonical analytical SQL over the `trades` table.
-- Generated from momentum.analytics.queries (the tested source of truth).
-- Parameter :run_id (NULL = all runs); :limit where applicable. Dialect: SQLite
-- (portable; CASE used instead of FILTER). r_multiple is in R; mfe/mae in R.


-- ============================================================
-- overall_summary
-- ============================================================
SELECT
    COUNT(*)                         AS num_trades,
    AVG(r_multiple)                  AS expectancy_r,
    SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) / NULLIF(-SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END), 0)                 AS profit_factor,
    AVG(CASE WHEN net_pnl > 0 THEN r_multiple END) AS avg_winner_r,
    AVG(CASE WHEN net_pnl < 0 THEN r_multiple END) AS avg_loser_r,
    MAX(r_multiple)                  AS largest_winner_r,
    MIN(r_multiple)                  AS largest_loser_r,
    SUM(CASE WHEN net_pnl > 0 THEN r_multiple ELSE 0 END) / NULLIF(SUM(CASE WHEN net_pnl > 0 THEN mfe ELSE 0 END), 0)                 AS trend_capture,
    AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END)                      AS win_rate,
    SUM(net_pnl)                     AS net_pnl
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id);


-- ============================================================
-- performance_by_sector
-- ============================================================
SELECT
    sector AS bucket,
    COUNT(*)                         AS num_trades,
    AVG(r_multiple)                  AS expectancy_r,
    SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) / NULLIF(-SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END), 0)                 AS profit_factor,
    AVG(CASE WHEN net_pnl > 0 THEN r_multiple END) AS avg_winner_r,
    AVG(CASE WHEN net_pnl < 0 THEN r_multiple END) AS avg_loser_r,
    MAX(r_multiple)                  AS largest_winner_r,
    SUM(CASE WHEN net_pnl > 0 THEN r_multiple ELSE 0 END) / NULLIF(SUM(CASE WHEN net_pnl > 0 THEN mfe ELSE 0 END), 0)                 AS trend_capture,
    AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END)                      AS win_rate,
    SUM(net_pnl)                     AS net_pnl,
    AVG(holding_days)                AS avg_holding_days
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id)
GROUP BY sector
ORDER BY expectancy_r DESC;


-- ============================================================
-- performance_by_regime
-- ============================================================
SELECT
    regime_label AS bucket,
    COUNT(*)                         AS num_trades,
    AVG(r_multiple)                  AS expectancy_r,
    SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) / NULLIF(-SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END), 0)                 AS profit_factor,
    AVG(CASE WHEN net_pnl > 0 THEN r_multiple END) AS avg_winner_r,
    AVG(CASE WHEN net_pnl < 0 THEN r_multiple END) AS avg_loser_r,
    MAX(r_multiple)                  AS largest_winner_r,
    SUM(CASE WHEN net_pnl > 0 THEN r_multiple ELSE 0 END) / NULLIF(SUM(CASE WHEN net_pnl > 0 THEN mfe ELSE 0 END), 0)                 AS trend_capture,
    AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END)                      AS win_rate,
    SUM(net_pnl)                     AS net_pnl,
    AVG(holding_days)                AS avg_holding_days
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id)
GROUP BY regime_label
ORDER BY expectancy_r DESC;


-- ============================================================
-- performance_by_entry_reason
-- ============================================================
SELECT
    entry_reason AS bucket,
    COUNT(*)                         AS num_trades,
    AVG(r_multiple)                  AS expectancy_r,
    SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) / NULLIF(-SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END), 0)                 AS profit_factor,
    AVG(CASE WHEN net_pnl > 0 THEN r_multiple END) AS avg_winner_r,
    AVG(CASE WHEN net_pnl < 0 THEN r_multiple END) AS avg_loser_r,
    MAX(r_multiple)                  AS largest_winner_r,
    SUM(CASE WHEN net_pnl > 0 THEN r_multiple ELSE 0 END) / NULLIF(SUM(CASE WHEN net_pnl > 0 THEN mfe ELSE 0 END), 0)                 AS trend_capture,
    AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END)                      AS win_rate,
    SUM(net_pnl)                     AS net_pnl,
    AVG(holding_days)                AS avg_holding_days
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id)
GROUP BY entry_reason
ORDER BY expectancy_r DESC;


-- ============================================================
-- performance_by_exit_reason
-- ============================================================
SELECT
    exit_reason AS bucket,
    COUNT(*)                         AS num_trades,
    AVG(r_multiple)                  AS expectancy_r,
    SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) / NULLIF(-SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END), 0)                 AS profit_factor,
    AVG(CASE WHEN net_pnl > 0 THEN r_multiple END) AS avg_winner_r,
    AVG(CASE WHEN net_pnl < 0 THEN r_multiple END) AS avg_loser_r,
    MAX(r_multiple)                  AS largest_winner_r,
    SUM(CASE WHEN net_pnl > 0 THEN r_multiple ELSE 0 END) / NULLIF(SUM(CASE WHEN net_pnl > 0 THEN mfe ELSE 0 END), 0)                 AS trend_capture,
    AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END)                      AS win_rate,
    SUM(net_pnl)                     AS net_pnl,
    AVG(holding_days)                AS avg_holding_days
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id)
GROUP BY exit_reason
ORDER BY expectancy_r DESC;


-- ============================================================
-- performance_by_holding_bucket
-- ============================================================
SELECT
    CASE WHEN holding_days <= 1 THEN '0-1d' WHEN holding_days <= 5 THEN '2-5d' WHEN holding_days <= 20 THEN '6-20d' WHEN holding_days <= 60 THEN '21-60d' ELSE '60d+' END AS bucket,
    COUNT(*)                         AS num_trades,
    AVG(r_multiple)                  AS expectancy_r,
    SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) / NULLIF(-SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END), 0)                 AS profit_factor,
    AVG(CASE WHEN net_pnl > 0 THEN r_multiple END) AS avg_winner_r,
    AVG(CASE WHEN net_pnl < 0 THEN r_multiple END) AS avg_loser_r,
    MAX(r_multiple)                  AS largest_winner_r,
    SUM(CASE WHEN net_pnl > 0 THEN r_multiple ELSE 0 END) / NULLIF(SUM(CASE WHEN net_pnl > 0 THEN mfe ELSE 0 END), 0)                 AS trend_capture,
    AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END)                      AS win_rate,
    SUM(net_pnl)                     AS net_pnl,
    AVG(holding_days)                AS avg_holding_days
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id)
GROUP BY CASE WHEN holding_days <= 1 THEN '0-1d' WHEN holding_days <= 5 THEN '2-5d' WHEN holding_days <= 20 THEN '6-20d' WHEN holding_days <= 60 THEN '21-60d' ELSE '60d+' END
ORDER BY expectancy_r DESC;


-- ============================================================
-- performance_by_relative_volume
-- ============================================================
SELECT
    CASE WHEN entry_relative_volume >= 2 THEN 'rvol>=2' WHEN entry_relative_volume >= 1 THEN 'rvol_1-2' ELSE 'rvol<1' END AS bucket,
    COUNT(*)                         AS num_trades,
    AVG(r_multiple)                  AS expectancy_r,
    SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) / NULLIF(-SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END), 0)                 AS profit_factor,
    AVG(CASE WHEN net_pnl > 0 THEN r_multiple END) AS avg_winner_r,
    AVG(CASE WHEN net_pnl < 0 THEN r_multiple END) AS avg_loser_r,
    MAX(r_multiple)                  AS largest_winner_r,
    SUM(CASE WHEN net_pnl > 0 THEN r_multiple ELSE 0 END) / NULLIF(SUM(CASE WHEN net_pnl > 0 THEN mfe ELSE 0 END), 0)                 AS trend_capture,
    AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END)                      AS win_rate,
    SUM(net_pnl)                     AS net_pnl,
    AVG(holding_days)                AS avg_holding_days
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id)
GROUP BY CASE WHEN entry_relative_volume >= 2 THEN 'rvol>=2' WHEN entry_relative_volume >= 1 THEN 'rvol_1-2' ELSE 'rvol<1' END
ORDER BY expectancy_r DESC;


-- ============================================================
-- top_winners
-- ============================================================
SELECT symbol, sector, regime_label, entry_reason, exit_reason,
       entry_ts, exit_ts, holding_days, r_multiple, net_pnl, mfe, mae
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id)
ORDER BY r_multiple DESC
LIMIT :limit;


-- ============================================================
-- excursion_capture
-- ============================================================
SELECT
    COUNT(*)        AS num_trades,
    AVG(mfe)        AS avg_mfe_r,
    AVG(mae)        AS avg_mae_r,
    AVG(r_multiple) AS avg_realised_r,
    SUM(CASE WHEN net_pnl > 0 THEN r_multiple ELSE 0 END) / NULLIF(SUM(CASE WHEN net_pnl > 0 THEN mfe ELSE 0 END), 0) AS trend_capture
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id);


-- ============================================================
-- monthly_pnl
-- ============================================================
SELECT
    strftime('%Y-%m', exit_ts) AS month,
    COUNT(*)                   AS num_trades,
    SUM(net_pnl)               AS net_pnl,
    AVG(r_multiple)            AS expectancy_r
FROM trades
WHERE status = 'closed' AND (:run_id IS NULL OR run_id = :run_id) AND exit_ts IS NOT NULL
GROUP BY month
ORDER BY month;
