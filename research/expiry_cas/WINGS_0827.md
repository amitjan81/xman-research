# The next-expiry wings on 2026-08-27 — did they reprice off the closing-auction indicative?

**Scope.** SENSEX, the **2026-09-03** expiry (7 days out), every listed strike 74,700–79,600, minute by minute 15:14–15:39 IST. Lot 20. Parity anchor 77,200.

## 0. What this data can and cannot settle

**The expiring series is not here.** The ±25 chain tree for this session carries bars for **2026-09-03** and nothing else. The 2026-08-27 expiring series has refdata entries but zero bars — it delisted into settlement. **So the 75,000 PE the press story is about remains untestable.** The 75,000 PE examined below is the *2026-09-03* contract: a different instrument, with a week of life left and an unbounded overnight gap, that happens to share a strike. Nothing here confirms or refutes the ~4,800 % claim.

**The options forward sits 289 points above cash, and that is a finding, not a nuisance.** The cash feed reads **77,181.61** at 15:14; parity at the anchor pair reads **77,470.15**. Carry at 6.5% over 7 days explains only **96** of the gap — the residual would need a rate near 20% — and the parity level is consistent across neighbouring strikes, so it is a real forward premium rather than one stale leg. **The two series therefore do different jobs here:** cash classifies strikes (moneyness, the wing cut, the at-the-money strike whose premium estimates time value), parity supplies movement and is the only series that survives past 15:29. The choice is not cosmetic: struck on cash the wing below is **10 strikes**, struck on parity it would be wider, and the 'at-the-money' strike whose premium sets every bound in §2 would sit 289 points in the money against cash and carry intrinsic rather than pure time value.

**The published indicative path is not in this feed's option rows** (77,182.91 at 15:15 → 74,983.19 between 15:18 and 15:23 → close 76,933.59). The 15:15 reference does appear in the broadcast `spot` column; the **indicative low does not appear anywhere**, which is the value the whole question turns on.

**Every change is between two bars that each printed volume**, and every such row carries `gap_min`. That guarantee covers the **spike leg only**. The checkpoint columns — `px_1514`, `px_15:30/35/39`, `cover_px`, and every §3 column — are last-trade-at-or-before their label with no gap reported, so a checkpoint may repeat an earlier print. Where that matters it is called out beside the table.

---

## 1. Did the next-week wings reprice off the indicative?

Cash index at 15:14: **77,181.61** — the reference every moneyness below is struck on. The wing put paths are in `fig/wings/sensex_2026-08-27_wing_paths.png`; the full strike × minute change grid is `fig/wings/sensex_2026-08-27_put_change_heatmap.png`.

**The forward's own move, which every premium change has to be read against.** This is the quantity the study's conventions say is usable on a non-expiring chain — a change, from one source, with the forward premium differencing out:

| checkpoint | implied_fwd | change_pts | change_pct |
|---|---|---|---|
| 15:23 (indicative low) | 77422.80 | -47.35 | -0.06 |
| 15:30 | 77372.90 | -97.25 | -0.13 |
| 15:35 | 77352.30 | -117.85 | -0.15 |
| 15:39 | 77333.00 | -137.15 | -0.18 |

So while the published indicative fell **2,199.72 points**, the traded forward fell **47** by the end of the crash window — **2 %** of it. Most of the forward's eventual move arrives *after* the indicative recovered, and Nifty's forward moved almost identically over the same span (§3), so it is market-wide drift into the close rather than a response to the auction.

### 1.1 Top 10 put strike-minutes by % change

`crash_1518_1523_pct` is the extreme premium reached while the indicative was at its low, against the price in `crash_base_min`. That base is the last continuous-session print at or before 15:14 wherever one exists. **Where `crash_base_min` reads later than 15:14 the strike had not traded yet**, so the base is itself inside the dislocation and the percentage **understates** the move — which is the case for the deepest strike on the board, the one the verdict quotes.

| strike | moneyness | crash_1518_1523_pct | crash_base_min | spike_min | phase | gap_min | px_before | px_spike | d_pct | d_rs | vol_spike | px_15:30 | px_15:35 | px_15:39 | reversal_15:30_pct | reversal_15:35_pct | reversal_15:39_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 74700.00 | 0.97 | 76.72 | 15:20 | 15:21 | crash | 1.00 | 11.60 | 19.35 | 66.81 | 7.75 | 40.00 | 17.50 | 16.95 | 14.75 | 23.87 | 30.97 | 59.35 |
| 74800.00 | 0.97 | 44.89 | 15:17 | 15:31 | post_auction | 1.00 | 14.80 | 21.40 | 44.59 | 6.60 | 460.00 | 14.80 | 18.05 | 20.75 | — | 50.76 | 9.85 |
| 75200.00 | 0.97 | 29.59 | 15:14 | 15:30 | post_auction | 1.00 | 25.70 | 34.55 | 34.44 | 8.85 | 300.00 | 34.55 | 28.25 | 26.55 | — | 71.19 | 90.40 |
| 74900.00 | 0.97 | 45.95 | 15:17 | 15:31 | post_auction | 1.00 | 16.35 | 20.60 | 25.99 | 4.25 | 620.00 | 16.35 | 23.05 | 18.45 | — | -57.65 | 50.59 |
| 75000.00 | 0.97 | 32.04 | 15:14 | 15:24 | pre | 1.00 | 23.90 | 29.50 | 23.43 | 5.60 | 68080.00 | 21.65 | 25.20 | 25.00 | 140.18 | 76.79 | 80.36 |
| 75100.00 | 0.97 | 24.26 | 15:14 | 15:24 | pre | 1.00 | 25.10 | 30.75 | 22.51 | 5.65 | 6320.00 | 23.45 | 27.75 | 23.55 | 129.20 | 53.10 | 127.43 |
| 75600.00 | 0.98 | 22.03 | 15:14 | 15:24 | pre | 1.00 | 39.60 | 48.20 | 21.72 | 8.60 | 4140.00 | 42.80 | 46.45 | 39.90 | 62.79 | 20.35 | 96.51 |
| 75500.00 | 0.98 | 24.78 | 15:14 | 15:24 | pre | 1.00 | 36.25 | 43.85 | 20.97 | 7.60 | 23580.00 | 34.35 | 41.05 | 40.00 | 125.00 | 36.84 | 50.66 |
| 75700.00 | 0.98 | 19.86 | 15:14 | 15:24 | pre | 1.00 | 44.35 | 53.45 | 20.52 | 9.10 | 4740.00 | 47.95 | 53.00 | 53.85 | 60.44 | 4.95 | -4.40 |
| 75800.00 | 0.98 | 17.34 | 15:14 | 15:24 | pre | 1.00 | 49.40 | 59.45 | 20.34 | 10.05 | 3940.00 | 53.15 | 59.25 | 55.50 | 62.69 | 1.99 | 39.30 |

### 1.2 Top 10 put strike-minutes by ₹ change

A percentage on an ₹12 premium is a few ticks, so the same scan is ranked by money. **Note `is_wing`:** the largest rupee moves are not wing repricing at all. They are deep in-the-money puts — moneyness above 1 — whose premium tracks the underlying nearly one-for-one, printing one or two lots at a time across multi-minute gaps. That is delta on an illiquid contract, and it is the opposite end of the board from the question.

| strike | moneyness | is_wing | spike_min | gap_min | px_before | px_spike | d_pct | d_rs | vol_spike | reversal_15:39_pct |
|---|---|---|---|---|---|---|---|---|---|---|
| 78700.00 | 1.02 | False | 15:36 | 9.00 | 1407.00 | 1639.45 | 16.52 | 232.45 | 20.00 | 0.00 |
| 78900.00 | 1.02 | False | 15:31 | 4.00 | 1350.00 | 1541.05 | 14.15 | 191.05 | 20.00 | 0.00 |
| 79200.00 | 1.03 | False | 15:37 | 2.00 | 1704.55 | 1822.00 | 6.89 | 117.45 | 20.00 | 0.00 |
| 79500.00 | 1.03 | False | 15:27 | 5.00 | 2085.00 | 2180.10 | 4.56 | 95.10 | 40.00 | 19.45 |
| 78200.00 | 1.01 | False | 15:27 | 1.00 | 948.00 | 1019.50 | 7.54 | 71.50 | 40.00 | 38.53 |
| 79000.00 | 1.02 | False | 15:20 | 2.00 | 1526.80 | 1597.80 | 4.65 | 71.00 | 80.00 | -111.27 |
| 78800.00 | 1.02 | False | 15:22 | 3.00 | 1347.00 | 1414.35 | 5.00 | 67.35 | 20.00 | -67.78 |
| 78400.00 | 1.02 | False | 15:38 | 7.00 | 1107.50 | 1172.40 | 5.86 | 64.90 | 20.00 | -11.94 |
| 78500.00 | 1.02 | False | 15:20 | 1.00 | 1099.35 | 1160.25 | 5.54 | 60.90 | 40.00 | -122.17 |
| 78300.00 | 1.01 | False | 15:20 | 1.00 | 925.30 | 985.45 | 6.50 | 60.15 | 500.00 | -131.84 |

### 1.3 The wings never came close to the indicative's own intrinsic

`intrinsic_at_indicative_low` = max(K − 74,983.19, 0); `intrinsic_at_close` = max(K − 76,933.59, 0). For a 7-day option neither is a settlement value — they are the reference points the question asks for.

Had the index really been at 74,983.19, every strike above it would have been in the money and `spike_over_intrinsic_low` could not be negative. It is negative from 75,300 upward (75,100 is −86, 75,200 is −182, and it widens from there). **This is worth stating precisely, because on its own it is not independent evidence:** that the wings did not price the indicative as a level is the same fact as the forward not moving to it, already visible in the table above and established in `CROSS_INDEX.md`. It is that fact in rupee units. Note also that the column compares `px_spike`, a maximum over the whole window, against intrinsic at the 15:18–15:23 low, so it mixes times.

| strike | moneyness | px_1514 | px_spike | spike_min | phase | px_15:39 | intrinsic_at_indicative_low | intrinsic_at_close | spike_over_intrinsic_low |
|---|---|---|---|---|---|---|---|---|---|
| 74700.00 | 0.97 | — | 19.35 | 15:21 | crash | 14.75 | 0.00 | 0.00 | 19.35 |
| 74800.00 | 0.97 | — | 21.40 | 15:31 | post_auction | 20.75 | 0.00 | 0.00 | 21.40 |
| 75200.00 | 0.97 | 20.95 | 34.55 | 15:30 | post_auction | 26.55 | 216.81 | 0.00 | -182.26 |
| 74900.00 | 0.97 | — | 20.60 | 15:31 | post_auction | 18.45 | 0.00 | 0.00 | 20.60 |
| 75000.00 | 0.97 | 18.10 | 29.50 | 15:24 | pre | 25.00 | 16.81 | 0.00 | 12.69 |
| 75100.00 | 0.97 | 20.20 | 30.75 | 15:24 | pre | 23.55 | 116.81 | 0.00 | -86.06 |
| 75600.00 | 0.98 | 32.45 | 48.20 | 15:24 | pre | 39.90 | 616.81 | 0.00 | -568.61 |
| 75500.00 | 0.98 | 29.05 | 43.85 | 15:24 | pre | 40.00 | 516.81 | 0.00 | -472.96 |
| 75700.00 | 0.98 | 37.00 | 53.45 | 15:24 | pre | 53.85 | 716.81 | 0.00 | -663.36 |
| 75800.00 | 0.98 | 42.10 | 59.45 | 15:24 | pre | 55.50 | 816.81 | 0.00 | -757.36 |
| 75400.00 | 0.98 | 26.10 | 38.75 | 15:24 | pre | 32.15 | 416.81 | 0.00 | -378.06 |
| 76000.00 | 0.98 | 54.25 | 72.50 | 15:24 | pre | 75.70 | 1016.81 | 0.00 | -944.31 |
| 78700.00 | 1.02 | 1281.75 | 1639.45 | 15:36 | post_auction | 1639.45 | 3716.81 | 1766.41 | -2077.36 |
| 76100.00 | 0.99 | 62.85 | 82.90 | 15:24 | pre | 87.25 | 1116.81 | 0.00 | -1033.91 |
| 75900.00 | 0.98 | 48.10 | 64.00 | 15:24 | pre | 64.20 | 916.81 | 0.00 | -852.81 |
| 76200.00 | 0.99 | 73.15 | 94.40 | 15:24 | pre | 93.00 | 1216.81 | 0.00 | -1122.41 |
| 78900.00 | 1.02 | — | 1541.05 | 15:31 | post_auction | 1541.05 | 3916.81 | 1966.41 | -2375.76 |
| 76600.00 | 0.99 | 130.00 | 132.60 | 15:20 | crash | 168.10 | 1616.81 | 0.00 | -1484.21 |
| 75300.00 | 0.98 | — | 32.95 | 15:33 | post_auction | 27.00 | 316.81 | 0.00 | -283.86 |
| 76500.00 | 0.99 | 112.40 | 137.90 | 15:24 | pre | 142.85 | 1516.81 | 0.00 | -1378.91 |
| 76400.00 | 0.99 | 97.05 | 100.00 | 15:20 | crash | 131.00 | 1416.81 | 0.00 | -1316.81 |
| 76800.00 | 0.99 | 173.40 | 180.00 | 15:20 | crash | 225.15 | 1816.81 | 0.00 | -1636.81 |
| 76300.00 | 0.99 | 84.35 | 104.80 | 15:24 | pre | 117.90 | 1316.81 | 0.00 | -1212.01 |
| 76700.00 | 0.99 | 149.95 | 179.20 | 15:24 | pre | 199.90 | 1716.81 | 0.00 | -1537.61 |
| 76900.00 | 1.00 | 199.95 | 203.65 | 15:20 | crash | 251.05 | 1916.81 | 0.00 | -1713.16 |
| 77000.00 | 1.00 | 232.00 | 236.85 | 15:20 | crash | 283.00 | 2016.81 | 66.41 | -1779.96 |
| 77300.00 | 1.00 | 341.55 | 351.40 | 15:20 | crash | 414.75 | 2316.81 | 366.41 | -1965.41 |
| 77400.00 | 1.00 | 386.35 | 398.90 | 15:20 | crash | 462.00 | 2416.81 | 466.41 | -2017.91 |
| 77600.00 | 1.00 | 491.15 | 506.00 | 15:20 | crash | 574.15 | 2616.81 | 666.41 | -2110.81 |
| 77200.00 | 1.00 | 301.40 | 305.10 | 15:20 | crash | 369.00 | 2216.81 | 266.41 | -1911.71 |
| 78000.00 | 1.01 | 738.80 | 764.95 | 15:20 | crash | 838.85 | 3016.81 | 1066.41 | -2251.86 |
| 77500.00 | 1.00 | 436.85 | 444.45 | 15:20 | crash | 514.00 | 2516.81 | 566.41 | -2072.36 |
| 77100.00 | 1.00 | 264.10 | 300.95 | 15:24 | pre | 323.00 | 2116.81 | 166.41 | -1815.86 |
| 78200.00 | 1.01 | — | 1019.50 | 15:27 | pre | 991.95 | 3216.81 | 1266.41 | -2197.31 |
| 77900.00 | 1.01 | 673.55 | 692.00 | 15:20 | crash | 755.60 | 2916.81 | 966.41 | -2224.81 |
| 77700.00 | 1.01 | 544.75 | 557.00 | 15:20 | crash | 629.00 | 2716.81 | 766.41 | -2159.81 |
| 79200.00 | 1.03 | — | 1822.00 | 15:37 | post_auction | 1822.00 | 4216.81 | 2266.41 | -2394.81 |
| 77800.00 | 1.01 | 606.60 | 623.70 | 15:20 | crash | 683.55 | 2816.81 | 866.41 | -2193.11 |
| 78300.00 | 1.01 | 960.00 | 985.45 | 15:20 | crash | 1064.75 | 3316.81 | 1366.41 | -2331.36 |
| 78400.00 | 1.02 | — | 1172.40 | 15:38 | post_auction | 1180.15 | 3416.81 | 1466.41 | -2244.41 |
| 78100.00 | 1.01 | 804.05 | 923.85 | 15:36 | post_auction | 919.00 | 3116.81 | 1166.41 | -2192.96 |
| 78500.00 | 1.02 | 1125.00 | 1160.25 | 15:20 | crash | 1234.65 | 3516.81 | 1566.41 | -2356.56 |
| 78800.00 | 1.02 | — | 1414.35 | 15:22 | crash | 1460.00 | 3816.81 | 1866.41 | -2402.46 |
| 79000.00 | 1.02 | 1569.05 | 1597.80 | 15:20 | crash | 1676.80 | 4016.81 | 2066.41 | -2419.01 |
| 79500.00 | 1.03 | — | 2180.10 | 15:27 | pre | 2161.60 | 4516.81 | 2566.41 | -2336.71 |
| 78600.00 | 1.02 | 1209.65 | 1330.10 | 15:27 | pre | 1288.75 | 3616.81 | 1666.41 | -2286.71 |
| 79100.00 | 1.02 | — | 1762.40 | 15:27 | pre | 1770.95 | 4116.81 | 2166.41 | -2354.41 |

#### 1.3.1 What the ±25 chain adds: how much of the wing move was delta?

This is the part the ±10 ladder could not answer. For each wing strike, an empirical delta is fitted from this chain — the slope of its traded premium change against the simultaneous forward change, over every minute both printed — and the crash-window move is split into the part that slope explains and the residual:

| strike | moneyness | base_min | n | empirical_delta | fit_ok | fwd_move_pts | move_rs | delta_part_rs | residual_rs |
|---|---|---|---|---|---|---|---|---|---|
| 74700.00 | 0.97 | 15:20 | 17 | 0.06 | False | -47.35 | 8.90 | -2.90 | 11.80 |
| 74800.00 | 0.97 | 15:17 | 21 | -0.05 | True | -47.35 | 6.15 | 2.33 | 3.82 |
| 75200.00 | 0.97 | 15:14 | 25 | -0.02 | True | -47.35 | 6.20 | 1.14 | 5.06 |
| 74900.00 | 0.97 | 15:17 | 22 | -0.02 | True | -47.35 | 7.10 | 1.14 | 5.96 |
| 75000.00 | 0.97 | 15:14 | 25 | -0.03 | True | -47.35 | 5.80 | 1.51 | 4.29 |
| 75100.00 | 0.97 | 15:14 | 25 | -0.03 | True | -47.35 | 4.90 | 1.38 | 3.52 |
| 75600.00 | 0.98 | 15:14 | 25 | -0.06 | True | -47.35 | 7.15 | 2.81 | 4.34 |
| 75500.00 | 0.98 | 15:14 | 25 | -0.05 | True | -47.35 | 7.20 | 2.36 | 4.84 |

**The residual is most of the move at every wing strike.** The forward fell only 47 points through the crash window, and at these deltas that accounts for roughly a rupee or two; the rest is a volatility and skew bid. So the wings did reprice — as *insurance getting more expensive*, not as a directional mark to 74,983. `n` is the number of paired minutes behind each slope; a slope fitted on a handful of prints is loose, and the fit absorbs some vega into the delta term, which if anything makes the residual a conservative estimate.

**Read `fit_ok` before reading any row.** A put's delta is negative by construction, so a positive fitted slope means the regression failed on that strike — which is exactly what happens at the headline 74,700, the thinnest contract on the board and the one with no pre-crash print. Its split is not usable. Every strike whose fit does hold lands in the same place: delta explains ₹1–3 of a ₹5–7 move and the residual is the majority.

### 1.4 Calls — were they sold down?

| strike | moneyness | spike_min | gap_min | px_before | px_trough | drop_pct | drop_rs | vol_spike | px_15:35 | px_15:39 | recovery_by_1539_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 79700.00 | 1.03 | 15:33 | 1.00 | 14.10 | 11.50 | -18.44 | -2.60 | 100.00 | 13.00 | 10.95 | -21.15 |
| 79600.00 | 1.03 | 15:33 | 1.00 | 17.15 | 14.40 | -16.04 | -2.75 | 2860.00 | 14.55 | 11.80 | -94.55 |
| 79100.00 | 1.02 | 15:30 | 1.00 | 36.20 | 31.60 | -12.71 | -4.60 | 10300.00 | 29.15 | 28.70 | -63.04 |
| 78900.00 | 1.02 | 15:20 | 1.00 | 56.00 | 49.30 | -11.96 | -6.70 | 1700.00 | 41.00 | 39.80 | -141.79 |
| 79300.00 | 1.03 | 15:20 | 1.00 | 29.70 | 26.20 | -11.78 | -3.50 | 520.00 | 21.85 | 18.45 | -221.43 |
| 79200.00 | 1.03 | 15:20 | 1.00 | 35.00 | 30.95 | -11.57 | -4.05 | 500.00 | 25.70 | 24.90 | -149.38 |
| 79000.00 | 1.02 | 15:20 | 1.00 | 47.10 | 41.70 | -11.46 | -5.40 | 28180.00 | 34.40 | 29.25 | -230.56 |
| 78800.00 | 1.02 | 15:20 | 1.00 | 64.40 | 57.65 | -10.48 | -6.75 | 1800.00 | 48.00 | 43.30 | -212.59 |

---

## 2. Was the mispricing tradeable and bounded?

**There is no bound.** The ±3 % band bounds *today's auction close* (floor 74,867.42), which is a settlement bound only for a contract expiring today. A 2026-09-03 put has an unbounded overnight gap, so its short has **no worst case**. What is bounded is the mark-to-market if the position is closed the same session with the index at the floor: `intrinsic at the floor + time value`, with time value estimated as the 15:14 at-the-money put premium (**₹301.40** at K=77,200). **The direction of that estimate's error is indeterminate, and it does not matter.** Holding volatility at its pre-dislocation level understates the mark; applying an at-the-money time value unchanged to strikes that would be hundreds of points in the money at the floor overstates it. Intrinsic at the floor is exact — what is estimated is only the time value's dependence on volatility and moneyness. The ratios below are two orders of magnitude from break-even, so no plausible correction reaches them.

| strike | entry | sold_at | cover_at | cover_px | reward_pts | floor_mark_pts | adverse_pts | reward_risk | reward_rs_per_lot | adverse_rs_per_lot | vol_lots_at_entry |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 74700.00 | 15:21 | 19.35 | 15:35 | 16.95 | 2.40 | 301.40 | 282.05 | 0.01 | 48.00 | -5641.00 | 2.00 |
| 74700.00 | 15:21 | 19.35 | 15:39 | 14.75 | 4.60 | 301.40 | 282.05 | 0.02 | 92.00 | -5641.00 | 2.00 |
| 74800.00 | 15:31 | 21.40 | 15:35 | 18.05 | 3.35 | 301.40 | 280.00 | 0.01 | 67.00 | -5600.00 | 23.00 |
| 74800.00 | 15:31 | 21.40 | 15:39 | 20.75 | 0.65 | 301.40 | 280.00 | 0.00 | 13.00 | -5600.00 | 23.00 |
| 75200.00 | 15:30 | 34.55 | 15:35 | 28.25 | 6.30 | 633.98 | 599.43 | 0.01 | 126.00 | -11988.55 | 15.00 |
| 75200.00 | 15:30 | 34.55 | 15:39 | 26.55 | 8.00 | 633.98 | 599.43 | 0.01 | 160.00 | -11988.55 | 15.00 |
| 74900.00 | 15:31 | 20.60 | 15:35 | 23.05 | -2.45 | 333.98 | 313.38 | -0.01 | -49.00 | -6267.55 | 31.00 |
| 74900.00 | 15:31 | 20.60 | 15:39 | 18.45 | 2.15 | 333.98 | 313.38 | 0.01 | 43.00 | -6267.55 | 31.00 |
| 75000.00 | 15:24 | 29.50 | 15:35 | 25.20 | 4.30 | 433.98 | 404.48 | 0.01 | 86.00 | -8089.55 | 3404.00 |
| 75000.00 | 15:24 | 29.50 | 15:39 | 25.00 | 4.50 | 433.98 | 404.48 | 0.01 | 90.00 | -8089.55 | 3404.00 |
| 75100.00 | 15:24 | 30.75 | 15:35 | 27.75 | 3.00 | 533.98 | 503.23 | 0.01 | 60.00 | -10064.55 | 316.00 |
| 75100.00 | 15:24 | 30.75 | 15:39 | 23.55 | 7.20 | 533.98 | 503.23 | 0.01 | 144.00 | -10064.55 | 316.00 |
| 75600.00 | 15:24 | 48.20 | 15:35 | 46.45 | 1.75 | 1033.98 | 985.78 | 0.00 | 35.00 | -19715.55 | 207.00 |
| 75600.00 | 15:24 | 48.20 | 15:39 | 39.90 | 8.30 | 1033.98 | 985.78 | 0.01 | 166.00 | -19715.55 | 207.00 |
| 75500.00 | 15:24 | 43.85 | 15:35 | 41.05 | 2.80 | 933.98 | 890.13 | 0.00 | 56.00 | -17802.55 | 1179.00 |
| 75500.00 | 15:24 | 43.85 | 15:39 | 40.00 | 3.85 | 933.98 | 890.13 | 0.00 | 77.00 | -17802.55 | 1179.00 |

`vol_lots_at_entry` is the whole strike-minute's traded volume in lots of 20 — the market's total, not a fill. A realistic share of it is a fraction, and the quote that would actually be hit is unobservable: this corpus has **no bid/ask**, only trade prints.

---

## 3. Nifty cross-check at the same moneyness

**Nifty is a no-event control, not a second response.** NSE runs no closing auction, so there was no indicative to reprice off; the comparison measures what an ordinary session's wings did over the same minutes. Nifty's front expiry is a Tuesday weekly, so its tenor does not match Sensex's 7 days — both Nifty expiries are shown so the result cannot be read as a tenor artifact.

`*_1518_1523_pct` is the largest traded premium in 15:18–15:23 against the price at `*_base_min`, which is the same `crash_base` rule §1.1 uses. **Read the rupee columns first:** at these moneynesses a Nifty put costs ₹1.60, where one tick is a double-digit percentage, so a ratio of two such percentages is a ratio of ticks. `*_max_1min_pct` is a maximum over traded-to-traded changes whose gaps are not shown, so the `1min` in its name is not guaranteed.

| moneyness | sensex_K | sensex_dte | sensex_max_1min_pct | sensex_base_min | sensex_base_px | sensex_crash_px | sensex_1518_1523_pct | nifty_front_K | nifty_front_dte | nifty_front_max_1min_pct | nifty_front_base_min | nifty_front_base_px | nifty_front_crash_px | nifty_front_1518_1523_pct | nifty_next_K | nifty_next_dte | nifty_next_max_1min_pct | nifty_next_base_min | nifty_next_base_px | nifty_next_crash_px | nifty_next_1518_1523_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.96 | 74700.00 | 7 | 66.81 | 15:20 | 11.60 | 20.50 | 76.72 | 23150.00 | 5 | 10.71 | 15:14 | 1.40 | 1.45 | 3.57 | 23150.00 | 12 | 6.47 | 15:14 | 6.75 | 7.05 | 4.44 |
| 0.97 | 74900.00 | 7 | 25.99 | 15:17 | 15.45 | 22.55 | 45.95 | 23400.00 | 5 | 14.58 | 15:14 | 2.45 | 2.55 | 4.08 | 23400.00 | 12 | 6.87 | 15:14 | 11.25 | 11.65 | 3.56 |
| 0.97 | 75300.00 | 7 | 13.62 | 15:25 | 32.75 | — | — | 23550.00 | 5 | 11.43 | 15:14 | 3.60 | 3.65 | 1.39 | 23550.00 | 12 | 10.39 | 15:14 | 16.60 | 17.25 | 3.92 |
| 0.98 | 75600.00 | 7 | 21.72 | 15:14 | 32.45 | 39.60 | 22.03 | 23650.00 | 5 | 12.75 | 15:14 | 4.95 | 5.10 | 3.03 | 23650.00 | 12 | 8.11 | 15:14 | 22.30 | 23.15 | 3.81 |
| 0.98 | 76000.00 | 7 | 16.56 | 15:14 | 54.25 | 62.20 | 14.65 | 23750.00 | 5 | 13.33 | 15:14 | 7.70 | 8.05 | 4.55 | 23750.00 | 12 | 8.62 | 15:14 | 30.95 | 31.90 | 3.07 |
| 0.99 | 76400.00 | 7 | 12.49 | 15:14 | 97.05 | 106.30 | 9.53 | 23900.00 | 5 | 11.28 | 15:14 | 17.10 | 18.15 | 6.14 | 23900.00 | 12 | 5.56 | 15:14 | 52.00 | 54.00 | 3.85 |

Figure: `fig/wings/cross_index_wing_2026-08-27.png`.

---

## 4. Controls — how often does a wing put move ≥ 100 % in this window?

The wing is every put with moneyness ≤ **0.98** against that session's own 15:14 **cash** index, because listed depth differs session to session. `hits_*` counts distinct wing strikes whose largest traded-to-traded move in 15:14–15:39 reached the threshold; `crash_hits_*` and `postauction_hits_*` split that count by **when** the move landed. **The split is the point.** Only a move inside 15:18–15:23 is a response to the indicative. A move at 15:30–15:31 lands after matching has begun and the close is about to be published — a different event with a different cause, and one an ordinary session can produce too.

| underlying | session | expiry | dte | n_wing | min_moneyness | max_wing_move_pct | hits_25pct | crash_hits_25pct | postauction_hits_25pct | hits_50pct | crash_hits_50pct | postauction_hits_50pct | hits_100pct | crash_hits_100pct | postauction_hits_100pct | row |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SENSEX | 2026-08-27 | 2026-09-03 | 7 | 10 | 0.97 | 66.81 | 4 | 1 | 3 | 1 | 1 | 0 | 0 | 0 | 0 | EVENT |
| SENSEX | 2026-08-20 | 2026-09-03 | 14 | 2 | 0.97 | 12.53 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | control |
| SENSEX | 2026-08-25 | 2026-09-03 | 9 | 5 | 0.97 | 13.03 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | control |
| SENSEX | 2026-08-26 | 2026-09-03 | 8 | 6 | 0.97 | 23.83 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | control |
| SENSEX | 2026-08-28 | 2026-09-03 | 6 | 10 | 0.97 | 11.21 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | control |
| NIFTY | 2026-08-25 | 2026-09-01 | 7 | 16 | 0.95 | 4.44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | control |
| NIFTY | 2026-08-26 | 2026-09-01 | 6 | 15 | 0.95 | 7.50 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | control |
| NIFTY | 2026-08-27 | 2026-09-01 | 5 | 16 | 0.95 | 14.58 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | control |
| NIFTY | 2026-08-28 | 2026-09-01 | 4 | 16 | 0.95 | 15.38 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | control |

**At the 100 % threshold the trigger fires nowhere — 0 across 8 control sessions, and 0 on the event session itself.** A trigger with neither false positives nor true positives is not a trigger; it is a threshold above the entire distribution.

**Lowering it does not rescue the trigger, once the hits are read by phase.** At 25 % the event fires 4 against 0 for the controls — but only **1 of those 4 landed in the crash window**; 3 landed at 15:30–15:31, after matching began and as the close was being published. Those are not responses to the indicative. The genuine crash-window separation on the event session is **1 strike**, against a control maximum wing move of 23.8 %.

**And 86 is not a denominator.** Strikes within a session move together, so the independent unit is the session and there are 8 of them. The per-strike counts are reported for transparency, not as a rate. One control also carries a caveat: the 2026-08-20 session's tree holds only the 3 Sep expiry, so it is a 14-day chain with 2 wing strikes rather than a tenor-matched control.

---

## 5. Verdict

**One claim, not two.** The wings repriced — as *insurance getting dearer*, not as a mark to the indicative. Those are the same finding, and the earlier framing that asserted both a repricing and a market that 'never made an error' was asserting a contradiction. What the chain shows is narrower and consistent:

- **What moved.** The wing bid rose broadly with depth (not monotonically — 75,200 outruns 74,900 and 75,000, and 75,600 outruns 75,500). The largest wing mover is **74,700 PE**: ₹11.60 → **₹19.35** at **15:21** (+66.8 %, ₹+7.75, gap 1 min, 2 lots traded that minute). It had no print before 15:20, so its base is itself inside the dislocation and it is a thin contract: the level that actually held afterwards was about ₹20.
- **Why it moved.** Not delta. The forward fell only 47 points through the crash window (2 % of the indicative's move), which at these deltas explains a rupee or two of an ₹5–9 move (§1.3.1). The rest is a volatility and skew bid — the wings got more expensive without the forward going anywhere near 74,983.
- **When it moved.** Only 1 wing strike cleared 25 % inside 15:18–15:23; 3 of the session's hits landed at 15:30–15:31, around the close publication, which an ordinary session also produces (§4).

**The Nifty comparison, made on strikes that can carry it.** The headline 74,700 is the wrong numerator for a cross-index claim: it has no pre-crash print (its base is 15:20, inside the dislocation), 2 lots traded in its spike minute, and its delta fit fails (§1.3.1). Both Nifty legs base cleanly at 15:14, so the like-for-like comparison uses the 6 Sensex wing strikes that also base at or before 15:14: their median crash-window move is **+25.4 %** (₹6.50 on premiums of ₹18–32), measured inside 15:18-15:23 rather than over the whole window.

Against that: Nifty's **front** put at the same moneyness moved ₹1.40 → ₹1.45 — **one tick on a ₹1.40 option**, so the nominal 21× is a ratio of ticks and carries nothing. Nifty's **12-day** put is the usable comparator at ₹6.75: it moved ₹0.30 (**+4.4 %**). So Sensex's wings repriced roughly **five times harder in percentage terms** and an order of magnitude more in rupees — a real asymmetry, and one that still lives inside a few rupees per contract.

**No, there was no defined-risk trade with positive expectancy.** Three independent reasons, any one of which is sufficient:

1. **The reward is a rounding error and the risk is not.** Fading the headline spike — sell 74,700 PE at ₹19.35 at 15:21, cover at ₹14.75 at 15:39 — returns **₹92 per lot** against an adverse same-session mark of **₹5,641**: **1 : 61**. The best of the eight wing fades is 75,600 PE at ₹166 per lot (1 : 119). **Capacity cuts both ways and neither way helps.** The headline strike is far too thin to trade — 2 lots printed in its entry minute, so the spike is a couple of prints rather than a market. The strikes that do carry size (3,404 lots at 75,000 in its entry minute) show the same arithmetic at a worse ratio.
2. **The risk is genuinely unbounded.** The band constrains today's auction close. These are 2026-09-03 contracts: they carry the overnight gap, and the band says nothing about it. The one structural feature that made the expiring-series version of this trade *analysable* — a known worst case — does not exist here.
3. **The trigger cannot be built.** A wing-put spike is only distinguishable from an ordinary session at a threshold of roughly 25–50 %, which on these premiums is a handful of rupees, and the corpus is 8 control sessions. There is no sample here capable of estimating the false-positive rate of a trigger that loose.

**The reason there is nothing to fade:** the thesis needs wings *marked to a crash that was not going to happen*, and that is not what happened. The forward never went near 74,983.19 (§1), the wings never traded at the intrinsic that level implies (§1.3), and what did move was a few rupees of volatility premium — which is the correct response to a genuine spike in uncertainty about where the close would print, and which was itself largely justified: the eventual close came in 249 points below the 15:15 reference. There is a repricing here. There is no mispricing.

### What is still missing

- **The expiring series.** Zero bars in this corpus (§0), so the ~4,800 % move the thesis originates from cannot be examined on any feed available here. A trade in *that* instrument is neither confirmed nor refuted by anything above.
- **Bid/ask.** Every price here is a trade print. Reward figures of ₹2–8 per unit sit inside a plausible wing spread, so a positive number in §2 may be entirely spread and the sign of the realised P&L is not determined by this data.
