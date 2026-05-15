
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pmdarima import auto_arima
from statsmodels.tsa.statespace.sarimax import SARIMAX
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import StandardScaler
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
import pandas_ta as ta
from pykalman import KalmanFilter

BUY = 1
SELL = 0
HOLD = 0
STRONG_BUY = 1
STRONG_SELL = 0

# =================================================================
# 1. SMA & EMA Signals
# =================================================================
def sma_ema_signals(df, col_name='Ref_Price'):
    df['SMA_10'] = df[col_name].rolling(10).mean()
    df['SMA_20'] = df[col_name].rolling(20).mean()
    df['SMA_100'] = df[col_name].rolling(100).mean()
    
    df['EMA_10'] = df[col_name].ewm(span=10, adjust=False).mean()
    df['EMA_20'] = df[col_name].ewm(span=20, adjust=False).mean()
    df['EMA_50'] = df[col_name].ewm(span=50, adjust=False).mean()
    
    # SMA Buy when Ref_Price price is 1% above SMA_10 and Sell when 1% below SMA_10 else Hold
    conditions_sma = [
        df[col_name] > df['SMA_10'] * 1.01,
        df[col_name] < df['SMA_10'] * 0.99
    ]
    choices = [BUY, SELL]
    df['SMA_Signal_1'] = np.select(conditions_sma, choices, default=HOLD)
    
    # Price above 20 & 100 SMA -> Strong Buy
    # Price below 20 & 100 SMA -> Strong Sell
    conditions_sma_strong = [
        (df[col_name] > df['SMA_20']) & (df[col_name] > df['SMA_100']),
        (df[col_name] < df['SMA_20']) & (df[col_name] < df['SMA_100'])
    ]
    choices_strong = [STRONG_BUY, STRONG_SELL]
    df['SMA_Signal_2'] = np.select(conditions_sma_strong, choices_strong, default=HOLD)
    
    # EMA Buy when Ref_Price price is 1% above EMA_10 and Sell when 1% below EMA_10 else Hold
    conditions_ema = [
        df[col_name] > df['EMA_10'] * 1.01,
        df[col_name] < df['EMA_10'] * 0.99
    ]
    df['EMA_Signal_1'] = np.select(conditions_ema, choices, default=HOLD)
    
    # Price above 20 & 50 EMA -> Strong Buy
    # Price below 20 & 50 EMA -> Strong Sell
    conditions_ema_strong = [
        (df[col_name] > df['EMA_20']) & (df[col_name] > df['EMA_50']),
        (df[col_name] < df['EMA_20']) & (df[col_name] < df['EMA_50'])
    ]
    df['EMA_Signal_2'] = np.select(conditions_ema_strong, choices_strong, default=HOLD)
    return df

# =================================================================
# 2. RSI Signals
# =================================================================
def rsi_signals(df, col_name='Ref_Price'):
    df['RSI'] = ta.rsi(df[col_name], length=14)
    
    # Signals
    df['RSI_Signal'] = np.select(
        [
            (df['RSI'] < 30) & (df['RSI'].shift(1) < 30),  # Strong Buy
            (df['RSI'] > 70) & (df['RSI'].shift(1) > 70),  # Strong Sell
            (df['RSI'] > 30) & (df['RSI'].shift(1) <= 30),  # Buy
            (df['RSI'] < 70) & (df['RSI'].shift(1) >= 70),  # Sell
        ],
        [STRONG_BUY, STRONG_SELL, BUY, SELL],
        default=HOLD
    )
    return df

# =================================================================
# 3. MACD Signals
# =================================================================
def macd_signals(df, col_name='Ref_Price'):
    exp12 = df[col_name].ewm(span=12, adjust=False).mean()
    exp26 = df[col_name].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp12 - exp26
    df['MACD_Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # Signals
    df['MACD_Signal'] = np.select(
        [
            (df['MACD'] > df['MACD_Signal_Line']) & (df['MACD'].shift(1) < df['MACD_Signal_Line'].shift(1)) & (df['MACD'] < 0),  # Strong Buy
            (df['MACD'] < df['MACD_Signal_Line']) & (df['MACD'].shift(1) > df['MACD_Signal_Line'].shift(1)) & (df['MACD'] > 0),  # Strong Sell
            (df['MACD'] > df['MACD_Signal_Line']),  # Buy
            (df['MACD'] < df['MACD_Signal_Line']),  # Sell
        ],
        [STRONG_BUY, STRONG_SELL, BUY, SELL],
        default=HOLD
    )
    return df

# =================================================================
# 4. Stochastic Signals
# =================================================================
def stochastic_signals(df, k_window=14, d_window=3, col_name='Ref_Price'):
    """
    Calculates Stochastic %K and %D and generates Buy/Sell signals.

    Parameters:
    df (DataFrame): Stock price data with 'High', 'Low', 'Ref_Price' columns.
    k_window (int): Lookback period for %K (default = 14).
    d_window (int): Smoothing period for %D (default = 3).

    Returns:
    DataFrame: Updated DataFrame with %K, %D, and 'Stochastic_Signal'.
    """
    # Stochastic %K and %D Calculation
    df['Low_Min'] = df['Low'].rolling(k_window).min()
    df['High_Max'] = df['High'].rolling(k_window).max()
    
    df['%K'] = 100 * ((df[col_name] - df['Low_Min']) / (df['High_Max'] - df['Low_Min']))
    df['%D'] = df['%K'].rolling(d_window).mean()

    # Store Previous Values to Detect Crossovers
    df['%K_Previous'] = df['%K'].shift(1)
    df['%D_Previous'] = df['%D'].shift(1)

    # Generate Signals
    df['Stochastic_Signal'] = np.select(
        [
            # Strong Buy: %K crosses above %D while below 20
            (df['%K'] > df['%D']) & (df['%K_Previous'] < df['%D_Previous']) & (df['%K'] < 20),

            # Strong Sell: %K crosses below %D while above 80
            (df['%K'] < df['%D']) & (df['%K_Previous'] > df['%D_Previous']) & (df['%K'] > 80),

            # Buy: %K crosses above 20 from below
            (df['%K_Previous'] < 20) & (df['%K'] > 20),

            # Sell: %K crosses below 80 from above
            (df['%K_Previous'] > 80) & (df['%K'] < 80),
        ],
        [STRONG_BUY, STRONG_SELL, BUY, SELL],
        default=HOLD
    )

    # Drop Temporary Columns
    df.drop(columns=['Low_Min', 'High_Max'], inplace=True)
    return df

# =================================================================
# 5. SMI Signals
# =================================================================
def smi_signals(df, window=14, smoothing=3, epsilon=np.finfo(float).eps, col_name='Ref_Price'):
    """
    Calculates Stochastic Momentum Index (SMI) and generates Buy/Sell signals.

    Parameters:
    df (DataFrame): Stock price data with 'High', 'Low', 'Ref_Price' columns.
    window (int): Lookback period for highest high and lowest low (default = 14).
    smoothing (int): EMA smoothing factor (default = 3).
    epsilon (float): Small constant to prevent division by zero

    Returns:
    DataFrame: Updated DataFrame with 'SMI' and 'SMI_Signal' columns.
    """
    # Compute High-Low Range and Median Price
    high_max = df['High'].rolling(window=window).max()
    low_min = df['Low'].rolling(window=window).min()
    median_price = (high_max + low_min) / 2
    
    # Standard SMI Calculation with Double EMA Smoothing
    diff = df[col_name] - median_price
    ema1 = diff.ewm(span=smoothing, adjust=False).mean()
    ema2 = ema1.ewm(span=smoothing, adjust=False).mean()
    
    hl_diff_ema = (high_max - low_min).ewm(span=smoothing, adjust=False).mean()
    
    df['SMI'] = 100 * ema2 / (0.5 * hl_diff_ema + epsilon)

    # Store Previous SMI Values to Detect Crossovers
    df['SMI_Previous'] = df['SMI'].shift(1)

    # Generate Buy/Sell Signals (Corrected Priority Order)
    df['SMI_Signal'] = np.select(
        [
            # Strong Buy: SMI crosses above -40 after being below it
            (df['SMI'] > -40) & (df['SMI_Previous'] <= -40),

            # Strong Sell: SMI crosses below 40 after being above it
            (df['SMI'] < 40) & (df['SMI_Previous'] >= 40),

            # Sell: SMI crosses below 0 (bearish momentum shift)
            (df['SMI'] < 0) & (df['SMI_Previous'] >= 0),

            # Buy: SMI crosses above 0 (bullish momentum shift)
            (df['SMI'] > 0) & (df['SMI_Previous'] <= 0),
        ],
        [STRONG_BUY, STRONG_SELL, SELL, BUY],  # Strongest signals first
        default=HOLD
    )

    # Drop Temporary Column
    # df.drop(columns=['SMI_Previous'], inplace=True)
    return df

# =================================================================
# 6. RVI Signals
# =================================================================
def rvi_signals(df, window=14, smoothing=3, col_name='Ref_Price'):
    """
    Calculates Relative Volatility Index (RVI) and generates Buy/Sell signals.

    Parameters:
    df (DataFrame): Stock price data with 'Ref_Price' column.
    window (int): Lookback period for RVI (default = 14).
    smoothing (int): EMA smoothing factor (default = 3).
    
    Signal Thresholds:
        - Strong Buy: Sustained move above 40 (oversold recovery)
        - Strong Sell: Sustained move below 60 (overbought rejection) 
        - Buy/Sell: Trend confirmation at 50 centerline

    Returns:
    DataFrame: Updated DataFrame with 'RVI' and 'RVI_Signal' columns.
    """

    # Input Validation
    if 'Ref_Price' not in df.columns:
        raise ValueError("DataFrame must contain 'Ref_Price' column")
    if len(df) < window:
        raise ValueError(f"DataFrame must have at least {window} rows")

    # Standard RVI calculation
    delta = df[col_name].diff().fillna(0)  # Prevents NaNs in first row

    up_vol = delta.where(delta > 0, 0).rolling(window).std()
    down_vol = delta.where(delta < 0, 0).abs().rolling(window).std()

    avg_up = up_vol.ewm(span=smoothing, adjust=False).mean()
    avg_down = down_vol.ewm(span=smoothing, adjust=False).mean()

    # Safe division
    denominator = (avg_up + avg_down).replace(0, 1e-9)
    df['RVI'] = 100 * avg_up / denominator

    # Store Previous RVI Values to Detect Crossovers
    df['RVI_Prev'] = df['RVI'].shift(1)
    df['RVI_Prev_Prev'] = df['RVI'].shift(2)

    # Signal Generation (Improved Prioritization)
    df['RVI_Signal'] = np.select(
        [
            # Strong Buy: RVI crosses above 40 after being below it for 2+ periods
            (df['RVI'] > 40) & (df['RVI_Prev'] <= 40) & (df['RVI_Prev_Prev'] <= 40),

            # Strong Sell: RVI crosses below 60 after being above it for 2+ periods
            (df['RVI'] < 60) & (df['RVI_Prev'] >= 60) & (df['RVI_Prev_Prev'] >= 60),

            # Buy: RVI crosses above 50 (bullish momentum confirmation)
            (df['RVI'] > 50) & (df['RVI_Prev'] <= 50),

            # Sell: RVI crosses below 50 (bearish momentum confirmation)
            (df['RVI'] < 50) & (df['RVI_Prev'] >= 50),
        ],
        [STRONG_BUY, STRONG_SELL, BUY, SELL],  # Prioritized for strong signals first
        default=HOLD
    )

    return df

# =================================================================
# 7. EMV Signals
# =================================================================
def emv_signals(df, window=14, vol_adjustment=1e6):
    """
    Calculates Ease of Movement (EMV) with signal thresholds.
    
    Parameters:
    df (DataFrame): OHLCV data with 'High', 'Low', 'Ref_Price', 'Volume'
    window (int): Smoothing period (default=14)
    vol_adjustment (float): Volume scaling factor (default=1e6)
    
    Signals:
    - Strong Buy: EMV > 0.3
    - Buy: EMV crosses above 0
    - Strong Sell: EMV < -0.3
    - Sell: EMV crosses below 0
    """
    # Input validation
    req_cols = {'High', 'Low', 'Ref_Price', 'Volume'}
    if not req_cols.issubset(df.columns):
        missing = req_cols - set(df.columns)
        raise ValueError(f"Missing columns: {missing}")
    
    # EMV Calculation
    df['Midpoint'] = (df['High'] + df['Low']) / 2
    df['Distance'] = df['Midpoint'].diff().fillna(method='bfill').fillna(0)  
    
    # Volume-adjusted Box Ratio
    df['Box_Ratio'] = (df['High'] - df['Low']) / (df['Volume'] / vol_adjustment)
    df['Box_Ratio'] = df['Box_Ratio'].replace(0, np.nan).ffill()  # Handle zero division
    
    # EMV Formula and smoothing
    df['EMV'] = (df['Distance'] / df['Box_Ratio']).rolling(window).mean()
    
    # Signal Generation
    df['EMV_Prev'] = df['EMV'].shift(1)
    df['EMV_Signal'] = np.select(
        [
            (df['EMV'] > 0.3),
            (df['EMV'] < -0.3),
            (df['EMV'] > 0) & (df['EMV_Prev'] <= 0),
            (df['EMV'] < 0) & (df['EMV_Prev'] >= 0)
        ],
        [STRONG_BUY, STRONG_SELL, BUY, SELL],
        default=HOLD
    )
    
    return df.drop(columns=['Midpoint', 'Distance', 'Box_Ratio'])

# =================================================================
# 8. Reynolds Signals
# =================================================================
def reynolds_signals(df, rvi_col='RVI', emv_col='EMV', window=21):
    """
    Calculates Reynolds Number (RN) with adaptive thresholds.
    
    Parameters:
    df (DataFrame): Must contain RVI and EMV columns
    window (int): Lookback for dynamic threshold calculation
    
    Signals:
    - Buy: RN > 1 standard deviation
    - Sell: RN < -1 standard deviation
    """
    # Input validation
    if not {rvi_col, emv_col}.issubset(df.columns):
        raise ValueError("Missing RVI or EMV columns")
    
    # RN Calculation with error handling
    df['RN'] = df[rvi_col] / df[emv_col].replace(0, np.nan)
    df['RN'] = df['RN'].replace([np.inf, -np.inf], np.nan).ffill()
    df['RN'] = df['RN'].ewm(span=5, adjust=False).mean()
    
    # Dynamic threshold calculation
    rolling_std = df['RN'].rolling(window).std()
    df['RN_Upper'] = rolling_std * 1.5
    df['RN_Lower'] = -rolling_std * 1.5
    
    min_threshold = 0.7 * rolling_std.mean()  # Prevent over-sensitivity in low volatility
    df['RN_Upper'] = np.maximum(df['RN_Upper'], min_threshold)
    df['RN_Lower'] = np.minimum(df['RN_Lower'], -min_threshold)
    
    # Signal Generation
    df['RN_Signal'] = np.select(
        [
            df['RN'] > df['RN_Upper'],
            df['RN'] < df['RN_Lower'],
            df['RN'] > 0,
            df['RN'] < 0
        ],
        [STRONG_BUY, STRONG_SELL, BUY, SELL],
        default=HOLD
    )
    
    return df

def next_day_open_direction(df):
    conditions = [
        df['Open'].shift(-1) > df['Close'] * 1.0025,
        df['Open'].shift(-1) < df['Close'] * 0.9975
    ]
    choices = [1, -1]
    df['Open_Direction'] = np.select(conditions, choices, default=HOLD)
    return df

def count_last_n_days(df, n=5):
    df['Up_Days'] = df['Close'].diff().gt(0).rolling(n).sum()
    df['Down_Days'] = df['Close'].diff().lt(0).rolling(n).sum()
    return df

def get_kalman_filter_price(df, col_name='Ref_Price', observation_covariance=1, transition_covariance=0.05):
    # Configure the Kalman Filter with a simple random walk model.
    kf = KalmanFilter(
        transition_matrices=[1],
        observation_matrices=[1],
        initial_state_mean=df[col_name].iloc[0],
        initial_state_covariance=df[col_name].var(),
        observation_covariance=observation_covariance,
        transition_covariance=transition_covariance
    )

    # Use kf.filter() for causal filtering.
    state_means, _ = kf.filter(df[col_name].values)
    filtered_prices = pd.Series(state_means.flatten(), index=df[col_name].index)

    # Plot the original close prices and the Kalman filter estimates.
    plt.figure(figsize=(12, 6))
    plt.plot(df[col_name], label="Original Close Price")
    plt.plot(filtered_prices, label="Kalman Filtered Price", linewidth=2)
    plt.title("Reference Price vs. Kalman Filtered Price")
    plt.xlabel("Date")
    plt.ylabel("Price")
    plt.legend()
    plt.show()

    # Display a few sample values.
    result = pd.DataFrame({
        "Original": df[col_name],
        "Filtered": filtered_prices
    })
    print(result.head(10))

    df[col_name] = result["Filtered"]    
    return df