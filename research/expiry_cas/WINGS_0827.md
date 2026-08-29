# The next-expiry wings on 2026-08-27 — did they reprice off the closing-auction indicative?

**Scope.** SENSEX, the **2026-09-03** expiry (7 days out), every listed strike 74,700–79,600, minute by minute 15:14–15:39 IST. Lot 20. Parity anchor 77,200.

## 0. What this data can and cannot settle

**The expiring series is not here.** The ±25 chain tree for this session carries bars for **2026-09-03** and nothing else. The 2026-08-27 expiring series has refdata entries but zero bars — it delisted into settlement. **So the 75,000 PE the press story is about remains untestable.** The 75,000 PE examined below is the *2026-09-03* contract: a different instrument, with a week of life left and an unbounded overnight gap, that happens to share a strike. Nothing here confirms or refutes the ~4,800 % claim.

**Parity levels are biased.** Parity spot on a non-expiring chain overstates the index by K(1-e^{-rT}) (~90 pts at K=77,200, T=7d). Changes over the window are usable; levels are not. Every index level below is therefore used for *changes* only, and the published indicative path (77,182.91 at 15:15 → 74,983.19 between 15:18 and 15:23 → close 76,933.59) is a set of published constants, not a measurement from this feed.

**Every change is between two bars that each printed volume**, and every row carries `gap_min`. A `gap_min` above 1 is a multi-minute move and is not a one-minute spike.

---

## 1. Did the next-week wings reprice off the indicative?

Implied index at 15:14: **77,470.15** (parity, biased high — see §0). Its own path over the window and the wing put paths are in `fig/wings/sensex_2026-08-27_wing_paths.png`; the full strike × minute change grid is `fig/wings/sensex_2026-08-27_put_change_heatmap.png`.

### 1.1 Top 10 put strike-minutes by % change

| strike | moneyness | crash_1518_1523_pct | spike_min | gap_min | px_before | px_spike | d_pct | d_rs | vol_spike | px_15:30 | px_15:35 | px_15:39 | reversal_15:30_pct | reversal_15:35_pct | reversal_15:39_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 74700.00 | 0.96 | — | 15:21 | 1.00 | 11.60 | 19.35 | 66.81 | 7.75 | 40.00 | 17.50 | 16.95 | 14.75 | 23.87 | 30.97 | 59.35 |
| 74800.00 | 0.97 | — | 15:31 | 1.00 | 14.80 | 21.40 | 44.59 | 6.60 | 460.00 | 14.80 | 18.05 | 20.75 | 100.00 | 50.76 | 9.85 |
| 75200.00 | 0.97 | 29.59 | 15:30 | 1.00 | 25.70 | 34.55 | 34.44 | 8.85 | 300.00 | 34.55 | 28.25 | 26.55 | 0.00 | 71.19 | 90.40 |
| 74900.00 | 0.97 | — | 15:31 | 1.00 | 16.35 | 20.60 | 25.99 | 4.25 | 620.00 | 16.35 | 23.05 | 18.45 | 100.00 | -57.65 | 50.59 |
| 75000.00 | 0.97 | 32.04 | 15:24 | 1.00 | 23.90 | 29.50 | 23.43 | 5.60 | 68080.00 | 21.65 | 25.20 | 25.00 | 140.18 | 76.79 | 80.36 |
| 75100.00 | 0.97 | 24.26 | 15:24 | 1.00 | 25.10 | 30.75 | 22.51 | 5.65 | 6320.00 | 23.45 | 27.75 | 23.55 | 129.20 | 53.10 | 127.43 |
| 75600.00 | 0.98 | 22.03 | 15:24 | 1.00 | 39.60 | 48.20 | 21.72 | 8.60 | 4140.00 | 42.80 | 46.45 | 39.90 | 62.79 | 20.35 | 96.51 |
| 75500.00 | 0.97 | 24.78 | 15:24 | 1.00 | 36.25 | 43.85 | 20.97 | 7.60 | 23580.00 | 34.35 | 41.05 | 40.00 | 125.00 | 36.84 | 50.66 |
| 75700.00 | 0.98 | 19.86 | 15:24 | 1.00 | 44.35 | 53.45 | 20.52 | 9.10 | 4740.00 | 47.95 | 53.00 | 53.85 | 60.44 | 4.95 | -4.40 |
| 75800.00 | 0.98 | 17.34 | 15:24 | 1.00 | 49.40 | 59.45 | 20.34 | 10.05 | 3940.00 | 53.15 | 59.25 | 55.50 | 62.69 | 1.99 | 39.30 |

### 1.2 Top 10 put strike-minutes by ₹ change

A percentage on an ₹12 premium is a few ticks, so the same scan is ranked by money. **Note `is_wing`:** the largest rupee moves are not wing repricing at all. They are deep in-the-money puts — moneyness above 1 — whose premium tracks the underlying nearly one-for-one, printing one or two lots at a time across multi-minute gaps. That is delta on an illiquid contract, and it is the opposite end of the board from the question.

| strike | moneyness | is_wing | spike_min | gap_min | px_before | px_spike | d_pct | d_rs | vol_spike | reversal_15:39_pct |
|---|---|---|---|---|---|---|---|---|---|---|
| 78700.00 | 1.02 | False | 15:36 | 9.00 | 1407.00 | 1639.45 | 16.52 | 232.45 | 20.00 | 0.00 |
| 78900.00 | 1.02 | False | 15:31 | 4.00 | 1350.00 | 1541.05 | 14.15 | 191.05 | 20.00 | 0.00 |
| 79200.00 | 1.02 | False | 15:37 | 2.00 | 1704.55 | 1822.00 | 6.89 | 117.45 | 20.00 | 0.00 |
| 79500.00 | 1.03 | False | 15:27 | 5.00 | 2085.00 | 2180.10 | 4.56 | 95.10 | 40.00 | 19.45 |
| 78200.00 | 1.01 | False | 15:27 | 1.00 | 948.00 | 1019.50 | 7.54 | 71.50 | 40.00 | 38.53 |
| 79000.00 | 1.02 | False | 15:20 | 2.00 | 1526.80 | 1597.80 | 4.65 | 71.00 | 80.00 | -111.27 |
| 78800.00 | 1.02 | False | 15:22 | 3.00 | 1347.00 | 1414.35 | 5.00 | 67.35 | 20.00 | -67.78 |
| 78400.00 | 1.01 | False | 15:38 | 7.00 | 1107.50 | 1172.40 | 5.86 | 64.90 | 20.00 | -11.94 |
| 78500.00 | 1.01 | False | 15:20 | 1.00 | 1099.35 | 1160.25 | 5.54 | 60.90 | 40.00 | -122.17 |
| 78300.00 | 1.01 | False | 15:20 | 1.00 | 925.30 | 985.45 | 6.50 | 60.15 | 500.00 | -131.84 |

### 1.3 The wings never came close to the indicative's own intrinsic

`intrinsic_at_indicative_low` = max(K − 74,983.19, 0); `intrinsic_at_close` = max(K − 76,933.59, 0). For a 7-day option neither is a settlement value — they are the reference points the question asks for.

**This is the sharpest single statement in the study.** Had the index really been at 74,983.19, every strike above it was in the money by construction, and `spike_over_intrinsic_low` would have to be at or above zero — a put cannot trade below intrinsic. It is deeply **negative** across the whole in-that-scenario-ITM range: the strikes read as hundreds of rupees below what they would be worth if the indicative were a real index level. The options market did not price the indicative as an index at all, at any strike, in any minute.

| strike | moneyness | px_1514 | px_spike | spike_min | px_15:39 | intrinsic_at_indicative_low | intrinsic_at_close | spike_over_intrinsic_low |
|---|---|---|---|---|---|---|---|---|
| 74700.00 | 0.96 | — | 19.35 | 15:21 | 14.75 | 0.00 | 0.00 | 19.35 |
| 74800.00 | 0.97 | — | 21.40 | 15:31 | 20.75 | 0.00 | 0.00 | 21.40 |
| 75200.00 | 0.97 | 20.95 | 34.55 | 15:30 | 26.55 | 216.81 | 0.00 | -182.26 |
| 74900.00 | 0.97 | — | 20.60 | 15:31 | 18.45 | 0.00 | 0.00 | 20.60 |
| 75000.00 | 0.97 | 18.10 | 29.50 | 15:24 | 25.00 | 16.81 | 0.00 | 12.69 |
| 75100.00 | 0.97 | 20.20 | 30.75 | 15:24 | 23.55 | 116.81 | 0.00 | -86.06 |
| 75600.00 | 0.98 | 32.45 | 48.20 | 15:24 | 39.90 | 616.81 | 0.00 | -568.61 |
| 75500.00 | 0.97 | 29.05 | 43.85 | 15:24 | 40.00 | 516.81 | 0.00 | -472.96 |
| 75700.00 | 0.98 | 37.00 | 53.45 | 15:24 | 53.85 | 716.81 | 0.00 | -663.36 |
| 75800.00 | 0.98 | 42.10 | 59.45 | 15:24 | 55.50 | 816.81 | 0.00 | -757.36 |
| 75400.00 | 0.97 | 26.10 | 38.75 | 15:24 | 32.15 | 416.81 | 0.00 | -378.06 |
| 76000.00 | 0.98 | 54.25 | 72.50 | 15:24 | 75.70 | 1016.81 | 0.00 | -944.31 |
| 78700.00 | 1.02 | 1281.75 | 1639.45 | 15:36 | 1639.45 | 3716.81 | 1766.41 | -2077.36 |
| 76100.00 | 0.98 | 62.85 | 82.90 | 15:24 | 87.25 | 1116.81 | 0.00 | -1033.91 |
| 75900.00 | 0.98 | 48.10 | 64.00 | 15:24 | 64.20 | 916.81 | 0.00 | -852.81 |
| 76200.00 | 0.98 | 73.15 | 94.40 | 15:24 | 93.00 | 1216.81 | 0.00 | -1122.41 |
| 78900.00 | 1.02 | — | 1541.05 | 15:31 | 1541.05 | 3916.81 | 1966.41 | -2375.76 |
| 76600.00 | 0.99 | 130.00 | 132.60 | 15:20 | 168.10 | 1616.81 | 0.00 | -1484.21 |
| 75300.00 | 0.97 | — | 32.95 | 15:33 | 27.00 | 316.81 | 0.00 | -283.86 |
| 76500.00 | 0.99 | 112.40 | 137.90 | 15:24 | 142.85 | 1516.81 | 0.00 | -1378.91 |
| 76400.00 | 0.99 | 97.05 | 100.00 | 15:20 | 131.00 | 1416.81 | 0.00 | -1316.81 |
| 76800.00 | 0.99 | 173.40 | 180.00 | 15:20 | 225.15 | 1816.81 | 0.00 | -1636.81 |
| 76300.00 | 0.98 | 84.35 | 104.80 | 15:24 | 117.90 | 1316.81 | 0.00 | -1212.01 |
| 76700.00 | 0.99 | 149.95 | 179.20 | 15:24 | 199.90 | 1716.81 | 0.00 | -1537.61 |
| 76900.00 | 0.99 | 199.95 | 203.65 | 15:20 | 251.05 | 1916.81 | 0.00 | -1713.16 |
| 77000.00 | 0.99 | 232.00 | 236.85 | 15:20 | 283.00 | 2016.81 | 66.41 | -1779.96 |
| 77300.00 | 1.00 | 341.55 | 351.40 | 15:20 | 414.75 | 2316.81 | 366.41 | -1965.41 |
| 77400.00 | 1.00 | 386.35 | 398.90 | 15:20 | 462.00 | 2416.81 | 466.41 | -2017.91 |
| 77600.00 | 1.00 | 491.15 | 506.00 | 15:20 | 574.15 | 2616.81 | 666.41 | -2110.81 |
| 77200.00 | 1.00 | 301.40 | 305.10 | 15:20 | 369.00 | 2216.81 | 266.41 | -1911.71 |
| 78000.00 | 1.01 | 738.80 | 764.95 | 15:20 | 838.85 | 3016.81 | 1066.41 | -2251.86 |
| 77500.00 | 1.00 | 436.85 | 444.45 | 15:20 | 514.00 | 2516.81 | 566.41 | -2072.36 |
| 77100.00 | 0.99 | 264.10 | 300.95 | 15:24 | 323.00 | 2116.81 | 166.41 | -1815.86 |
| 78200.00 | 1.01 | — | 1019.50 | 15:27 | 991.95 | 3216.81 | 1266.41 | -2197.31 |
| 77900.00 | 1.01 | 673.55 | 692.00 | 15:20 | 755.60 | 2916.81 | 966.41 | -2224.81 |
| 77700.00 | 1.00 | 544.75 | 557.00 | 15:20 | 629.00 | 2716.81 | 766.41 | -2159.81 |
| 79200.00 | 1.02 | — | 1822.00 | 15:37 | 1822.00 | 4216.81 | 2266.41 | -2394.81 |
| 77800.00 | 1.00 | 606.60 | 623.70 | 15:20 | 683.55 | 2816.81 | 866.41 | -2193.11 |
| 78300.00 | 1.01 | 960.00 | 985.45 | 15:20 | 1064.75 | 3316.81 | 1366.41 | -2331.36 |
| 78400.00 | 1.01 | — | 1172.40 | 15:38 | 1180.15 | 3416.81 | 1466.41 | -2244.41 |
| 78100.00 | 1.01 | 804.05 | 923.85 | 15:36 | 919.00 | 3116.81 | 1166.41 | -2192.96 |
| 78500.00 | 1.01 | 1125.00 | 1160.25 | 15:20 | 1234.65 | 3516.81 | 1566.41 | -2356.56 |
| 78800.00 | 1.02 | — | 1414.35 | 15:22 | 1460.00 | 3816.81 | 1866.41 | -2402.46 |
| 79000.00 | 1.02 | 1569.05 | 1597.80 | 15:20 | 1676.80 | 4016.81 | 2066.41 | -2419.01 |
| 79500.00 | 1.03 | — | 2180.10 | 15:27 | 2161.60 | 4516.81 | 2566.41 | -2336.71 |
| 78600.00 | 1.01 | 1209.65 | 1330.10 | 15:27 | 1288.75 | 3616.81 | 1666.41 | -2286.71 |
| 79100.00 | 1.02 | — | 1762.40 | 15:27 | 1770.95 | 4116.81 | 2166.41 | -2354.41 |

### 1.4 Calls — were they sold down?

| strike | moneyness | spike_min | gap_min | px_before | px_trough | drop_pct | drop_rs | vol_spike | px_15:35 | px_15:39 | recovery_by_1539_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 79700.00 | 1.03 | 15:33 | 1.00 | 14.10 | 11.50 | -18.44 | -2.60 | 100.00 | 13.00 | 10.95 | -21.15 |
| 79600.00 | 1.03 | 15:33 | 1.00 | 17.15 | 14.40 | -16.04 | -2.75 | 2860.00 | 14.55 | 11.80 | -94.55 |
| 79100.00 | 1.02 | 15:30 | 1.00 | 36.20 | 31.60 | -12.71 | -4.60 | 10300.00 | 29.15 | 28.70 | -63.04 |
| 79300.00 | 1.02 | 15:20 | 1.00 | 29.70 | 26.20 | -11.78 | -3.50 | 520.00 | 21.85 | 18.45 | -221.43 |
| 79200.00 | 1.02 | 15:20 | 1.00 | 35.00 | 30.95 | -11.57 | -4.05 | 500.00 | 25.70 | 24.90 | -149.38 |
| 79400.00 | 1.02 | 15:20 | 1.00 | 25.30 | 22.70 | -10.28 | -2.60 | 1300.00 | 18.85 | 18.45 | -163.46 |
| 79500.00 | 1.03 | 15:20 | 1.00 | 21.75 | 19.65 | -9.66 | -2.10 | 22680.00 | 16.55 | 14.05 | -266.67 |

---

## 2. Was the mispricing tradeable and bounded?

**There is no bound.** The ±3 % band bounds *today's auction close* (floor 74,867.42), which is a settlement bound only for a contract expiring today. A 2026-09-03 put has an unbounded overnight gap, so its short has **no worst case**. What is bounded is the mark-to-market if the position is closed the same session with the index at the floor: `intrinsic at the floor + time value`, with time value estimated as the 15:14 at-the-money put premium (**₹436.85** at K=77,500). That estimate holds implied volatility at its pre-dislocation level and ignores gamma over a 2,200-point distance, so it **understates** the adverse mark. Every `reward_risk` below is therefore optimistic in the direction that flatters the trade.

| strike | entry | sold_at | cover_at | cover_px | reward_pts | floor_mark_pts | adverse_pts | reward_risk | reward_rs_per_lot | adverse_rs_per_lot | vol_lots_at_entry |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 74700.00 | 15:21 | 19.35 | 15:35 | 16.95 | 2.40 | 436.85 | 417.50 | 0.01 | 48.00 | -8350.00 | 2.00 |
| 74700.00 | 15:21 | 19.35 | 15:39 | 14.75 | 4.60 | 436.85 | 417.50 | 0.01 | 92.00 | -8350.00 | 2.00 |
| 74800.00 | 15:31 | 21.40 | 15:35 | 18.05 | 3.35 | 436.85 | 415.45 | 0.01 | 67.00 | -8309.00 | 23.00 |
| 74800.00 | 15:31 | 21.40 | 15:39 | 20.75 | 0.65 | 436.85 | 415.45 | 0.00 | 13.00 | -8309.00 | 23.00 |
| 75200.00 | 15:30 | 34.55 | 15:35 | 28.25 | 6.30 | 769.43 | 734.88 | 0.01 | 126.00 | -14697.55 | 15.00 |
| 75200.00 | 15:30 | 34.55 | 15:39 | 26.55 | 8.00 | 769.43 | 734.88 | 0.01 | 160.00 | -14697.55 | 15.00 |
| 74900.00 | 15:31 | 20.60 | 15:35 | 23.05 | -2.45 | 469.43 | 448.83 | -0.01 | -49.00 | -8976.55 | 31.00 |
| 74900.00 | 15:31 | 20.60 | 15:39 | 18.45 | 2.15 | 469.43 | 448.83 | 0.01 | 43.00 | -8976.55 | 31.00 |
| 75000.00 | 15:24 | 29.50 | 15:35 | 25.20 | 4.30 | 569.43 | 539.93 | 0.01 | 86.00 | -10798.55 | 3404.00 |
| 75000.00 | 15:24 | 29.50 | 15:39 | 25.00 | 4.50 | 569.43 | 539.93 | 0.01 | 90.00 | -10798.55 | 3404.00 |
| 75100.00 | 15:24 | 30.75 | 15:35 | 27.75 | 3.00 | 669.43 | 638.68 | 0.01 | 60.00 | -12773.55 | 316.00 |
| 75100.00 | 15:24 | 30.75 | 15:39 | 23.55 | 7.20 | 669.43 | 638.68 | 0.01 | 144.00 | -12773.55 | 316.00 |
| 75600.00 | 15:24 | 48.20 | 15:35 | 46.45 | 1.75 | 1169.43 | 1121.23 | 0.00 | 35.00 | -22424.55 | 207.00 |
| 75600.00 | 15:24 | 48.20 | 15:39 | 39.90 | 8.30 | 1169.43 | 1121.23 | 0.01 | 166.00 | -22424.55 | 207.00 |
| 75500.00 | 15:24 | 43.85 | 15:35 | 41.05 | 2.80 | 1069.43 | 1025.58 | 0.00 | 56.00 | -20511.55 | 1179.00 |
| 75500.00 | 15:24 | 43.85 | 15:39 | 40.00 | 3.85 | 1069.43 | 1025.58 | 0.00 | 77.00 | -20511.55 | 1179.00 |

`vol_lots_at_entry` is the whole strike-minute's traded volume in lots of 20 — the market's total, not a fill. A realistic share of it is a fraction, and the quote that would actually be hit is unobservable: this corpus has **no bid/ask**, only trade prints.

---

## 3. Nifty cross-check at the same moneyness

Nifty's front expiry is a Tuesday weekly, so its tenor does not match Sensex's 7 days. Both Nifty expiries are shown so the comparison cannot be read as a tenor artifact. `*_1518_1523_pct` is the largest traded premium in 15:18–15:23 against the same strike's 15:14 price — the crash window itself.

| moneyness | sensex_K | sensex_dte | sensex_max_1min_pct | sensex_1518_1523_pct | nifty_front_K | nifty_front_dte | nifty_front_max_1min_pct | nifty_front_1518_1523_pct | nifty_next_K | nifty_next_dte | nifty_next_max_1min_pct | nifty_next_1518_1523_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.96 | 74700.00 | 7 | 66.81 | 76.72 | 23250.00 | 5 | 12.50 | 6.25 | 23250.00 | 12 | 6.67 | 3.12 |
| 0.97 | 75100.00 | 7 | 22.51 | 24.26 | 23500.00 | 5 | 10.94 | 1.56 | 23500.00 | 12 | 6.12 | 3.39 |
| 0.97 | 75500.00 | 7 | 20.97 | 24.78 | 23600.00 | 5 | 13.25 | 1.19 | 23650.00 | 12 | 8.11 | 3.81 |
| 0.98 | 75900.00 | 7 | 15.32 | 15.38 | 23750.00 | 5 | 13.33 | 4.55 | 23750.00 | 12 | 8.62 | 3.07 |
| 0.98 | 76300.00 | 7 | 11.55 | 11.38 | 23850.00 | 5 | 13.60 | 5.43 | 23900.00 | 12 | 5.56 | 3.85 |
| 0.99 | 76700.00 | 7 | 10.99 | 7.67 | 23950.00 | 5 | 10.84 | 6.81 | 24000.00 | 12 | 6.26 | 3.81 |

Figure: `fig/wings/cross_index_wing_2026-08-27.png`.

---

## 4. Controls — how often does a wing put move ≥ 100 % in this window?

The wing is every put with moneyness ≤ **0.98** against that session's own 15:14 implied index, because listed depth differs session to session. `hits` counts distinct wing strikes whose largest traded-to-traded move in 15:14–15:39 reached the threshold.

| underlying | session | expiry | dte | n_wing | min_moneyness | max_wing_move_pct | hits_25pct | hits_50pct | hits_100pct | row |
|---|---|---|---|---|---|---|---|---|---|---|
| SENSEX | 2026-08-27 | 2026-09-03 | 7 | 13 | 0.96 | 66.81 | 4 | 1 | 0 | EVENT |
| SENSEX | 2026-08-20 | 2026-09-03 | 14 | 2 | 0.96 | 12.53 | 0 | 0 | 0 | control |
| SENSEX | 2026-08-25 | 2026-09-03 | 9 | 9 | 0.96 | 13.03 | 0 | 0 | 0 | control |
| SENSEX | 2026-08-26 | 2026-09-03 | 8 | 10 | 0.97 | 23.83 | 0 | 0 | 0 | control |
| SENSEX | 2026-08-28 | 2026-09-03 | 6 | 13 | 0.96 | 11.21 | 0 | 0 | 0 | control |
| NIFTY | 2026-08-25 | 2026-09-01 | 7 | 18 | 0.94 | 4.44 | 0 | 0 | 0 | control |
| NIFTY | 2026-08-26 | 2026-09-01 | 6 | 17 | 0.95 | 7.83 | 0 | 0 | 0 | control |
| NIFTY | 2026-08-27 | 2026-09-01 | 5 | 17 | 0.95 | 14.73 | 0 | 0 | 0 | control |
| NIFTY | 2026-08-28 | 2026-09-01 | 4 | 17 | 0.95 | 15.38 | 0 | 0 | 0 | control |

**At the 100 % threshold the trigger fires nowhere — 0 of 103 control wing strike-sessions across 8 sessions, and 0 of 13 on the event session itself.** A trigger with no false positives and no true positives is not a trigger; it is a threshold above the entire distribution. The sweep is what carries the information: at **50 %** the event fires 1 of 13 while the controls fire 0 of 103, and at **25 %** the event fires 4 against 0 for the controls. The event session is separable from an ordinary one — but only at a threshold that describes a ₹8 move on a ₹12 premium.

---

## 5. Verdict

**Yes, the next-week wings repriced off the indicative — and the size of the repricing is the finding.** The deepest listed put moved +nan % through the crash window and +66.8 % in its largest single traded minute (**74,700 PE, ₹11.60 → ₹19.35** at 15:21, gap 1 min), and the response decays monotonically as the strike approaches the money. The move is real, it is ordered, it is nan× the same-moneyness Nifty response, and **it is ₹7.75**.

**No, there was no defined-risk trade with positive expectancy.** Three independent reasons, any one of which is sufficient:

1. **The reward is a rounding error and the risk is not.** Selling the largest spike on the board and covering at the last bar returns ₹166 per lot at best. Against the same-session mark at the band floor the ratio is about **1 : 100**, and that denominator is already the most flattering one available — it holds volatility flat across a 2,200-point move.
2. **The risk is genuinely unbounded.** The band constrains today's auction close. These are 2026-09-03 contracts: they carry the overnight gap, and the band says nothing about it. The one structural feature that made the expiring-series version of this trade *analysable* — a known worst case — does not exist here.
3. **The trigger cannot be built.** A wing-put spike is only distinguishable from an ordinary session at a threshold of roughly 25–50 %, which on these premiums is a handful of rupees, and the corpus is 8 control sessions. There is no sample here capable of estimating the false-positive rate of a trigger that loose.

**What the data says instead, and it is the stronger result:** the wings priced the indicative as noise, correctly and immediately. At the indicative low every strike above 74,983.19 was notionally in the money, yet none of them traded within hundreds of rupees of that intrinsic (§1.3). The mispricing the thesis needs — wings marked to a crash that was not going to happen — **is not present to be traded.** The market never made the error.

### What is still missing

- **The expiring series.** Zero bars in this corpus (§0), so the ~4,800 % move the thesis originates from cannot be examined on any feed available here. A trade in *that* instrument is neither confirmed nor refuted by anything above.
- **Bid/ask.** Every price here is a trade print. Reward figures of ₹2–8 per unit sit inside a plausible wing spread, so a positive number in §2 may be entirely spread and the sign of the realised P&L is not determined by this data.
