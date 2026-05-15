# MomentumLearning Research Summary
---

## Table of Contents

1. [Market Data Management & Infrastructure](#1-market-data-management--infrastructure)
2. [Technical Indicators & Signal Generation](#2-technical-indicators--signal-generation)
3. [The Momentum Strategy — Core Idea](#3-the-momentum-strategy--core-idea)
4. [EMA Scoring System & Portfolio Construction](#4-ema-scoring-system--portfolio-construction)
5. [FIP Value — Frequency-Imbalance Persistence Scoring](#5-fip-value--frequency-imbalance-persistence-scoring)
6. [Regime-Aware Relative Strength Classification](#6-regime-aware-relative-strength-classification)
7. [Hurst Exponent — Trending vs Mean-Reverting Markets](#7-hurst-exponent--trending-vs-mean-reverting-markets)
8. [ARIMA Time-Series Forecasting](#8-arima-time-series-forecasting)
9. [GARCH & Volatility Modelling](#9-garch--volatility-modelling)
10. [Hidden Markov Models (HMM) for Regime Detection](#10-hidden-markov-models-hmm-for-regime-detection)
11. [LSTM Deep Learning for Price Prediction](#11-lstm-deep-learning-for-price-prediction)
12. [Kalman Filter & OLS Trend Analysis](#12-kalman-filter--ols-trend-analysis)
13. [Backtesting Framework & Performance Metrics](#13-backtesting-framework--performance-metrics)
14. [Market Universe Construction](#14-market-universe-construction)
15. [Common Gotchas in Quantitative Research](#15-common-gotchas-in-quantitative-research)

---

## 1. Market Data Management & Infrastructure

**Files:** `Utils.py`, `DataFrameWindowFilter.py`

### 1.1 Basic Introduction

Before you can analyse anything, you need data — clean, reliable, and properly time-indexed market data. In quantitative finance, market data refers to the time-series of price and volume information for financial instruments (stocks, indices, forex pairs, etc.). Each data point is called a **candle** or **bar** and contains five fields:

- **Open** — price at which the period started
- **High** — highest price reached during the period
- **Low** — lowest price reached during the period
- **Close** — price at which the period ended
- **Volume** — number of shares/contracts traded

The **granularity** (or interval) determines how long each candle represents: 1 minute, 5 minutes, 1 day, etc.

### 1.2 What Is the Use of This

Data management infrastructure is the foundation of every single strategy. Without clean, correctly time-indexed, and granularity-aware data:
- Your indicators will be calculated on wrong windows
- Your backtests will be contaminated with survivorship bias or look-ahead bias
- Your live system will fail when data is missing on weekends or holidays

### 1.3 What Has Been Tried

**`Utils.py`** contains a comprehensive library of data utilities. Key capabilities include:

**Downloading from Yahoo Finance** with granularity limits correctly enforced:
```python
# From Utils.py — enforces the 60-day lookback limit for intraday granularities
if granularity == "2m" or granularity == "5m" ...:
    max_lookback_date = calculate_dates(get_current_date(), 59, 59)['past_date']
    if is_date_in_range(start_date, max_lookback_date, get_current_date()) == False:
        print("We can only get ...")
        return
```

This is critical: Yahoo Finance only allows intraday (1m, 2m, 5m, etc.) data for the last 60 days. The code enforces this programmatically instead of silently returning bad data.

**Day-by-day download loop** (`Utils.py`, functions `download_Mkt_Data_For_Symbols_With_Start_And_EndDate_With_Granularity_And_SaveFilesToDirectory` and `download_market_data`):
- Downloads one calendar day at a time per symbol
- Skips weekends using `is_weekend()`
- Skips already-downloaded files (idempotent — safe to re-run)
- Saves each day as a separate CSV file named `SYMBOL.NS_YYYY-MM-DD.csv`

**Reading and stitching data** (`readCsv_from_startdate_enddate`):
- Checks for a pre-stitched cache file first (avoids redundant re-reading)
- Discovers existing day-files by regex pattern matching
- Concatenates them in order, deduplicated
- Saves the combined file for future reuse

**Filtering by date range and time-of-day**:
```python
# Utils.py — range filter
def filter_panda_df_in_range_constraint(dataframe, columnName, rangeStart, rangeEnd):
    return dataframe[(dataframe[columnName] >= rangeStart) & (dataframe[columnName] <= rangeEnd)].copy()
```

**Weekly resampling** (`filter_dataframe_by_days`):
- Condenses daily data into "N-day bars" (e.g., every 6 trading days ≈ weekly)
- Aggregates: High = rolling max, Low = rolling min, Open = shifted, Volume = rolling sum
- This is the backbone of the weekly momentum backtest

**Calendar-based window filtering** (`DataFrameWindowFilter.py`):
```python
# Get last trading day of each calendar month
def get_calendar_month_end_filter_list(df):
    df['Month'] = df['Date'].dt.to_period('M')
    last_dates = df.groupby('Month')['Date'].max().reset_index()
    return last_dates['Date'].dt.date.tolist()
```
This is used for end-of-month rebalancing strategies.

**Statistical helpers** in `Utils.py`:
- `covariance_x_y()` — beta computation via covariance / market variance
- `get_Z_Score()` — normalises a value against a historical distribution (useful for volume spikes)
- `get_linear_regression_coefficients()` — alpha/beta decomposition (CAPM residuals)

### 1.4 What More Can Be Done

- **Incremental updates**: Currently the system re-downloads if the cache is stale. A proper incremental updater (only fetch new days since last download) would be faster.
- **Corporate actions adjustment**: Yahoo Finance data includes dividends but split-adjustment is not explicitly validated. Price data before a stock split will look artificially different from post-split data.
- **Multi-source fallback**: If Yahoo Finance is down, fall back to NSE direct API or Zerodha Kite (the `AbsoluteMomentum.ipynb` has a Kite Connect cell already). Implementing a unified data interface would make the system more robust.
- **Data quality checks**: Detect outliers (e.g., a price spike 50% in one candle), cross-validate Open against previous Close, detect missing trading days.

### 1.5 Advanced Concepts

**Tick data vs OHLCV**: OHLCV is already aggregated. Raw tick data (every single trade) lets you reconstruct order flow and compute more precise volume-at-price distributions, but requires far more storage and processing.

**Point-in-Time Data**: Survivorship bias is when your backtest universe only contains stocks that survived to today — implicitly excluding stocks that went bankrupt or were delisted. The NSE universe here is built from option-backed underliers (stocks liquid enough to have options), which partially addresses this because delisted stocks lose their options, but it is not a fully point-in-time survivorship-free database.

**Timezone Handling**: Indian markets trade in IST (UTC+5:30). Yahoo Finance returns timestamps in UTC. The `convert_yf_datetime_to_pandas_datetime` and `remove_timeZoneInfo_from_datetime` functions handle this, but in a live system timezone management is critical — one missed DST transition can misalign your signals.

### 1.6 Advanced Extensions

- Implement a **data lake** where raw intraday CSVs are stored in Apache Parquet format, partitioned by symbol and date. This reduces read time by 10–50x for large backtests.
- Build a **reference data cache** (already partially done via `refdata_cache.py`) that maintains corporate actions (splits, dividends, rights issues) so prices are always properly adjusted.
- Add **orderbook data** (bid/ask depth) from Zerodha's WebSocket API for live execution quality analysis.

---

## 2. Technical Indicators & Signal Generation

**Files:** `StrategyRepos/common_indicators.py`, `IndicatorCalculator.py`

### 2.1 Basic Introduction

A **technical indicator** is a mathematical transformation of price (and sometimes volume) data designed to reveal patterns that are not obvious from the raw price series. They fall broadly into three families:

1. **Trend-following indicators** — tell you the direction of the trend (SMA, EMA, MACD)
2. **Momentum/oscillator indicators** — measure the speed of price change and identify overbought/oversold conditions (RSI, Stochastic, SMI)
3. **Volume-based indicators** — incorporate traded volume to confirm or contradict price moves (EMV, Volume Z-score)

None of these indicators predict the future with certainty. They are probabilistic signals that, when combined correctly, can give a statistical edge.

### 2.2 What Is the Use of This

Technical indicators are used to:
- **Generate buy/sell signals** without any fundamental analysis
- **Filter trades** (e.g., only buy when the trend is up)
- **Measure risk** (volatility indicators)
- **Rank stocks** within a universe (which stock has the strongest momentum?)

### 2.3 What Has Been Tried

**`common_indicators.py`** implements eight distinct indicator families:

#### Simple Moving Average (SMA) and Exponential Moving Average (EMA)

```python
# common_indicators.py
df['SMA_10'] = df[col_name].rolling(10).mean()
df['EMA_10'] = df[col_name].ewm(span=10, adjust=False).mean()
```

**SMA** gives equal weight to all `n` recent prices. **EMA** gives exponentially more weight to recent prices (controlled by `span`). EMA reacts faster to new information.

**Signals generated:**
- `SMA_Signal_1`: Buy if price > SMA_10 × 1.01 (1% cushion to avoid whipsaws), Sell if price < SMA_10 × 0.99
- `SMA_Signal_2`: Strong Buy if price above both SMA_20 and SMA_100 (multi-timeframe confirmation)
- Similarly for EMA with spans 10, 20, 50

#### Relative Strength Index (RSI)

```python
# common_indicators.py
df['RSI'] = ta.rsi(df[col_name], length=14)
# Strong Buy: RSI < 30 for 2 consecutive periods
# Strong Sell: RSI > 70 for 2 consecutive periods
```

RSI measures the ratio of average gains to average losses over the last `n` periods (default 14). It oscillates between 0 and 100:
- **Below 30**: Oversold — the asset has fallen too fast, potential reversal up
- **Above 70**: Overbought — the asset has risen too fast, potential reversal down
- The signal requires **two consecutive periods** below/above the threshold — this reduces false signals from brief spikes.

#### MACD (Moving Average Convergence Divergence)

```python
# common_indicators.py
exp12 = df[col_name].ewm(span=12, adjust=False).mean()
exp26 = df[col_name].ewm(span=26, adjust=False).mean()
df['MACD'] = exp12 - exp26
df['MACD_Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
```

MACD = EMA(12) − EMA(26). The signal line is EMA(9) of the MACD. When MACD crosses above its signal line while still below zero — that is a **Strong Buy** (momentum is turning positive from a bearish environment). This cross-validation with zero level is the "strongest signal" refinement.

#### Stochastic Oscillator

```python
# common_indicators.py — %K and %D computation
df['%K'] = 100 * ((df[col_name] - df['Low_Min']) / (df['High_Max'] - df['Low_Min']))
df['%D'] = df['%K'].rolling(d_window).mean()
```

Stochastic measures where the current price sits within its recent high-low range. 0 = at the bottom of the range, 100 = at the top. The crossover of `%K` above `%D` while below 20 is a Strong Buy.

#### SMI (Stochastic Momentum Index)

SMI is a refinement of Stochastic. Instead of measuring position within the high-low range, it measures position relative to the **midpoint** of that range, and applies double EMA smoothing. The formula:

```
diff = Close − midpoint(HighMax, LowMin)
ema1 = EMA(diff, smoothing)
ema2 = EMA(ema1, smoothing)          # double smoothing
SMI = 100 × ema2 / (0.5 × EMA(HighMax - LowMin, smoothing))
```

SMI is less "jerky" than raw Stochastic. Crossovers of the +40/−40 levels are Strong signals; zero-line crossovers are regular signals.

#### RVI (Relative Volatility Index)

```python
# common_indicators.py
delta = df[col_name].diff().fillna(0)
up_vol = delta.where(delta > 0, 0).rolling(window).std()
down_vol = delta.where(delta < 0, 0).abs().rolling(window).std()
df['RVI'] = 100 * avg_up / (avg_up + avg_down)
```

RVI is like RSI but uses **volatility** (standard deviation of up/down moves) instead of the magnitude of price moves. When upside volatility dominates (RVI > 60), the trend is strong and buyers are confident. Strong Buy signal is when RVI crosses above 40 after being below it for 2+ consecutive periods.

#### EMV (Ease of Movement)

```python
# common_indicators.py
df['Midpoint'] = (df['High'] + df['Low']) / 2
df['Distance'] = df['Midpoint'].diff()
df['Box_Ratio'] = (df['High'] - df['Low']) / (df['Volume'] / vol_adjustment)
df['EMV'] = (df['Distance'] / df['Box_Ratio']).rolling(window).mean()
```

EMV answers: "How easily is price moving?" A high EMV means price moved a lot relative to the volume traded — buyers are in control with little resistance. EMV > 0.3 → Strong Buy; crossing above zero → Buy.

#### Reynolds Number

```python
# common_indicators.py — combines RVI and EMV
df['RN'] = df[rvi_col] / df[emv_col]
rolling_std = df['RN'].rolling(window).std()
df['RN_Upper'] = rolling_std * 1.5   # dynamic threshold
```

The Reynolds Number is a **composite indicator** blending volatility character (RVI) with price movement ease (EMV). Dynamic thresholds (1.5× rolling standard deviation) adapt to changing market conditions rather than using fixed levels. This is an original research indicator developed in this codebase.

#### Advances-Declines Indicator

```python
# IndicatorCalculator.py
diff = dataframe.loc[index[i], col] - dataframe.loc[index[i-1], col]
if diff > 0: value = 1    # Advance
elif diff < 0: value = -1 # Decline
else: value = 0           # Unchanged
```

For each period: +1 if price rose, −1 if it fell, 0 if flat. This is a bar-level Advance/Decline indicator. Aggregated across symbols, it becomes a market breadth measure.

#### Kalman Filter Smoothing

```python
# common_indicators.py — Kalman filter as price smoother
kf = KalmanFilter(transition_matrices=[1], observation_matrices=[1], ...)
state_means, _ = kf.filter(df[col_name].values)
```

Used as a **pre-processing step**: smooth out the noisy close price before applying trend indicators. Reduces false signals caused by random intraday volatility.

### 2.4 What More Can Be Done

- **Indicator combination**: All these indicators are computed independently. The next step is to learn how to combine them optimally — e.g., only take a buy signal when RSI + MACD + SMA all agree.
- **Indicator parameter optimisation**: The `AbsoluteMomentum.ipynb` notebook already does grid search over EMA window parameters. This could be extended to RSI and MACD periods using walk-forward optimisation.
- **Adaptive parameters**: Instead of fixed period=14 for RSI, use a period that adapts to current volatility (e.g., shorter when volatility is high, longer when it is low).

### 2.5 Advanced Concepts

**Look-ahead bias in indicators**: Rolling functions like `ewm()` in pandas are **causal** — they only use past data. But if you ever call `.fillna(method='bfill')`, you are filling missing values backward in time, which introduces look-ahead bias. This invalidates your backtest.

**Indicator lag**: All indicators are lagging — they confirm trends that have already started. The shorter the period, the faster the reaction but the more false signals. The longer the period, the smoother but later the signal. This is the fundamental trade-off in indicator design.

**Multi-timeframe analysis**: Compute the same indicator on multiple timeframes (e.g., daily and weekly EMA) and only trade in the direction where both agree. The `common_indicators.py` SMA_Signal_2 does this with SMA_20 and SMA_100.

### 2.6 Advanced Extensions

- Implement **Fisher Transform** to normalise indicator values into a near-Gaussian distribution, making overbought/oversold levels statistically meaningful.
- Build **machine learning-based signal combination**: train a Random Forest or XGBoost classifier where the features are the 8 indicator signals and the target is next-week return direction.
- Research **non-linear indicators**: neural network-based indicators that directly learn from OHLCV data without a predefined mathematical formula.

---

## 3. The Momentum Strategy — Core Idea

**Files:** `FirstMomentumStrategy.py`, `StrategyRepos/FirstBtStrategy.py`

### 3.1 Basic Introduction

**Momentum** is one of the most well-documented phenomena in financial markets: assets that have performed well in the recent past tend to continue performing well in the near future, and assets that have performed poorly tend to continue performing poorly. This is the opposite of the "buy low, sell high" intuition — momentum says "buy high, sell even higher."

The academic literature (Jegadeesh & Titman, 1993) showed that buying the top-performing 10% of stocks over the past 3–12 months and holding them for 3–12 months generates significant alpha. This is called **cross-sectional momentum**.

**Why does momentum exist?**
1. **Behavioral underreaction**: Investors are slow to update their beliefs when good news arrives — prices take time to fully reflect information.
2. **Institutional herding**: Fund managers buy what is already going up (performance chasing), creating self-fulfilling trends.
3. **Feedback loops**: As a stock rises, it attracts more attention, which attracts more buyers.

### 3.2 What Is the Use of This

A momentum strategy automates this process: at regular intervals (e.g., weekly), rank all stocks by their recent return, buy the top N, and sell/avoid the bottom N. Rebalance every period.

### 3.3 What Has Been Tried

**`FirstMomentumStrategy.py`** is the entry point and orchestrates:
1. Build the market universe (`MarketUniverse.optionBackedEquityUniverse()`)
2. Download historical data for each symbol in the universe
3. For each symbol: load, clean, filter by date range and trading hours, compute indicators
4. Run a backtest using the `SmaCross` strategy from `FirstBtStrategy.py`

**`FirstBtStrategy.py`** implements a backtesting strategy using the `backtesting.py` library:

```python
# FirstBtStrategy.py
class SmaCross(Strategy):
    n1 = 20    # EMA period
    n2 = 20    # Bollinger Band period
    n3 = 101   # Hurst Exponent window
    
    def init(self):
        self.SMA = self.I(SMA, self.data.Close, self.n1)    # EMA-based "SMA"
        self.twostdp = self.I(TWOSTD, self.data.Close, self.n2)
        self.minustwostdp = self.I(MINUSTWOSTD, self.data.Close, self.n2)
        self.hurstexp = self.I(hurst_exp, self.data.Close, self.n3)
```

Notice that `SMA()` in `FirstBtStrategy.py` is actually implemented using `ewm()` (EMA), not `rolling().mean()` — a deliberate choice to weight recent prices more. The strategy pre-computes:
- EMA of Close (trend direction)
- Upper Bollinger Band (EMA + 2σ) — potential resistance
- Lower Bollinger Band (EMA − 2σ) — potential support
- Hurst Exponent over a 101-period rolling window (is the market trending?)

The `next()` method is currently empty (`pass`) — the signal logic has been stripped out for research purposes, with multiple commented-out approaches visible in the code. This represents an ongoing research state.

**Candlestick charting** (`FirstMomentumStrategy.py`, lines 119–170):
- Uses Plotly to generate interactive HTML charts with candlesticks + volume overlay + SMA line
- Saves one HTML file per symbol, per date range

**Volume statistics analysis** (`RankingStrategy.py`):
```python
# RankingStrategy.py
filteredSymbolDataFrame['ChangeInClose'] = ((Close - Open)/Open) * 100
meanChangeClose = filteredSymbolDataFrame['ChangeInClose'].mean()
close_std_deviation = filteredSymbolDataFrame['ChangeInClose'].std()
```
For each symbol, computes the mean and standard deviation of intraday price change (Close vs Open). This is used to characterise how "volatile" each stock's intraday moves are — high-mean + low-std stocks are strong candidates.

### 3.4 What More Can Be Done

- **Complete the `next()` method** in `SmaCross`: implement the actual entry/exit logic based on the pre-computed indicators (EMA crossovers, Bollinger Band touches, Hurst regime).
- **Parameter optimisation**: The `n1`, `n2`, `n3` class variables are designed for optimisation via `backtesting.py`'s `Backtest.optimize()` method. Run a grid search to find optimal EMA and Bollinger Band windows.
- **Short selling**: The current strategy only buys. Indian markets allow short selling via futures or options. Adding a short leg would allow profiting from downward momentum.

### 3.5 Advanced Concepts

**Momentum crash risk**: Momentum strategies periodically suffer catastrophic losses called "momentum crashes" — typically at market reversals when crowded momentum positions unwind simultaneously (e.g., 2009 reversal after the financial crisis). Managing this risk is critical.

**Lookback period selection**: The classic academic period is 12 months minus the most recent month (to avoid short-term reversal). The codebase experiments with various windows (20 candles, 30 candles) on weekly data.

**Transaction costs**: Each rebalance incurs costs (brokerage, impact). The `momentumStratPortfolio.py` applies 0.1% (10 bps) transaction cost per trade. At weekly rebalancing with 6 stocks, annual transaction costs can be 5–10% of capital.

### 3.6 Advanced Extensions

- Implement **52-week high momentum**: buy stocks near their 52-week high (George & Hwang, 2004 — shows stronger performance than raw return momentum).
- Add **volatility scaling**: instead of equal-weight, weight positions inversely proportional to realised volatility so each position contributes equal risk.
- Research **earnings momentum (PEAD)**: buy after positive earnings surprises. Combine with price momentum for a more robust signal.

---

## 4. EMA Scoring System & Portfolio Construction

**Files:** `StrategyRepos/AbsoluteMomentum.ipynb`, `StrategyRepos/momentumStratPortfolio.py`

### 4.1 Basic Introduction

Instead of using a single momentum indicator, the system builds a **composite score** across multiple EMA timeframes. The intuition is: a stock that is above its short-term, medium-term, AND long-term moving average, and where each shorter MA is above each longer one, is in a very strong uptrend. Each individual condition is a binary signal (+1 or −1). The sum of all conditions gives a total score.

### 4.2 What Is the Use of This

This multi-timeframe scoring system:
1. Reduces noise compared to any single indicator
2. Creates a natural ranking — stocks with score +10 are much stronger than those with score +6
3. Is easy to interpret and explain to investors ("this stock is above all its major moving averages")

### 4.3 What Has Been Tried

**The 6-condition scoring system** (from `AbsoluteMomentum.ipynb`):

```python
# AbsoluteMomentum.ipynb cell-4 and momentumStratPortfolio.py
symbolDataframe['E10'] = symbolDataframe['Close'].ewm(span=10, adjust=False).mean()
symbolDataframe['E21'] = symbolDataframe['Close'].ewm(span=21, adjust=False).mean()
symbolDataframe['E50'] = symbolDataframe['Close'].ewm(span=50, adjust=False).mean()

symbolDataframe['isCloseAbove10'] = 1 if Close > E10 else -1
symbolDataframe['isCloseAbove21'] = 1 if Close > E21 else -1
symbolDataframe['isCloseAbove50'] = 1 if Close > E50 else -1
symbolDataframe['isE10AboveE21']  = 1 if E10 > E21 else -1
symbolDataframe['isE21AboveE50']  = 1 if E21 > E50 else -1
symbolDataframe['isE10AboveE50']  = 1 if E10 > E50 else -1

symbolDataframe['TotalValue'] = sum of above 6 conditions   # Range: -6 to +6
```

Score of +6 means ALL conditions are met — the strongest possible trend confirmation. Score of −6 means the stock is in a complete downtrend.

**The extended 10-condition system** (in `momentumStratPortfolio.py`):

```python
# momentumStratPortfolio.py — 4 EMA spans
spanList = [int(60//filterTypeDays), int(90//filterTypeDays), 
            int(126//filterTypeDays), int(300//filterTypeDays)]
# These are roughly 2-month, 3-month, 6-month, and 12-month EMAs on weekly data
```

With 4 EMA spans (E10, E15, E21, E50 on weekly data), there are 4 + 6 = 10 binary conditions:
- 4 conditions: Close above each of 4 EMAs
- 6 conditions: each shorter EMA above each longer EMA (C(4,2) = 6 pairs)

This gives a score range of −10 to +10.

**The lag factor** (`momentumStratPortfolio.py`, line 378):
```python
symbolDataframe['E10'] = symbolDataframe['Close'].shift(lagFactor).ewm(span=spanList[0], ...).mean()
```

The `shift(lagFactor)` shifts the input price series forward by `lagFactor` candles before computing the EMA. This intentionally delays the EMA signal by `lagFactor` periods. **Why?** To avoid look-ahead bias in a live setting — when a decision is made at the close of period T, you only know prices up to T-lagFactor for your EMA computation.

**Parameter optimisation** (`AbsoluteMomentum.ipynb` cell-12):

```python
# Grid search over EMA windows and momentum lookback periods
parameter_combinations = list(product(
    lookbackPeriod_range,   # range(3, 8)
    windowSize_range,       # range(20, 46)
    ewmWindow1_range,       # range(5, 21)
    ewmWindow2_range,       # range(21, 51)
    ewmWindow3_range        # range(50, 71)
))
with ProcessPoolExecutor(max_workers=15) as executor:
    results = list(executor.map(process_combination, parameter_combinations))
```

This parallelised grid search runs each parameter combination in a separate process. The code structure is in place but the selection criterion (which metric to maximise) needs to be added.

**Weekly resampling with `filterTypeDays=6`** (`momentumStratPortfolio.py`):
- Every 6 trading days ≈ one calendar week
- The `filter_dataframe_by_days()` function from `Utils.py` collapses daily data into 6-day bars
- All momentum computations then run on these "weekly" bars

### 4.4 What More Can Be Done

- **Weighted scoring**: Instead of equal weight for each binary condition, assign higher weights to longer-term conditions (they are more meaningful for medium-term strategies).
- **Continuous scoring**: Replace the binary −1/+1 with a continuous measure: how far is the Close above the EMA as a percentage? A stock 5% above its EMA is stronger than one 0.1% above.
- **Sector-relative scoring**: Rank the score relative to sector peers, not the full universe.

### 4.5 Advanced Concepts

**William O'Neil's CANSLIM**: The idea of requiring price above multiple timeframe MAs before buying is similar to O'Neil's technical criteria. This codebase implements a quantitative version of that qualitative framework.

**Trend Template** (Minervini): A famous swing trader's checklist requires price above 50-day, 150-day, and 200-day MA, with each shorter MA above each longer one. The 6-condition scoring is essentially a quantitative implementation of this template, scoring how many conditions are met.

**Cross-sectional vs time-series momentum**: The EMA score is a **cross-sectional** ranking — it ranks stocks against each other at a given point in time. The `ReturnChange` column (N-period return) is a **time-series** momentum measure — it tells you whether a stock is going up, regardless of how other stocks are doing.

### 4.6 Advanced Extensions

- Implement **dual momentum** (Gary Antonacci): combine cross-sectional momentum (rank best stock) with absolute momentum (only hold if the stock has positive absolute return). This reduces drawdowns during bear markets.
- Add **earnings quality filters**: only buy momentum stocks with positive earnings revisions (analyst upgrades) to reduce the risk of buying on false premises.
- Research **momentum with volatility adjustment** (AQR style): divide the momentum return by its realised volatility. This gives equal risk weight to all signals.

---

## 5. FIP Value — Frequency-Imbalance Persistence Scoring

**Files:** `StrategyRepos/AbsoluteMomentum.ipynb`, `StrategyRepos/momentumStratPortfolio.py`

### 5.1 Basic Introduction

The **FIP (Frequency-Imbalance Persistence) Value** is an original indicator developed in this research. It addresses a specific question: *Is the recent momentum in price supported by a persistent imbalance in the direction of price moves?*

A stock can have a high 6-month return but most of that return might have come from a few big-up days surrounded by many small-down days. Such "fragile momentum" is less reliable than a stock that has had steady, consistent upward movement most days.

### 5.2 What Is the Use of This

The FIP Value:
1. Acts as a **momentum quality filter** — high-quality momentum has consistent directional persistence
2. Is used as a **secondary sort criterion** after the EMA TotalValue score
3. Penalises stocks where the direction count is "confused" (almost equal up and down days)

### 5.3 What Has Been Tried

**The core computation** (`AbsoluteMomentum.ipynb`, `momentumStratPortfolio.py`):

```python
# momentumStratPortfolio.py
symbolDataframe['ReturnChange'] = ((Close.shift(lagFactor) - Close.shift(moveToShiftForReturn + lagFactor))
                                   / Close.shift(moveToShiftForReturn + lagFactor)) * 100
symbolDataframe['PRET'] = 1 if ReturnChange > 0 else -1   # Positive or Negative return

symbolDataframe['Direction'] = symbolDataframe['Close'].diff()  # +ve if up, -ve if down
symbolDataframe['PositivePercentage'] = Direction.shift(lagFactor).rolling(FIPWindowSpan).apply(
    lambda x: len([i for i in x if i > 0]))   # Count of up-days in window
symbolDataframe['NegativePercentage'] = Direction.shift(lagFactor).rolling(FIPWindowSpan).apply(
    lambda x: len([i for i in x if i < 0]))   # Count of down-days in window

symbolDataframe['FIPValue1'] = PRET * ((NegativePercentage/FIPWindowSpan) - (PositivePercentage/FIPWindowSpan))
symbolDataframe['FIPValue']  = NegativePercentage/30 if PRET == -1 else PositivePercentage/30
```

**How FIPValue1 works:**

If `PRET = +1` (stock has positive recent return), then:
`FIPValue1 = 1 × (NegDays/N − PosDays/N) = fraction of down days − fraction of up days`

A **negative FIPValue1** when PRET=+1 means: the stock went up AND most days were up-days (NegDays < PosDays). This is **good quality momentum**.

A **positive FIPValue1** when PRET=+1 means: the stock went up but most days were down-days (a few large-up-day jumps). This is **fragile momentum**.

**Portfolio ranking** (`momentumStratPortfolio.py`, line 575):
```python
symbolDf1 = symbolDf1.sort_values(
    by=['TotalScore', 'Strength', 'FIPScore'], 
    ascending=[False, False, True]   # FIPScore ascending = lower (more negative) is better
)
portfolioSymbolsToAdd = symbolDf1.head(stocksToSelect)['Symbol'].tolist()
```

Stocks are sorted: highest EMA TotalScore first, then highest Regime Strength, then most negative FIPValue (best quality momentum) last as tiebreaker.

**FIPValue** (simpler version): just the fraction of up/down days in the window, used as an alternative rank metric.

### 5.4 What More Can Be Done

- **Calibrate the window**: `FIPWindowSpan = int(240 // filterTypeDays)` ≈ 40 weeks on weekly data. Test shorter windows (20 weeks) and longer windows (60 weeks).
- **Weighted direction count**: Instead of counting all up-days equally, weight each day's contribution by the magnitude of the move. A +5% day should count more than a +0.1% day.
- **FIP decay**: More recent direction information is more relevant. Apply exponential decay weights to the rolling window.

### 5.5 Advanced Concepts

**Autocorrelation of returns**: The FIP Value is essentially measuring the autocorrelation of the sign of daily returns. High positive autocorrelation (most returns in the same direction) = high persistence = reliable momentum signal. The Hurst Exponent (Section 7) formalises this mathematically.

**Garman-Klass volatility vs up-day count**: The FIP approach counts the *number* of up days. An alternative is to measure the ratio of upside variance to total variance (related to the RVI indicator in Section 2). Both capture the same underlying idea from different angles.

### 5.6 Advanced Extensions

- Combine FIP with **earnings announcement timing**: stocks that show consistent positive persistence and are approaching earnings are at higher risk of reversal. Add an earnings calendar filter.
- Research **sector FIP breadth**: instead of computing FIP per stock, compute the fraction of stocks in a sector that have positive FIP. This becomes a sector-level breadth indicator that can time sector rotations.

---

## 6. Regime-Aware Relative Strength Classification

**Files:** `StrategyRepos/momentumStratPortfolio.py`

### 6.1 Basic Introduction

A **market regime** is a period during which the market behaves in a characteristically different way — typically distinguished as "bull market" (rising) vs "bear market" (falling). The key insight in regime-aware investing is: a stock's behaviour during an adverse regime tells you more about its intrinsic strength than its behaviour during a favourable regime.

Think of it like testing athletes: the real champions are those who perform well under pressure, not just when conditions are perfect.

### 6.2 What Is the Use of This

Regime-aware strength classification helps:
1. Identify stocks that protect capital during downturns
2. Find stocks that outperform even when the market is struggling
3. Rank stocks on a quality-adjusted basis rather than raw momentum

### 6.3 What Has Been Tried

**The regime change detection** (`momentumStratPortfolio.py`, lines 339–373):

```python
# momentumStratPortfolio.py
symbolDataframe['BenchmarkCR'] = ((BenchmarkPrice - BenchmarkPrice.shift(regimeLookBackValue)) 
                                   / BenchmarkPrice.shift(regimeLookBackValue)) * 100
symbolDataframe['CloseCR']     = ((Close - Close.shift(regimeLookBackValue)) 
                                   / Close.shift(regimeLookBackValue)) * 100
```

`BenchmarkCR` = Nifty 200 return over the last `regimeLookBackValue` periods.
`CloseCR` = Individual stock return over the same period.

**Finding the "opposite regime" index**:
```python
def find_regime_change(row_idx, cr_series, window):
    current_cr = cr_series.iloc[row_idx]
    for i in range(row_idx - window, -1, -1):
        prev_cr = cr_series.iloc[i]
        # Find the most recent period where the market was in the opposite direction
        if (current_cr > 0 and prev_cr < 0) or (current_cr < 0 and prev_cr > 0):
            return i
    return np.nan
```

For each current date, this finds the most recent date when the Nifty 200 was going in the opposite direction. This gives us `CloseOppositeCR` — how the stock performed during the opposite market regime.

**The `classify_strength()` function** (`momentumStratPortfolio.py`, lines 208–271):

This is a rule-based classifier scoring stocks from −10 to +100 based on four inputs:
- `cr`: current stock return (in current regime)
- `cr_opp`: stock return during the opposite regime
- `bench`: benchmark return in current regime
- `bench_opp`: benchmark return in opposite regime

Highest scores (100, 90, 80):
- Score 100: Stock beats benchmark in BOTH the current regime AND the opposite regime — a true all-weather performer
- Score 90: Stock beats benchmark now AND falls less than benchmark in adverse conditions
- Score 80: Stock beats benchmark now AND matches benchmark in adverse conditions

Lowest scores (0, −5, −10):
- Score −10: Stock falls when market rises AND falls when market falls — systematically broken
- Score −5: Stock falls in rallies but rises in crashes — defensive but not a momentum candidate

**The `classify_strength_alternate()` function** handles the case where the current regime is bearish (BenchmarkCR < 0), adjusting the logic accordingly.

**Dynamic dispatch**:
```python
def dynamic_strength_label(row):
    if row['BenchmarkCR'] > 0 and row['BenchmarkOppositeCR'] < 0:
        return classify_strength(row)         # Market up now, was down before
    elif row['BenchmarkCR'] < 0 and row['BenchmarkOppositeCR'] > 0:
        return classify_strength_alternate(row)  # Market down now, was up before
```

### 6.4 What More Can Be Done

- **Continuous scoring**: Replace the rule-based score table with a continuous formula. E.g., `Strength = (cr − bench) / std(cr, bench) + (cr_opp − bench_opp) / std(cr_opp, bench_opp)`.
- **Multi-regime**: The current code has just 2 regimes (up/down). Real markets have at least 4: strong bull, weak bull, weak bear, strong bear. Use a 4-regime HMM (see Section 10) to classify.
- **Regime duration weighting**: A stock that performed well during a 6-month bear market is more impressive than one that did well during a 2-week bear spell. Weight `cr_opp` by the duration of the opposite regime.

### 6.5 Advanced Concepts

**Alpha vs beta**: In CAPM, `alpha` is the return above what would be predicted by the stock's beta (market sensitivity). A stock with high alpha consistently outperforms regardless of market direction. The `Strength` score here is an approximation of alpha quality.

**Conditional correlation**: An advanced version of this analysis computes the correlation between a stock and the market separately for up-market and down-market periods. Stocks with low correlation during down markets (but high during up markets) are the most desirable — they don't give back gains during downturns.

**Factor models**: The Fama-French three-factor model (market, size, value) and Carhart four-factor (adding momentum) provide a more rigorous framework for attributing returns to systematic factors vs stock-specific alpha. The `Strength` score is essentially a simplified factor attribution.

### 6.6 Advanced Extensions

- Implement **rolling alpha calculation**: compute CAPM alpha for each stock over a rolling 6-month window. Use this as an additional rank criterion.
- Research **defensive momentum**: screen for stocks that have positive momentum AND low beta. These provide momentum returns with lower crash risk.

---

## 7. Hurst Exponent — Trending vs Mean-Reverting Markets

**Files:** `StrategyRepos/hurst.ipynb`, `StrategyRepos/FirstBtStrategy.py`

### 7.1 Basic Introduction

The **Hurst Exponent (H)** is a statistical measure of the long-term memory of a time series. It was developed by hydrologist Harold Hurst studying the Nile River's annual flood cycles. In finance, it tells you whether a price series has a **persistent trend** (momentum) or a **mean-reverting** character.

Interpretation:
- **H > 0.5**: Trending series — past moves predict future moves in the **same** direction
- **H = 0.5**: Random walk — past moves give no information about future (Efficient Market Hypothesis)
- **H < 0.5**: Mean-reverting series — past moves predict future moves in the **opposite** direction

### 7.2 What Is the Use of This

The Hurst Exponent is used to:
1. **Choose the right strategy**: Trend-following strategies work when H > 0.5; mean-reversion (contrarian) strategies work when H < 0.5
2. **Regime filtering**: Only apply momentum strategies when the Hurst Exponent confirms a trending regime
3. **Volatility prediction**: Persistent series have different volatility profiles than mean-reverting ones

### 7.3 What Has Been Tried

**Two computation methods** (`hurst.ipynb`):

```python
# hurst.ipynb — using the hurst library (R/S analysis method)
H1, c1, data1 = compute_Hc(df['Close_diff'].dropna().values, kind='change', simplified=True)
H2, c2, data2 = compute_Hc(df['Close_log_diff'].dropna().values, kind='change', simplified=True)
```

The first uses differenced price (absolute changes), the second uses log returns. Log returns are preferred because they are approximately stationary (constant mean and variance) — a requirement for H to be well-defined.

**Manual R/S computation** (`hurst.ipynb`):
```python
def compute_hurst_exponent(ts, max_lag=100):
    lags = range(2, max_lag)
    tau = [np.std(np.subtract(ts[lag:], ts[:-lag])) for lag in lags]
    hurst_exp = np.polyfit(np.log(lags), np.log(tau), 1)[0]
    return hurst_exp
```

This computes the **slope of log(lag) vs log(standard deviation of differences)** — essentially fitting a power law. If H = 0.5, standard deviation grows as `sqrt(lag)` (random walk). If H > 0.5, it grows faster.

**Rolling Hurst in backtesting** (`FirstBtStrategy.py`):
```python
# FirstBtStrategy.py
def hurst_exp(values, n):
    hurst_exp = pd.Series(values).rolling(n).apply(
        lambda x: computeHc(x, max_lag=50), raw=True)
    return hurst_exp

class SmaCross(Strategy):
    n3 = 101  # Rolling window for Hurst Exponent
    def init(self):
        self.hurstexp = self.I(hurst_exp, self.data.Close, self.n3)
```

This computes a rolling 101-period Hurst Exponent during the backtest — giving a time-varying picture of when the market is trending vs mean-reverting.

**Strategy testing** (`hurst.ipynb`):

The notebook tests two strategies on Reliance's stock and compares their performance:

*Bollinger Band Strategy (mean-reversion — bets on H < 0.5)*:
```python
# hurst.ipynb
df['Signal'] = 0
df.loc[df['Close'] < df['Lower_Band'], 'Signal'] = 1   # Buy when below lower band
df.loc[df['Close'] > df['Upper_Band'], 'Signal'] = -1  # Sell when above upper band
```

*RSI Strategy (also mean-reversion)*:
```python
# hurst.ipynb
df.loc[df['RSI'] < oversold, 'Signal'] = 1    # Buy oversold
df.loc[df['RSI'] > overbought, 'Signal'] = -1 # Sell overbought
```

Both strategies are backtested and their cumulative returns plotted. This directly validates whether the Hurst Exponent regime prediction matches actual strategy performance.

### 7.4 What More Can Be Done

- **Conditional strategy switching**: Compute rolling Hurst. When H > 0.55 → switch to momentum strategy. When H < 0.45 → switch to mean-reversion strategy. When 0.45 < H < 0.55 → stay in cash.
- **Multi-symbol Hurst analysis**: Compute Hurst across the full NSE universe. The distribution of H values tells you whether the market as a whole is in a trending or mean-reverting regime.
- **Time-scale specific Hurst**: Compute H at different frequencies (daily vs weekly). A stock might trend on a weekly basis but mean-revert intraday.

### 7.5 Advanced Concepts

**Fractional Brownian Motion (fBm)**: The mathematical model underlying the Hurst Exponent. A standard random walk has H=0.5. fBm generalises this to any H ∈ (0,1). The increments of fBm with H≠0.5 are correlated — this is what "long-range memory" means.

**Detrended Fluctuation Analysis (DFA)**: A more robust alternative to R/S analysis for computing the Hurst Exponent, less sensitive to trends in the data. The `compute_Hc` library function uses R/S; DFA would be a significant improvement.

**ADF Test vs Hurst**: The Augmented Dickey-Fuller (ADF) test (used extensively in `arima.ipynb` and `hurst.ipynb`) tests for a unit root — whether the series is stationary. ADF and Hurst are related but measure different things: ADF tests for I(1) non-stationarity; Hurst measures long-memory regardless of stationarity.

### 7.6 Advanced Extensions

- Implement **wavelet-based Hurst estimation**: decomposes the time series into frequency components and estimates H for each scale — gives a richer picture of persistence across different time horizons.
- Research **multifractal analysis**: real financial markets are not monofractal (single H). They have different H values at different scales and during different regimes. MultiFractal Detrended Fluctuation Analysis (MF-DFA) captures this.

---

## 8. ARIMA Time-Series Forecasting

**Files:** `StrategyRepos/arima.ipynb`

### 8.1 Basic Introduction

**ARIMA (AutoRegressive Integrated Moving Average)** is a classical statistical model for time-series forecasting. It models the next value of a series as a linear combination of:
- **AR (AutoRegressive)**: past values of the series (the "momentum" component)
- **I (Integrated)**: differencing to make the series stationary
- **MA (Moving Average)**: past forecast errors (the "correction" component)

The model is written as ARIMA(p, d, q) where:
- **p**: number of autoregressive lags
- **d**: degree of differencing (typically 1 for stock prices)
- **q**: number of moving average terms

### 8.2 What Is the Use of This

ARIMA is used for:
1. **Price forecasting**: predict tomorrow's closing price
2. **Return forecasting**: predict whether tomorrow's return will be positive or negative
3. **Baseline benchmark**: ARIMA provides a simple, interpretable baseline to beat with more complex models (LSTM, GARCH)

### 8.3 What Has Been Tried

**Walk-forward validation** (`arima.ipynb`, cell 1):

```python
# arima.ipynb — strict walk-forward: train on window of 200 samples, predict 1 step ahead
for t in range(test_size):
    train_returns = np.log(history).diff().dropna()  # Log returns for stationarity
    
    model = auto_arima(train_returns, seasonal=False, 
                       stepwise=True, max_p=5, max_q=5, max_d=1)
    p, d, q = model.order
    
    return_forecast = model_fit.get_forecast(steps=1).predicted_mean.iloc[0]
    price_forecast = last_price * np.exp(return_forecast)  # Convert return to price
    
    history = pd.concat([history.iloc[1:], pd.Series(actual)])  # Roll forward by 1
```

Key choices:
- Uses **log returns** (not raw prices) — log returns are approximately stationary, a requirement for ARIMA
- **`auto_arima`** from `pmdarima` automatically selects p, d, q using information criteria (AIC/BIC)
- **Rolling window of 200 samples** — older data is discarded; only the most recent 200 log returns are used for each forecast

**Model reuse with periodic refit** (`arima.ipynb`, cell 4):

```python
# arima.ipynb — fixed order ARIMA(1,0,0) with periodic refit every 5 steps
if model_fit is None or t % 5 == 0:
    arima_model = SARIMAX(train_returns, order=(1, 0, 0), trend='c')
    model_fit = arima_model.fit(disp=0)
```

After ACF/PACF analysis showed the optimal order is ARIMA(1,0,0), the model is hardcoded and only refit every 5 steps (not every step). This is much faster while losing minimal accuracy.

**ARIMA-GARCH hybrid** (`arima.ipynb`, cell 6):

```python
# arima.ipynb — ARIMA for mean + GARCH for volatility
arima_model = SARIMAX(train_returns, order=(1, 0, 0), trend='c')
model_fit = arima_model.fit(disp=0)

garch_model = arch_model(residuals, vol='GARCH', p=1, q=1, dist='t')
garch_result = garch_model.fit(...)

return_forecast = model_fit.get_forecast(steps=1).predicted_mean.iloc[0]
vol_forecast = garch_result.forecast(horizon=1).variance.iloc[-1,0]

upper_bound = price_forecast * np.exp(1.96 * vol_forecast)   # 95% prediction interval
lower_bound = price_forecast * np.exp(-1.96 * vol_forecast)
```

This separates the model into two components: ARIMA models the conditional **mean** of returns, GARCH models the conditional **variance** (volatility). This is the standard industry approach for price forecasting with uncertainty quantification.

**Performance metrics computed**:
- MAE (Mean Absolute Error)
- RMSE (Root Mean Squared Error)
- R² (coefficient of determination)
- MAPE (Mean Absolute Percentage Error)
- **Directional Accuracy**: what fraction of times does the model correctly predict up vs down movement

### 8.4 What More Can Be Done

- **ARIMAX**: Add exogenous variables (X) to the ARIMA model — e.g., NSE VIX (volatility index), FII flows, sectoral ETF performance as additional predictors.
- **Seasonal ARIMA (SARIMA)**: Indian markets have seasonality — March (fiscal year end), June (quarterly results), October (festive season). SARIMA captures this.
- **Online learning**: Instead of a fixed rolling window, use an online EM algorithm that updates ARIMA parameters incrementally without full refit.

### 8.5 Advanced Concepts

**Stationarity requirement**: The ADF test in `arima.ipynb` confirms that log returns are stationary (p-value ≈ 10⁻¹⁸ << 0.05). Raw prices are NOT stationary (unit root). ARIMA(d=1) applied to prices is equivalent to ARIMA(d=0) applied to returns — the differencing makes it stationary.

**ACF/PACF analysis**: `arima.ipynb` plots ACF (AutoCorrelation Function) and PACF (Partial ACF) of returns. In theory, AR(p) shows PACF cutting off at lag p; MA(q) shows ACF cutting off at lag q. The finding that ARIMA(1,0,0) fits well means there is first-order autocorrelation in log returns — consistent with momentum on short timeframes.

**Information criteria**: `auto_arima` selects p, d, q by minimising AIC (Akaike Information Criterion) or BIC (Bayesian Information Criterion). These penalise model complexity — preventing overfitting by favouring simpler models.

**Directional accuracy vs price accuracy**: For trading, directional accuracy (did we predict up or down correctly?) is far more important than raw price accuracy (MAE/RMSE). A model with poor RMSE but 60% directional accuracy is extremely valuable; a model with perfect RMSE but 50% directional accuracy is useless.

### 8.6 Advanced Extensions

- Implement **Conformal Prediction Intervals** instead of Gaussian intervals: these give coverage guarantees without distributional assumptions.
- Research **Ensemble ARIMA**: train multiple ARIMA models on different sub-windows and average their forecasts — reduces variance of individual model errors.
- Study **TBATS (Trigonometric, Box-Cox, ARMA, Trend, Seasonal)**: extends ARIMA for complex multi-seasonal patterns common in intraday data.

---

## 9. GARCH & Volatility Modelling

**Files:** `StrategyRepos/volatility_modelling.ipynb`, `StrategyRepos/ms_garch.ipynb`

### 9.1 Basic Introduction

**Volatility** in finance means how much prices fluctuate. Unlike in physics, financial volatility is not constant — it **clusters**: periods of high volatility are followed by more high volatility; calm periods are followed by calm periods. This is called **volatility clustering**.

**GARCH (Generalised AutoRegressive Conditional Heteroskedasticity)** is the standard model for this phenomenon. The conditional variance (volatility²) at time t depends on:
1. Past squared residuals (ARCH effect) — recent shocks increase volatility
2. Past conditional variances (GARCH effect) — volatility is persistent

### 9.2 What Is the Use of This

Volatility modelling is used for:
1. **Position sizing**: risk-adjusted positions (smaller positions when volatility is high)
2. **Options pricing**: options are priced based on expected volatility
3. **Risk management**: VaR (Value at Risk) calculations require volatility forecasts
4. **Signal quality**: momentum signals are more reliable when volatility is low

### 9.3 What Has Been Tried

**Standard GARCH(1,1)** — Python and R implementations:

```python
# volatility_modelling.ipynb (ms_garch.ipynb cell-6)
from arch.univariate import ConstantMean, GARCH
garch = ConstantMean(df["Log_Returns"])
garch.volatility = GARCH(1, 1)
garch_fit = garch.fit()
df["GARCH_Volatility"] = garch_fit.conditional_volatility
```

GARCH(1,1) formula: `σ²_t = ω + α × ε²_{t-1} + β × σ²_{t-1}`
- **ω**: long-run average variance
- **α**: ARCH coefficient — sensitivity to recent shocks
- **β**: GARCH coefficient — persistence of volatility
- If α + β ≈ 1: shocks are very persistent (typical for stock markets)

**The R implementation** (`ms_garch.ipynb`, cell 0-1) uses the `rugarch` package, which is more mature for GARCH than Python alternatives:
```r
# ms_garch.ipynb
garch_spec <- ugarchspec(
  variance.model = list(model = "sGARCH", garchOrder = c(1,1)),
  mean.model = list(armaOrder = c(0,0)),
  distribution.model = "std"   # Student-t distribution for fat tails
)
```

The use of Student-t distribution for errors is important — stock returns have **fat tails** (extreme events occur more often than a normal distribution predicts). Student-t captures this.

**EGARCH (Exponential GARCH)** (`ms_garch.ipynb`, cell 2):

```r
garch_spec <- ugarchspec(
  variance.model = list(model = "eGARCH", garchOrder = c(1,1)),
  mean.model = list(armaOrder = c(1,0), include.mean = TRUE)
)
```

EGARCH models the log of variance (ensuring σ² > 0 without parameter constraints) and captures the **leverage effect**: negative price shocks increase volatility more than positive shocks of the same magnitude. This is well-documented for equity markets.

**Markov-Switching Model** (`ms_garch.ipynb`, cell 5 Python, cell 2 R):

```python
# volatility_modelling.ipynb — 2-regime Markov switching model
ms_model = MarkovRegression(df["Log_Returns"], k_regimes=2, trend="c", switching_variance=True)
ms_fit = ms_model.fit()
df["Regime_1_Prob"] = ms_fit.smoothed_marginal_probabilities[0]  # Low volatility
df["Regime_2_Prob"] = ms_fit.smoothed_marginal_probabilities[1]  # High volatility
```

This fits a 2-regime model where returns are drawn from two different distributions (low-volatility and high-volatility regimes) with a Markov transition structure. The output is the probability of being in each regime at each time point.

**ARIMA-GARCH combined** (`arima.ipynb` cell 6, `ms_garch.ipynb` R cell 2):
- ARIMA provides the mean forecast (where will the price go?)
- GARCH provides the volatility forecast (how certain are we?)
- Combined: ARIMA mean ± GARCH-based confidence interval

**Metrics used**:
- MAE, RMSE, R², MAPE for price accuracy
- **Coverage_95%**: does the actual price fall within the predicted 95% interval 95% of the time?
- **Directional Accuracy**
- **MASE** (Mean Absolute Scaled Error) — normalised by naive forecast performance
- **Theil's U** — measures improvement over a naïve baseline

### 9.4 What More Can Be Done

- **Realised volatility**: Instead of model-based volatility, compute it from high-frequency intraday data (sum of squared 5-minute returns = daily realised variance). Use this as a target for GARCH forecasts.
- **HAR-RV model**: Heterogeneous AutoRegressive model of Realised Volatility — regresses realised volatility on its own daily, weekly, and monthly averages. Extremely simple but very powerful.
- **VaR backtesting**: Use GARCH volatility forecasts to compute 1-day 99% VaR. Then check empirically how often actual losses exceed VaR (should be 1% of days).

### 9.5 Advanced Concepts

**Volatility risk premium**: Implied volatility (from options prices) is systematically higher than realised volatility. Selling options (collecting premium) profits from this difference. GARCH can help identify when the premium is unusually high or low.

**Correlation clustering**: Just like individual volatility clusters, the correlation between assets also clusters — during market stress, correlations spike toward 1 (diversification disappears). DCC-GARCH (Dynamic Conditional Correlation) models this jointly.

**Non-stationarity of GARCH parameters**: The optimal GARCH parameters (α, β, ω) change over time. The rolling-window approach in `arima.ipynb` handles this by re-estimating parameters every 5 steps.

### 9.6 Advanced Extensions

- Implement **GARCH-GJR (Glosten-Jagannathan-Runkle)**: explicitly models the asymmetric volatility response to positive vs negative shocks.
- Research **Stochastic Volatility (SV) models**: treat volatility as a latent (unobserved) stochastic process rather than a deterministic function of past observations. More flexible but harder to estimate.
- Build a **volatility surface**: model the term structure of volatility (1-day, 1-week, 1-month forecasts simultaneously) using the Heston model or variance curve fitting.

---

## 10. Hidden Markov Models (HMM) for Regime Detection

**Files:** `StrategyRepos/hmm_regime_detection.ipynb`

### 10.1 Basic Introduction

A **Hidden Markov Model (HMM)** assumes that the observed data (stock returns) are generated by an underlying **hidden state** (market regime) that switches over time according to a Markov chain. "Hidden" means we cannot directly observe which regime we are in — we can only infer it probabilistically from the returns.

The simplest financial HMM has 2 or 3 hidden states:
- State 0: Bear market — negative mean return, high volatility
- State 1: Sideways market — near-zero mean return, moderate volatility
- State 2: Bull market — positive mean return, low volatility

### 10.2 What Is the Use of This

HMMs are used for:
1. **Regime identification**: Objectively identify what type of market we are currently in
2. **Strategy switching**: Use momentum in bull regimes, hedging in bear regimes
3. **Portfolio rebalancing**: Reduce equity exposure when the model signals a bear regime
4. **Feature engineering**: Regime probability as a feature for downstream ML models

### 10.3 What Has Been Tried

**Simple 3-state HMM** (`hmm_regime_detection.ipynb`, cell 2):

```python
# hmm_regime_detection.ipynb
X = data[['log_return', 'adx', 'ma_slope', 'rsi', 'macd_diff']].values
model = GaussianHMM(n_components=3, covariance_type="full", n_iter=1000)
model.fit(X)
hidden_states = model.predict(X)
data['regime'] = hidden_states
```

The model uses 5 features simultaneously:
- `log_return`: the primary signal
- `adx`: trend strength
- `ma_slope`: trend direction
- `rsi`: momentum
- `macd_diff`: momentum divergence

Using multiple features makes the regime assignment more robust than log-return alone.

**Automated HMM tuning via BIC** (`hmm_regime_detection.ipynb`, cell 0):

```python
# hmm_regime_detection.ipynb
def tune_hmm_state(X, state_range=range(2, 7), covariance_types=['full', 'diagonal'], ...):
    for n_states in state_range:
        for cov_type in covariance_types:
            model = GaussianHMM(n_components=n_states, covariance_type=cov_type, ...)
            model.fit(X)
            bic = compute_bic(model, X)  # -2*logL + n_params*log(n_samples)
            if bic < best_bic:
                best_model = model
```

BIC (Bayesian Information Criterion) penalises complexity — more states = higher complexity. The optimal number of states minimises BIC. Tests 2 through 6 states with both 'full' and 'diagonal' covariance types.

**Trending regime identification** (`hmm_regime_detection.ipynb`):

```python
trending_criteria = {
    'log_return': lambda x: x > 0,    # Positive average return
    'adx': lambda x: x > 25,          # Strong trend (ADX > 25 threshold)
    'rsi': lambda x: x > 50,          # Momentum positive
    'macd_diff': lambda x: x > 0      # MACD positive
}
is_trending = all(criterion(regime_means[current_regime][feature]) 
                  for feature, criterion in trending_criteria.items())
persistent = (recent_states[-MIN_TREND_DURATION:] == current_regime).all()
```

A regime is classified as "trending" only if ALL four criteria are met AND the regime has persisted for at least `MIN_TREND_DURATION=5` consecutive days. This prevents trading on brief regime spikes.

**Portfolio integration** (`hmm_regime_detection.ipynb`):

```python
# hmm_regime_detection.ipynb — score for portfolio ranking
score = base_score + params['weight_ma'] * avg_ma_slope + params['weight_adx'] * avg_adx
```

Stocks in trending regimes receive a positive score, proportional to the strength of the trend indicators. Non-trending stocks receive score 0. This integrates the HMM signal into the portfolio construction.

**Hyperparameter tuning** (`hmm_regime_detection.ipynb`):

```python
# hmm_regime_detection.ipynb — grid search on training set
candidate_weight_ma  = [0.0005, 0.001, 0.0015]
candidate_weight_adx = [0.005, 0.01, 0.015]
best_params = tune_parameters(symbols, data_dir, TRAIN_START, TRAIN_END)
```

The MA and ADX weights are optimised on a training period (2020–2022) before being applied to the test period (2022–2023). This is proper walk-forward methodology.

### 10.4 What More Can Be Done

- **Online HMM**: The current HMM is batch — trained on all historical data. An online (real-time updating) HMM using the Viterbi algorithm would update regime probabilities as new data arrives.
- **Markov switching with GARCH**: Combine the Markov switching from `ms_garch.ipynb` with the HMM regime detection — model both the mean return regime AND the volatility regime as hidden states.
- **Macro feature integration**: Add non-price features to the HMM: NSE VIX, FII/DII flows, credit spreads, INR/USD rate. Macro data often leads price-based signals by several days.

### 10.5 Advanced Concepts

**Viterbi algorithm**: The most likely sequence of hidden states given the observed data. This is what `model.predict(X)` computes — it finds the most probable path through the hidden states, respecting the Markov transition probabilities.

**Forward-Backward algorithm**: Instead of the single most likely state sequence, computes the probability of being in each state at each time point. This gives a smoother, probabilistic view of regimes. `model.predict_proba(X)` uses this.

**Non-stationarity problem**: HMM assumes stationary transition probabilities (the probability of switching from bull to bear is the same in 2015 and in 2023). Real markets have non-stationary regimes. A solution is time-varying HMM, which re-estimates transition probabilities in rolling windows.

### 10.6 Advanced Extensions

- Implement **Factor HMM**: model each factor (value, momentum, quality) as having its own hidden regime, and observe how factor regimes correlate and lead/lag each other.
- Research **Regime prediction**: can you predict regime transitions in advance? If so, you can pre-position before the transition. Use logistic regression or gradient boosting to predict P(regime change in next k days).

---

## 11. LSTM Deep Learning for Price Prediction

**Files:** `StrategyRepos/lstm_predictor.ipynb`

### 11.1 Basic Introduction

**LSTM (Long Short-Term Memory)** is a type of Recurrent Neural Network (RNN) specifically designed to learn long-range temporal dependencies. Unlike simple RNNs that forget information quickly, LSTMs have a "memory cell" that can retain information across hundreds of time steps.

In financial forecasting, the intuition is: rather than hand-crafting momentum indicators, let a neural network learn which patterns in the past 60 days' OHLCV + indicators are predictive of tomorrow's return.

### 11.2 What Is the Use of This

LSTM is used for:
1. **End-to-end feature learning**: the network automatically learns which combinations of indicators are predictive
2. **Non-linear pattern recognition**: captures complex relationships that linear models (ARIMA) cannot
3. **Multi-input forecasting**: simultaneously processes multiple feature streams

### 11.3 What Has Been Tried

**Feature engineering** (`lstm_predictor.ipynb`):

```python
# lstm_predictor.ipynb
feature_cols = ['Open', 'High', 'Low', 'Close', 'Volume',
                'SMA_5', 'SMA_10', 'SMA_20',
                'EMA_5', 'EMA_10', 'EMA_20',
                'RSI_14',
                'BB_Upper', 'BB_Lower', 'BB_Mid',
                'MACD', 'MACD_Signal']   # 17 features
```

The model uses 17 features including raw OHLCV and pre-computed indicators.

**Dual targets** (`lstm_predictor.ipynb`):
```python
# Two targets simultaneously
df['Target']    = df['Close'].shift(-1)   # Regression: predict next day's price
df['Direction'] = (df['Target'] > df['Close']).astype(int)  # Classification: up or down
```

**Sequence construction**:
```python
# lstm_predictor.ipynb
seq_length = 60  # Use past 60 days to predict next day
def create_sequences(data, seq_length):
    for i in range(seq_length, len(data)):
        X.append(data[i-seq_length:i, feature_index])  # 60×17 input matrix
        y.append(data[i, target_index])
```

Each training sample is a 60×17 matrix — 60 days of history across 17 features.

**MinMax scaling** (`lstm_predictor.ipynb`):
```python
scaler = MinMaxScaler(feature_range=(0,1))
train_scaled = scaler.fit_transform(train_df)
test_scaled  = scaler.transform(test_df)  # Note: fit on train only, never on test
```

Critical: the scaler is fit **only on training data**. Fitting on the full dataset introduces look-ahead bias.

**Hyperparameter tuning with Keras Tuner** (`lstm_predictor.ipynb`):

```python
# lstm_predictor.ipynb — tunable architecture
def build_model(hp):
    model = Sequential([
        LSTM(units=hp.Int('units_1', 32, 128, step=32), return_sequences=True),
        Dropout(rate=hp.Float('dropout_1', 0.1, 0.5, step=0.1)),
        LSTM(units=hp.Int('units_2', 32, 128, step=32)),
        Dropout(rate=hp.Float('dropout_2', 0.1, 0.5, step=0.1)),
        Dense(1, activation='linear')
    ])
    model.compile(optimizer='adam', loss='mean_squared_error')
    return model

tuner = kt.RandomSearch(build_model, objective='val_loss', max_trials=5)
```

Keras Tuner tries 5 random combinations of LSTM unit counts (32, 64, 96, 128) and dropout rates (0.1 to 0.5). Early stopping prevents overfitting.

**Inverse transformation** for price recovery:
```python
# lstm_predictor.ipynb
def inverse_transform_price(scaled_val):
    dummy = np.zeros((1, len(all_columns)))
    dummy[0, target_index] = scaled_val
    inv = scaler.inverse_transform(dummy)
    return inv[0, target_index]
```

Since the scaler was fit on all columns together, inverse transformation requires placing the scaled prediction back into the correct column position.

### 11.4 What More Can Be Done

- **Attention mechanism**: Add an attention layer that learns which of the 60 past time steps are most important for predicting tomorrow. This makes the model more interpretable.
- **Multi-step forecasting**: Currently predicts only 1 day ahead. Extend to 5-day or 10-day forecasts using encoder-decoder LSTM architecture.
- **Ensemble with ARIMA**: Use LSTM residuals (actual − LSTM prediction) and model them with ARIMA. The combination often outperforms either model alone.

### 11.5 Advanced Concepts

**Overfitting risk**: LSTMs with millions of parameters trained on a few thousand data points will memorise training data. The Dropout layers and EarlyStopping callback in the code mitigate this, but robust validation (cross-validation with multiple time splits) is essential.

**Non-stationarity**: Neural networks assume the input distribution is stationary. Financial data is highly non-stationary (distributions change over market regimes). Walk-forward retraining (retrain every N periods) partially addresses this.

**Data leakage**: The most dangerous pitfall in ML for finance. Any information from the future that leaks into training features will make the model look brilliant in backtests and fail completely in production. The use of `shift(-1)` for the target and proper train/test split in `lstm_predictor.ipynb` shows awareness of this.

**Directionality vs price accuracy**: For trading, a 55% directional accuracy is valuable even if RMSE is high. The notebook tracks both metrics, recognising this distinction.

### 11.6 Advanced Extensions

- Implement **Temporal Fusion Transformer (TFT)**: the current state-of-the-art for multi-horizon time-series forecasting, combining LSTM with self-attention. Significantly outperforms pure LSTM.
- Research **Reinforcement Learning for trading**: instead of predicting prices, train an RL agent to directly maximise risk-adjusted returns through buy/sell/hold actions. The Sharpe ratio becomes the reward signal.
- Add **alternative data**: satellite imagery of company car parks, social media sentiment, web scraping of search trends. These non-price features often have different information content than price-based indicators.

---

## 12. Kalman Filter & OLS Trend Analysis

**Files:** `StrategyRepos/ols_kalman_trend.ipynb`, `StrategyRepos/common_indicators.py`

### 12.1 Basic Introduction

The **Kalman Filter** is an optimal linear state estimator — it combines a noisy measurement (the observed price) with a prediction from a model (the price should evolve smoothly) to produce the best estimate of the "true" underlying price. It continuously updates its estimate as new data arrives.

**Ordinary Least Squares (OLS) rolling regression** fits a linear trend line through a rolling window of prices — the slope tells you the trend direction and magnitude.

### 12.2 What Is the Use of This

- **Kalman Filter**: noise reduction for price signals; smooth out intraday noise to see the underlying trend
- **Rolling OLS**: quantify the strength and significance of a price trend (not just direction); rank stocks by trend strength adjusted for confidence

### 12.3 What Has Been Tried

**Kalman Filter as price smoother** (`common_indicators.py`, `ols_kalman_trend.ipynb`):

```python
# common_indicators.py — simple 1D Kalman filter
kf = KalmanFilter(transition_matrices=[1], observation_matrices=[1],
                  initial_state_mean=df[col_name].iloc[0],
                  initial_state_covariance=df[col_name].var(),
                  observation_covariance=observation_covariance,    # measurement noise
                  transition_covariance=transition_covariance)      # process noise
state_means, _ = kf.filter(df[col_name].values)
```

The ratio `transition_covariance / observation_covariance` controls how much the filter trusts the model vs the observation. Low ratio = trusts observations more = follows price closely. High ratio = trusts model more = heavily smoothed.

**2D Kalman filter with velocity** (`ols_kalman_trend.ipynb`):

```python
# ols_kalman_trend.ipynb — position + velocity state
kf = KalmanFilter(dim_x=2, dim_z=1)
kf.x = np.array([series.iloc[0], 0])  # [position, velocity]
kf.F = np.array([[1, 1], [0, 1]])      # State transition: position += velocity
kf.H = np.array([[1, 0]])              # Observation: we observe position only
```

This 2D filter models price as having both a **level** and a **velocity** (trend). The velocity component naturally captures momentum — if the price has been rising (positive velocity), the filter expects it to continue rising.

**Rolling OLS regression** (`ols_kalman_trend.ipynb`):

```python
# ols_kalman_trend.ipynb
def rolling_regression(series, window=REGRESSION_WINDOW):
    for i in range(window, len(series)):
        y = series.iloc[i-window:i]
        x = np.arange(window)
        x = sm.add_constant(x)
        model = sm.OLS(y, x).fit()
        slopes.append(model.params[1])        # Trend slope
        p_values.append(model.pvalues[1])     # Statistical significance
        t_stats.append(model.tvalues[1])      # t-statistic (slope / standard error)
```

For each 20-day window, fits a linear regression of price vs time. The slope is the average daily price change. The p-value tests whether the slope is statistically significantly different from zero.

**Volatility-adjusted momentum score** (`ols_kalman_trend.ipynb`):

```python
# ols_kalman_trend.ipynb
significant = p_values < SIGNIFICANCE_LEVEL   # Only use statistically significant trends
normalized_slopes = significant_slopes / significant_volatility  # Sharpe-like ratio

# Weight by t-statistic (more confident = more weight)
weights = significant_t_stats[top_n] / significant_t_stats[top_n].sum()
```

This is a rigorous momentum signal: only use trends that are statistically significant (p < 0.05), and rank stocks by slope/volatility (Sharpe-like ratio of trend strength). Position weights are proportional to t-statistics.

**Full pipeline** in `ols_kalman_trend.ipynb`:
1. Fetch Nifty 50 stocks from Yahoo Finance
2. Apply Kalman filter to smooth prices
3. Compute rolling OLS regression (slope, p-value, t-stat, volatility) for each stock
4. Weekly rebalancing: select top 5 stocks by volatility-adjusted slope with significant p-values
5. Evaluate: cumulative return vs Nifty index, Sharpe ratio, max drawdown, beta

### 12.4 What More Can Be Done

- **Kalman filter parameter tuning**: the `observation_covariance` and `transition_covariance` significantly affect smoothing. Tune these using maximum likelihood estimation or cross-validation.
- **Non-linear Kalman (Unscented Kalman Filter)**: stock prices follow non-linear dynamics (log-normal, not linear). UKF handles non-linear state transitions.
- **Piecewise OLS**: instead of a rolling window that discards old data, use a change-point detection algorithm to identify structural breaks and fit OLS on each stationary segment.

### 12.5 Advanced Concepts

**Kalman filter as signal/noise separator**: The Kalman filter's state estimate and its uncertainty (Kalman gain) can be used to measure how much of price movement is "signal" (real trend) vs "noise". High Kalman gain = trusting the measurement more (high noise in model). Low Kalman gain = trusting the model more (high measurement noise).

**OLS vs LASSO for high-dimensional momentum**: When using many features (17 in LSTM notebook), LASSO regression adds an L1 penalty that automatically sets irrelevant feature weights to zero — sparse momentum factors.

**Heteroskedasticity in OLS**: The standard OLS regression assumes constant variance of residuals. Financial returns have GARCH-type variance clustering, which violates this. Weighted Least Squares (WLS) or robust standard errors (HC3) correct for this.

### 12.6 Advanced Extensions

- Implement **Particle Filter**: a non-parametric extension of the Kalman filter that can handle arbitrary non-linear, non-Gaussian dynamics — appropriate for capturing crash dynamics that violate Gaussian assumptions.
- Research **State Space Models with EM**: use Expectation-Maximisation to learn optimal Kalman filter parameters from data, rather than hand-tuning `process_variance` and `measurement_variance`.

---

## 13. Backtesting Framework & Performance Metrics

**Files:** `StrategyRepos/AbsoluteMomentum.ipynb` (cells 7–8), `StrategyRepos/momentumStratPortfolio.py`

### 13.1 Basic Introduction

**Backtesting** is the process of simulating how a trading strategy would have performed historically. It is how quant researchers validate that a strategy has a real edge before risking real capital. A backtest converts historical price data and a set of trading rules into a hypothetical P&L (profit and loss) track record.

### 13.2 What Is the Use of This

Backtesting helps:
1. **Validate the hypothesis**: does the momentum signal actually predict returns?
2. **Estimate returns and risks**: expected CAGR, Sharpe ratio, max drawdown
3. **Identify failure modes**: when does the strategy lose money? (market crashes, momentum crashes)
4. **Parameter sensitivity**: how sensitive are results to the choice of lookback period, number of stocks, etc.

### 13.3 What Has Been Tried

**Portfolio simulation** (`momentumStratPortfolio.py`, `AbsoluteMomentum.ipynb`):

```python
# momentumStratPortfolio.py — core portfolio simulation loop
cashInPortfolio = 1000000   # ₹10 lakh starting capital
portfolioList = []
symbolToPriceDict = {}
symbolPurchasedToQtyDict = {}

for runDate in range(nearest_start_date_index, nearest_end_date_index, forwardValue):
    current_run_date = AllDates[runDate]
    
    # Score and rank all symbols
    symbolDf1 = symbolDf1.sort_values(
        by=['TotalScore', 'Strength', 'FIPScore'], ascending=[False, False, True])
    portfolioSymbolsToAdd = symbolDf1.head(stocksToSelect)['Symbol'].tolist()
    
    # Calculate what to buy and sell
    commonSymbols     = set(portfolioList) & set(portfolioSymbolsToAdd)  # Hold
    symbolsToLiquidate = set(portfolioList) - commonSymbols              # Sell
    symbolsToAdd       = set(portfolioSymbolsToAdd) - commonSymbols      # Buy
    
    # Apply transaction costs
    cashInPortfolio -= cashPerStock * 0.001   # 0.1% commission on each trade
```

**Performance metrics** (`AbsoluteMomentum.ipynb`, cell 7–8):

```python
# AbsoluteMomentum.ipynb
weeklyPortfolioValueDf['Returns'] = weeklyPortfolioValueDf['AccountValue'].pct_change()
weeklyPortfolioValueDf['CumulativeMax'] = weeklyPortfolioValueDf['AccountValue'].cummax()
weeklyPortfolioValueDf['Drawdown'] = (AccountValue - CumulativeMax) / CumulativeMax
weeklyPortfolioValueDf['SharpeRatio'] = CumulativeMeanReturn / CumulativeStdReturn
weeklyPortfolioValueDf['ROMADRatio'] = TotalReturn / abs(Drawdown)
```

**CAGR calculation** (`AbsoluteMomentum.ipynb`, cell 8):
```python
start_val = df['AccountValue'].iloc[0]
end_val   = df['AccountValue'].iloc[-1]
years     = (df.index[-1] - df.index[0]).days / 365.25
cagr      = ((end_val / start_val) ** (1 / years) - 1) * 100
```

**Win/loss analysis**:
```python
positive_weeks = (weekly_returns > 0).sum() / len(weekly_returns) * 100
negative_weeks = (weekly_returns < 0).sum() / len(weekly_returns) * 100
max_drawdown_duration = negative_streaks.max()   # Longest losing streak
```

**Benchmark comparison** (`momentumStratPortfolio.py`):
```python
# Compare strategy vs Nifty 200
nifty200Dataframe = getNifty200PortfolioValues(...)
ss['PortfolioValue'] = initialPortfolioValue * (1 + ss['PctChange']).cumprod()
```

The Nifty 200 (large and mid-cap index) serves as the benchmark. Strategy performance is compared against simply buying and holding the index.

**Stop-loss** (`momentumStratPortfolio.py`, lines 615–622):
```python
stopLossPercentage = 3  # 3% stop loss
# If price drops 3% from purchase price, exit at stop loss price
# (code is present but commented out — experimental)
```

### 13.4 What More Can Be Done

- **Monte Carlo simulation**: instead of a single backtest, run thousands of variations by randomly shuffling trade order or bootstrap-sampling returns. This gives a distribution of possible outcomes, not a single number.
- **Walk-forward optimisation**: divide history into overlapping in-sample/out-of-sample windows. Optimise parameters on in-sample, validate on out-of-sample. Much more honest than single-period backtesting.
- **Multi-benchmark comparison**: Compare against Nifty 50, Nifty 200, NSE Alpha 50, and NSE Momentum 50 indices.

### 13.5 Advanced Concepts

**Survivorship bias**: The current universe is built from option-backed stocks that exist today. Stocks that went bankrupt or were delisted would not be in this universe, making backtest returns look too good.

**Slippage**: The backtest uses last traded price. In reality, your buy order may execute at a price 0.1–0.5% worse (market impact). For 6 stocks with weekly rebalancing, this can add up.

**Backtest overfitting**: The more parameters you test, the higher the chance of finding one that happens to look good on historical data by chance. Statistical techniques like the Bonferroni correction and the False Discovery Rate adjust for multiple testing.

**Key metrics reference:**
- **CAGR**: Compound Annual Growth Rate — annualised geometric return
- **Sharpe Ratio**: (Return − Risk Free Rate) / Volatility — risk-adjusted return per unit of risk
- **Max Drawdown**: Largest peak-to-trough decline — measures tail risk
- **ROMAD**: Return over Maximum Absolute Drawdown — like Sharpe but using drawdown as the risk measure
- **Positive Weeks %**: fraction of periods with positive return — consistency measure

### 13.6 Advanced Extensions

- Implement **Pbo (Probability of Backtest Overfitting)** from Bailey et al. — a rigorous statistical test for whether backtest results are likely to be overfitted.
- Add **Regime-conditional performance analysis**: what is the Sharpe ratio specifically during bear markets, bull markets, high-VIX periods? A robust strategy should show acceptable performance in all regimes.
- Research **Transaction cost modelling** using Almgren-Chriss: models the market impact of your trades as a function of position size relative to average daily volume — particularly important as AUM scales.

---

## 14. Market Universe Construction

**Files:** `MarketUniverse.py`

### 14.1 Basic Introduction

The **investment universe** is the set of assets you consider for investment. Choosing the right universe is crucial:
- Too large: computational burden, more noise, more delistings
- Too small: insufficient diversification, concentration risk
- Wrong selection criteria: survivorship bias, liquidity risk

### 14.2 What Is the Use of This

The market universe defines which stocks the momentum strategy considers at each rebalancing date. Using the wrong universe (e.g., all NSE-listed stocks including illiquid penny stocks) would make backtests meaningless because many apparent "momentum winners" would be impossible to trade in size.

### 14.3 What Has Been Tried

**Option-backed equity universe** (`MarketUniverse.py`):

```python
# MarketUniverse.py
def optionBackedEquityUniverse(self):
    refDataCache = refdata_cache.RefDataCache(None)
    symbolList = refDataCache.get_underlier_lookup_list()
    # Returns stocks that have active F&O (Futures & Options) contracts on NSE
```

This is an elegant filter: NSE only grants options (derivatives) to stocks that meet NSE's minimum liquidity and free-float criteria. Stocks with F&O tend to be:
- Highly liquid (can execute large orders without large slippage)
- Institutionally held (higher quality earnings transparency)
- Well-covered by research analysts (better price discovery)

Approximately 220–250 stocks qualify, covering all major sectors.

**Sector classification** (`MarketUniverse.py`):

```python
# MarketUniverse.py
def classify_stocks_to_sector(self):
    csvFile = pd.read_csv('nifty500.csv')
    csvFile = csvFile[['Symbol', 'Industry']]
    for index, row in csvFile.iterrows():
        equityNameToSectorDict[row['Symbol']] = row['Industry']
    return equityNameToSectorDict
```

Maps each stock to its industry sector from Nifty 500 constituent data. This enables sector-relative analysis and sector rotation strategies.

**NSE API integration** (`MarketUniverse.py`):
```python
def queryNseUrl(self, url):
    baseurl = "https://www.nseindia.com/"
    session = requests.Session()
    # Establishes session with NSE (required for API authentication cookies)
    request = session.get(baseurl, headers=headers, timeout=5)
    cookies = dict(request.cookies)
```

NSE requires cookie-based authentication. The code establishes a browser-like session before calling NSE APIs, with a retry loop (`while count < 3`) for resilience.

### 14.4 What More Can Be Done

- **Point-in-time universe**: Maintain a historical record of which stocks had F&O contracts on each date. If a stock lost its F&O status in 2020, it should not be in the 2018 backtest universe.
- **Liquidity filtering**: Add a minimum Average Daily Volume (ADV) filter. Even among F&O stocks, some are illiquid. A minimum 50 crore ADV filter would further improve universe quality.
- **ESG filters**: Exclude stocks based on Environmental, Social, Governance criteria — increasingly required by institutional investors.

### 14.5 Advanced Concepts

**Nifty 50 vs Nifty 200 vs F&O Universe**: The Nifty 50 is the 50 largest stocks; Nifty 200 adds 150 more; F&O universe ≈ 250 stocks. The F&O universe has better risk-adjusted momentum properties than the Nifty 50 because mid-cap stocks show stronger momentum than large-caps (mid-cap momentum premium).

**Universe rebalancing frequency**: NSE adds/removes stocks from the F&O segment quarterly. Not accounting for these changes in a backtest is a form of survivorship bias.

### 14.6 Advanced Extensions

- Add **global universe expansion**: include Nasdaq 100 and Nikkei stocks via Interactive Brokers API (already partially integrated in the platform). Global cross-sectional momentum has stronger theoretical backing than domestic-only momentum.
- Implement **universe management system**: a database that tracks historical universe composition with effective dates, enabling truly point-in-time backtesting.

---

## Summary: Research Maturity Map

| Topic | File(s) | Stage | Key Strength | Key Gap |
|-------|---------|-------|--------------|---------|
| Data Infrastructure | `Utils.py`, `DataFrameWindowFilter.py` | Production | Robust, handles granularity limits | No incremental update |
| Technical Indicators | `common_indicators.py` | Research | 8 indicator families, signal logic | Not integrated into portfolio loop |
| Core Momentum | `FirstMomentumStrategy.py`, `FirstBtStrategy.py` | Prototype | Framework in place | `next()` method empty |
| EMA Scoring | `AbsoluteMomentum.ipynb`, `momentumStratPortfolio.py` | Advanced Research | 10-condition scoring, grid search | Parameter selection not finalised |
| FIP Value | `momentumStratPortfolio.py` | Innovative | Novel quality filter | Calibration needed |
| Regime Strength | `momentumStratPortfolio.py` | Advanced Research | Dual-regime scoring | Needs walk-forward validation |
| Hurst Exponent | `hurst.ipynb`, `FirstBtStrategy.py` | Research | Good theoretical basis | Strategy switching not implemented |
| ARIMA | `arima.ipynb` | Complete | Walk-forward, hybrid ARIMA-GARCH | Stand-alone, not integrated |
| GARCH | `volatility_modelling.ipynb`, `ms_garch.ipynb` | Research | EGARCH, MS-GARCH, R + Python | Not integrated into position sizing |
| HMM Regimes | `hmm_regime_detection.ipynb` | Research | Multi-feature, BIC tuning | Computationally expensive |
| LSTM | `lstm_predictor.ipynb` | Research | Keras Tuner, dual targets | Overfitting risk, no walk-forward |
| Kalman + OLS | `ols_kalman_trend.ipynb` | Complete | Statistically rigorous | Small universe (Nifty 50 only) |
| Backtesting | `AbsoluteMomentum.ipynb`, `momentumStratPortfolio.py` | Advanced | CAGR, Sharpe, ROMAD vs Nifty200 | Survivorship bias, no slippage model |
| Universe | `MarketUniverse.py` | Production | F&O liquidity filter | Not point-in-time |

---

## Recommended Learning Path

**Week 1–2 (Foundations):**
1. Read `Utils.py` to understand data infrastructure
2. Study SMA/EMA/RSI in `common_indicators.py`
3. Run `FirstMomentumStrategy.py` to download data and generate charts

**Week 3–4 (Core Strategy):**
4. Study the 6-condition EMA scoring in `AbsoluteMomentum.ipynb` (cells 0–6)
5. Understand FIP Value computation
6. Run the backtest and analyse `weeklyPortfolioValueDf` metrics

**Week 5–6 (Statistical Foundations):**
7. Study Hurst Exponent in `hurst.ipynb` — understand stationarity and ADF test
8. Study ARIMA in `arima.ipynb` — understand walk-forward validation

**Week 7–8 (Advanced Models):**
9. Study GARCH in `volatility_modelling.ipynb`
10. Study HMM in `hmm_regime_detection.ipynb`
11. Study LSTM in `lstm_predictor.ipynb`

**Week 9–10 (Integration):**
12. Study Regime Strength classification in `momentumStratPortfolio.py`
13. Study the full portfolio simulation and performance metrics
14. Design and implement a strategy that combines insights from all of the above

---

## 15. Common Gotchas in Quantitative Research

> **The graveyard of quant strategies is not filled with bad ideas — it is filled with good ideas that were tested badly.**  
> Every bias below is a silent killer: your backtest looks great, your Sharpe is high, but the live strategy loses money from day one. Learning to recognise these traps early is the single most valuable skill in quantitative research.

**Files with illustrative examples:** `momentumStratPortfolio.py`, `lstm_predictor.ipynb`, `hmm_regime_detection.ipynb`, `arima.ipynb`, `Utils.py`, `common_indicators.py`

---

### 15.1 Basic Introduction

When you run a backtest and see a Sharpe ratio of 3.5 and a CAGR of 40%, your first instinct is excitement. Your second instinct — once you are properly trained — should be suspicion. Quantitative research is a field where mistakes compound silently. You do not get a compiler error when you look at tomorrow's data today. The code runs, the charts look beautiful, and the numbers are completely fictional.

The gotchas below fall into two families:
- **Data contamination bugs** — the data you feed your model is different from what would have been available at the time of the decision.
- **Statistical validity errors** — the conclusions you draw from your data are not statistically sound, even if the data itself is clean.

Understanding both families is non-negotiable before trusting any backtest result.

---

### 15.2 What Is the Use of This Section

Knowing these pitfalls in advance will:
1. Save you weeks of debugging why a live strategy underperforms its backtest.
2. Let you critically evaluate research papers and other people's backtests.
3. Make your own research trustworthy enough to stake real capital on.
4. Give you a checklist to run through every time you build a new signal or model.

The financial loss from an undetected bias is not hypothetical — funds have blown up because someone's mean-reversion signal was contaminated with look-ahead. The cost of a proper bias audit is a few hours. The cost of not doing one can be catastrophic.

---

### 15.3 The Gotchas — What Goes Wrong and Where

---

#### 15.3.1 Look-Ahead Bias (Forward Data Leakage)

**What it is:** Your signal calculation uses data that would not have been available at the time your strategy would have made a decision.

**Why it is insidious:** Python DataFrames are indexed arrays — all rows are equally accessible at all times. There is no "time boundary" in memory. The code `df['Close'].shift(-1)` gives you *tomorrow's close today*, and nothing stops you from accidentally using it.

**Classic examples:**

1. **Shifted signals without shifted correctly:** In `momentumStratPortfolio.py`, the `lagFactor=3` shift is applied *before* EWM computation specifically to prevent this. Without it, the EWM at time T would incorporate prices that would only be observable after T.

   ```python
   # WRONG — EMA at T sees price at T, used to decide trade at T
   ema_score = df['Close'].ewm(span=span).mean()
   
   # RIGHT — shift price by lagFactor before computing EMA
   ema_score = df['Close'].shift(lagFactor).ewm(span=span).mean()
   ```

2. **`fillna(method='bfill')` — backward fill propagates future data backwards.** If a stock's price is missing on Monday and you back-fill from Tuesday's value, Monday's signal calculation now secretly uses Tuesday's price. `common_indicators.py` uses `bfill` in several places — always verify what the missing values represent before filling them.

3. **Label creation for ML models:** In `lstm_predictor.ipynb`, the target `y` is the *next day's direction*. If you accidentally align `y` with the same row as `X` instead of shifting by 1, your model trains on the answer it is trying to predict — a perfect in-sample fit with zero real predictive power.

4. **Rolling window `apply` without `raw=True` boundary:** Some custom rolling functions inadvertently receive a Series that includes the current row AND future rows if the window is not right-justified. Always validate window edge behaviour on small synthetic data first.

**How to detect it:** If your in-sample Sharpe is above 2.5 and the strategy makes money on *every single year* without exception, be very suspicious. Run the strategy on a truly held-out dataset that was physically separated before any transformation was applied. If performance collapses completely, you likely have leakage.

---

#### 15.3.2 Survivorship Bias

**What it is:** Your backtesting universe only contains stocks that *exist today*, which means it already excludes companies that failed, were delisted, or were acquired. Your backtest therefore tests on a universe that is artificially tilted toward survivors — companies that turned out to do well enough to still be listed.

**Why it matters:** In the Indian market (NSE F&O universe used in `MarketUniverse.py`), the F&O list is periodically revised. Stocks added to the F&O list are typically high-quality, liquid names. Stocks removed are usually under financial distress. If your universe is always "current F&O list", your 2014 backtest is running on 2025's pre-screened survivors — stocks that navigated 11 years of economic cycles successfully.

**Concrete impact:** A momentum strategy tested on the survivor universe can show 15–20% annualised CAGR inflation versus the true-universe result. You are implicitly short all the companies that failed, without paying the cost of those failures.

**What has been tried in this codebase:** The `optionBackedEquityUniverse()` function in `MarketUniverse.py` fetches the *current* F&O list live. This is convenient for live trading but means historical backtests use the present-day universe — survivorship bias is present and not corrected.

**How to fix it:** Maintain a point-in-time universe — a database of which stocks were in the F&O list on each specific historical date. Quandl's Sharadar database (US markets) and Nifty index constituent history files are examples of point-in-time universe data. For research purposes, at minimum document this limitation and discount your backtest CAGR accordingly.

---

#### 15.3.3 Overfitting / Data Snooping Bias

**What it is:** You test hundreds of parameter combinations on the same historical dataset and pick the one that performed best. The "best" configuration is best because it was lucky on that specific history — not because it has genuine predictive power.

**Why it is lethal:** Every parameter search is implicitly an inference from the same data. If you test 500 parameter combinations and pick the top performer, you have done 500 hypothesis tests without applying any multiple-testing correction. At the standard 5% significance level, roughly 25 of those combinations would appear significant purely by chance.

**Concrete examples in this codebase:**

1. **`AbsoluteMomentum.ipynb`** runs a grid search with `ProcessPoolExecutor(max_workers=15)` over combinations of `num_stocks`, `EMA spans`, `VIX percentile filter`, and `window` parameters. Unless the grid is evaluated on a *held-out* test set that was never used during search, the selected parameters are overfit.

2. **`hmm_regime_detection.ipynb`** tunes HMM state count (2–6) and covariance type via BIC — BIC is a penalised likelihood on the same training data, not a true out-of-sample measure. The selected 3-state model should be validated on held-out data before trusting the regime labels.

3. **Reynolds Number thresholds** in `common_indicators.py` are dynamically set at `1.5 × rolling_std`. The multiplier 1.5 is a parameter. If this was tuned via backtest, it is a snooped parameter.

**How to fix it:**
- **Train / Validation / Test split:** Define a test set (e.g., last 2 years) *before* any research begins and do not touch it until final evaluation.
- **Walk-forward optimisation:** Tune parameters on a rolling expanding window, re-optimise every 6–12 months of in-sample data, and evaluate the next period out-of-sample. `arima.ipynb` does this correctly for ARIMA.
- **Bonferroni correction:** If you test N parameter combinations, your effective significance level is α/N. For 500 combinations at α=0.05, only combinations with p < 0.0001 are credibly significant.
- **Deflated Sharpe Ratio (DSR):** Bailey and López de Prado's method adjusts the Sharpe ratio for the number of trials. A Sharpe of 1.5 after 100 trials may have a deflated Sharpe near 0.

---

#### 15.3.4 Transaction Cost Underestimation and Slippage

**What it is:** Your backtest models trading costs as a fixed percentage, but real-world costs include: brokerage, STT (Securities Transaction Tax), exchange charges, slippage (price impact of your own order), and the bid-ask spread.

**What the codebase does:** `momentumStratPortfolio.py` applies a flat 0.1% transaction cost (`transactionCostFactor = 0.001`) on both buys and sells. This is a first-order approximation but misses several real costs:

1. **Slippage** — for a position sized at ₹10L in a stock that trades ₹50L/day, your market order *moves the price against you*. The larger your fund AUM, the worse this gets. A ₹10Cr fund executing weekly rebalance of 20 stocks has market impact that a backtest of this type completely ignores.

2. **Impact of rebalancing frequency** — weekly rebalance as implemented creates 52 rebalance events per year. Each event has both a sell leg (on stocks exiting) and a buy leg (on new entrants). At 0.1% each direction, *each turnover event costs 0.2%*. If 30% of the portfolio turns over each week, annual transaction costs alone exceed 3%.

3. **STT asymmetry** — in India, STT is charged differently on delivery (0.1% on buy+sell), intraday (0.025% on sell only), and F&O. A backtest that ignores this asymmetry mismeasures costs.

4. **Fill assumption** — the backtest assumes you always fill at the weekly open price (`df['Open'].shift(-1)` style). In practice, the open auction can gap significantly from the prior close.

**How to fix it:** Use a realistic transaction cost model:
```
total_cost = brokerage + STT + exchange_fee + SEBI_fee + GST + slippage
```
For Indian equity delivery: ~0.3–0.5% round trip is a more honest estimate for retail. For institutional sizing (>₹1Cr per stock), add a market impact model (e.g., Almgren-Chriss).

---

#### 15.3.5 Normalisation / Scaling Leakage

**What it is:** You fit your data scaler (e.g., `MinMaxScaler`, `StandardScaler`) on the *entire dataset* including the test set, then use that scaler to transform both train and test. The scaler now encodes information from the future (the test set's min and max) into the training data transformation.

**Where this happens in the codebase:** `lstm_predictor.ipynb` explicitly avoids this correctly:
```python
# RIGHT — scaler fitted on train_df only
scaler = MinMaxScaler()
scaler.fit(train_df[feature_columns])
X_train = scaler.transform(train_df[feature_columns])
X_test = scaler.transform(test_df[feature_columns])  # transform only, not fit
```
This is the correct pattern. The common beginner mistake is:
```python
# WRONG — scaler sees the entire dataset including test period
scaler.fit(df[feature_columns])  # leaks future min/max into training
```

**Why it matters for models:** A stock's normalised price of 0.97 means "near its all-time high in the dataset". If the all-time high in your dataset is from 2024 and you are training on 2018 data, the model in 2018 already "knows" the price will eventually reach a 2024 level — information it cannot have in reality. This artificially inflates model accuracy on in-sample evaluation.

**The same principle applies to:** z-score normalisation, PCA (fit on full data), any rolling-window statistic that uses future periods, and even column mean/std if computed globally.

---

#### 15.3.6 Point-in-Time Data Issues

**What it is:** Financial data that *looks* historical is sometimes revised or restated after the fact. The number you see today for "Q2 2023 earnings" may be the *restated* number, not what was actually published on the earnings release date.

**Common variants:**

1. **Earnings data** — companies restate financials. If you download quarterly EPS from a data vendor today, the Q2 2023 figure might reflect a 2024 restatement. Any model trained on this data is looking at future-adjusted information.

2. **Index constituents** — the Nifty 200 as it existed in 2015 is different from the Nifty 200 today. Using today's constituent list to test a 2015 strategy is both survivorship bias and point-in-time error simultaneously.

3. **Corporate actions** — stock splits, bonuses, and dividends change the price series. Most data vendors auto-adjust historical prices for these events retroactively (adjusted close). This is correct for returns calculation but means the raw price you see for 2015 did not exist at that time — it is an artificial number computed backwards from today.

4. **Nifty200.csv parsing** in `momentumStratPortfolio.py` — the benchmark file is a static snapshot. If it is not updated, benchmark comparisons are against a stale universe, making the strategy look relatively better (or worse) than it actually is.

---

#### 15.3.7 Regime Non-Stationarity

**What it is:** A strategy parameter set (EMA span, RSI threshold, etc.) that works in one market regime may be completely wrong in another. The historical period used for parameter optimisation may not resemble the future deployment environment.

**Concrete example:** The EMA scoring system in `momentumStratPortfolio.py` uses spans of approximately `[10, 15, 21, 50]` weeks. These spans were presumably chosen or validated on NSE data from 2014–2024. This 10-year window includes:
- Post-demonetisation shock (2016)
- IL&FS credit crisis (2018)
- COVID crash and V-recovery (2020)
- Post-pandemic bull run (2021–2022)
- Rate hike regime (2022–2023)

Each of these regimes has different autocorrelation structure in price returns. An EMA span optimised on all of them simultaneously is a compromise — it is not optimal for any single regime. When the next regime (e.g., prolonged sideways consolidation) arrives, the strategy may perform poorly.

**How the codebase attempts to address this:** The HMM regime detection (`hmm_regime_detection.ipynb`) and Markov-Switching model (`volatility_modelling.ipynb`) are exactly attempts to detect regime changes and potentially switch strategy parameters. The `classify_strength()` function in `momentumStratPortfolio.py` also uses a dual-regime performance measure to score stocks. However, these are research experiments — the production strategy (`strategy_run()`) does not yet switch parameters based on detected regime.

**The deeper problem:** Regime-switching models themselves suffer from the same overfitting problem — the number of regimes and the transition probabilities are fitted on historical data. If future regimes are structurally different, the model's regime labels may be wrong.

---

#### 15.3.8 Lookahead in Feature Engineering for ML

**What it is:** Any feature that is computed using future information, even indirectly, contaminates ML model training.

**Specific patterns to watch for:**

1. **RSI or MACD computed on the full time series, then split:** If you compute RSI on the entire `df` and then do `train = df.iloc[:split]`, the RSI values in the training set are computed using future prices (because the EWM at any point in the full-series computation is influenced by future observations for the first several periods).

   **Fix:** Compute indicators *after* splitting, or use `min_periods=span` and `adjust=False` in EWM to ensure the computation is causal.

2. **Target variable misalignment:** The target in `lstm_predictor.ipynb` is `df['next_day_direction']`. This column is created by shifting Close by -1. If any preprocessing step (like `dropna()`) is applied globally after this shift, rows at different positions may misalign — causing the model to see tomorrow's direction in today's feature row for certain samples.

3. **Correlation-based feature selection on full data:** If you compute `df.corr()` on the full dataset and select the top 10 features most correlated with returns, you are using the correlation from the *test period* to select features used in the *training period*. This inflates model performance.

---

#### 15.3.9 Backfilling and Forward-Filling Errors

**What it is:** Filling missing values in time series using future data (`bfill`) or blindly propagating stale past data (`ffill`) without understanding the temporal implications.

**`ffill` (forward fill):** Usually safe — it says "use the last known value". The risk is when a stock is halted for days and the stale price is used as if trading is continuing. An indicator computed on a flat-line series during a halt will give meaningless signals.

**`bfill` (backward fill):** Almost always dangerous for time series. It says "use the next known value to fill this gap". This means Monday's value is filled with Tuesday's value — Tuesday's information flows backwards to Monday. Any signal computed on Monday now uses Tuesday's data.

**In `common_indicators.py`:** Several DataFrame operations use `bfill` for cleanup. This is acceptable if the missing values represent genuine data quality issues (e.g., provider gaps) rather than genuine missing observations (e.g., non-trading days). The distinction matters.

---

#### 15.3.10 Multiple Testing Without Correction

**What it is:** Every time you look at a backtest result and decide whether to "keep" or "discard" a signal based on Sharpe or CAGR, you are performing an implicit hypothesis test. Doing this 100 times without adjusting for multiple comparisons guarantees you will find something that looks good purely by chance.

**Why quant research is especially vulnerable:** The research loop is:
1. Hypothesis → backtest → result → adjust hypothesis → backtest again.

Each iteration is a test. Most quant researchers run hundreds of such iterations before landing on a "good" strategy. Without tracking and correcting for this, the final selected strategy has unknown true significance.

**What happens in practice:** A strategy selected from 200 backtests with Sharpe > 1.0 may have a true out-of-sample expected Sharpe near 0.2–0.3, with the observed 1.0 being almost entirely selection bias.

**Partial mitigations used in this codebase:**
- Walk-forward validation in `arima.ipynb` limits overfitting to the rolling window.
- BIC for HMM state selection penalises model complexity.

**Stronger mitigations:**
- **Combinatorial Purged Cross-Validation (CPCV):** López de Prado's method generates many non-overlapping test folds and tracks the distribution of backtest Sharpes. A strategy is credible only if it performs above median across *all* folds, not just the average.
- **False Discovery Rate (FDR) control:** Benjamini-Hochberg correction across all tested signals.
- **Deflated Sharpe Ratio:** Adjusts the observed Sharpe for the number of trials undertaken.

---

#### 15.3.11 Timezone and Market Hours Errors

**What it is:** When mixing data from multiple sources or multiple markets, timezone mismatches can shift price series by one period — which is effectively look-ahead bias of exactly one period.

**Example in the codebase:** `Utils.py` downloads data from Yahoo Finance using `yfinance`. Yahoo Finance returns timestamps in the exchange's local timezone for intraday data (IST for NSE) but sometimes in UTC for daily data. If you compute a signal using data where one ticker is in IST and another is in UTC, the cross-sectional comparison is comparing Monday morning prices against Monday evening prices — a 5.5-hour mismatch on daily data, and catastrophic on intraday data.

**HKD/INR data** from `volatility_modelling.ipynb` is from the forex market which runs 24 hours. Aligning this with NSE equity data (which closes at 15:30 IST) requires careful timestamp matching — using the wrong close can shift the correlation by hours.

**How to catch it:** Always print `df.index[:5]` with timezone information (`df.index.tz`) before aligning two DataFrames. Use `pd.DatetimeIndex.tz_convert()` explicitly rather than assuming alignment.

---

#### 15.3.12 Execution Assumption Errors

**What it is:** The backtest assumes you can always execute at a specific price (usually the open of the next candle after a signal fires). In practice, execution is probabilistic and depends on market conditions.

**Common violations:**

1. **Gap risk:** A weekly signal fires at Friday's close, and the backtest executes at Monday's open. If Monday opens 8% lower due to weekend news, the backtest assumed a fill at Monday's open — but in a gapping market, limit orders may not fill at all, and market orders fill much worse.

2. **Volume constraint:** The backtest buys a position 10x larger than the stock's average daily volume. In reality, you cannot absorb this position without significant market impact.

3. **Simultaneous execution of all rebalance trades:** The strategy model assumes all 20 rebalance trades happen simultaneously at the same price. In practice, executing 20 stocks one by one takes 15–30 minutes, during which prices move.

4. **`rebalancePortfolio()` in `momentumStratPortfolio.py`** sends stock selections to the Bling Trading Platform API. The actual execution price depends on when the API call happens, what orders were placed, and whether the exchange's matching engine fills them — none of which is modelled in the backtest.

---

### 15.4 What More Can Be Done (Applied Bias Audit)

For every strategy you build, create a **bias audit checklist** and run through it before trusting any backtest result:

```
BIAS AUDIT CHECKLIST
=====================
□ Look-ahead bias
  □ Are all signals computed using only data available at signal time?
  □ Are EWM/rolling computations right-justified?
  □ Is the lagFactor shift (or equivalent) applied before any indicator?
  □ Is the target variable correctly shifted by 1 period?

□ Survivorship bias
  □ Is the universe point-in-time or current-only?
  □ If current-only, is the survivorship bias documented and discounted?

□ Overfitting
  □ Was any parameter set using data from the test period?
  □ Was the test set physically separated before any analysis began?
  □ How many trials were run? Is the Deflated Sharpe Ratio acceptable?

□ Transaction costs
  □ Are costs modelled realistically (brokerage + STT + slippage)?
  □ Is turnover measured and its cost accounted for?

□ Scaling leakage
  □ Are all scalers fitted on train only, then applied to test?
  □ Are indicators computed on train-only data before split evaluation?

□ Point-in-time data
  □ Are fundamental data values restated or point-in-time?
  □ Are corporate actions handled consistently?

□ Timezone / alignment
  □ Are all DataFrames in the same timezone before joining?
  □ Are timestamps verified as representing the same market session?

□ Execution assumptions
  □ Is the fill price assumption (open/close/VWAP) realistic?
  □ Is position size constrained by average daily volume?
```

---

### 15.5 Advanced Concepts

**1. Information Leakage in Cross-Validation**

Standard k-fold cross-validation is *invalid* for time series because it allows training on future data relative to the validation fold. The correct approach is **Purged Cross-Validation** (López de Prado, 2018): after defining a validation fold, *purge* all training samples whose labels overlap temporally with the validation period, then add an **embargo** period after each fold to prevent leakage through the autocorrelation of returns.

**2. Backtest Overfitting in the Frequency Domain**

Bailey, Borwein, López de Prado, and Zhu (2014) showed that the probability of backtest overfitting is a function of the number of trials and the ratio of in-sample to out-of-sample performance. Their **Probability of Backtest Overfitting (PBO)** metric uses combinatorial cross-validation across many sub-periods to estimate the probability that the selected strategy performs above median purely by chance. A PBO > 50% means the strategy selection is no better than random.

**3. Structural Break Testing**

The Chow test, CUSUM test, and Bai-Perron multiple breakpoint test can detect when the parameters of a model (e.g., OLS regression slope in `ols_kalman_trend.ipynb`) changed permanently. If the OLS slope from 2014–2018 is statistically different from 2019–2024, your strategy parameters are non-stationary and should not be optimised on the pooled period.

**4. Transaction Cost-Aware Signal Optimisation**

Grinold and Kahn's **Fundamental Law of Active Management** states:
```
IR ≈ IC × √BR
```
where IR = Information Ratio, IC = Information Coefficient (correlation of signal with future returns), BR = Breadth (number of independent bets per year). Transaction costs reduce effective IC — a signal with IC=0.05 and 20bps round-trip cost may have an *effective* IC of 0.01 after costs. Strategies should be optimised on net-of-cost IR, not gross IR.

**5. Regime Conditioned Bias Detection**

A strategy may appear unbiased on average but be severely biased within specific regimes. For example, a momentum strategy's look-ahead bias may be more severe during high-volatility regimes (because prices move more between signal generation and execution). Regime-conditioned residual analysis (plotting signal error vs. HMM regime label) can detect this.

---

### 15.6 What More Can Be Done (Advanced Extensions)

1. **Build an automated bias detector** — a Python class that wraps any signal-generation function and validates: (a) no column is shifted forward, (b) all rolling windows are right-justified, (c) the output at time T is identical regardless of what data exists after time T (i.e., simulate computing the signal in a live environment at each historical timestamp).

2. **Implement López de Prado's CPCV** (`mlfinance` library) as a standard cross-validation wrapper for all strategy parameter searches — replace the current grid-search in `AbsoluteMomentum.ipynb` with CPCV to get honest out-of-sample Sharpe distribution estimates.

3. **Point-in-time universe database** — maintain a SQLite table with `(date, symbol, in_fo_list: bool)` records, updated each time the F&O list changes. Replace `optionBackedEquityUniverse()` in `MarketUniverse.py` to accept a `as_of_date` parameter and query this table.

4. **Realistic execution simulation** — integrate the backtest in `momentumStratPortfolio.py` with a VWAP-based fill model: assume execution happens over the first 30 minutes of the trading day, at a price that is a volume-weighted average of 1-minute bars, subject to a maximum fill of 10% of that period's volume.

5. **Slippage calibration from live vs backtest divergence** — once live trading begins via `rebalancePortfolio()`, compare the actual execution prices against the model's assumed fill prices. The divergence distribution is your empirical slippage model. Feed it back into the backtest to get realistic net performance.

6. **Information Coefficient decay analysis** — for each signal in `common_indicators.py` (RSI, Reynolds Number, EMA score, FIP Value), compute the IC at lag 1, 2, 5, 10, 20 days. A signal whose IC decays to zero by day 3 should only be traded with a 1–2 day holding period; trading it weekly wastes most of its predictive power.

---

### Recommended Further Reading

| Topic | Resource |
|---|---|
| Look-ahead and all biases | *Advances in Financial Machine Learning* — Marcos López de Prado, Chapter 11 |
| Backtest overfitting | *The Deflated Sharpe Ratio* — Bailey & López de Prado (2014) |
| Transaction costs | *Algorithmic Trading* — Ernie Chan, Chapters 3–4 |
| Point-in-time data | *Quantitative Equity Portfolio Management* — Chincarini & Kim |
| Multiple testing | *Evaluating Trading Strategies* — Harvey, Liu & Zhu (2016) |
| Execution modelling | *Optimal Execution of Portfolio Transactions* — Almgren & Chriss (2000) |
| Walk-forward validation | *Machine Learning for Asset Managers* — López de Prado, Chapter 6 |

