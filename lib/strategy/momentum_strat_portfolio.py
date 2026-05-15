import sys
sys.path.append('/home/qa/BlingTradePlatform/strategy/MomentumLearning/')
from lib.data import utils as Utils
import pandas as pd
import yfinance as yf
import requests
import json
from typing import Tuple, Dict
import os
from lib.data.market_universe import MarketUniverse
from lib.signals.indicator_calculator import IndicatorAdder
from lib.data.dataframe_window_filter import DataWindowFilter
import mplfinance as mpf
import plotly.graph_objects as go
from bokeh.plotting import figure, show
from bokeh.models import ColumnDataSource
from bokeh.io import output_file
from plotly.subplots import make_subplots
import sys
from backtesting import Backtest
from src.common.constants import *
from lib.strategy.first_bt_strategy import SmaCross
from itertools import product
from concurrent.futures import ProcessPoolExecutor
import argparse
import pycurl
import certifi
import shutil
import sys
import os
import requests
import csv
import time
import json
import datetime
import numpy as np
from datetime import datetime, timedelta
import subprocess

from fastapi import FastAPI, Request, HTTPException, APIRouter
from fastapi.responses import JSONResponse
import os
import sys
import logging
import re
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/../../')
from src.common.constants import *
from src.common.json_file_reader import *
from src.gui.swagger_ui.external_api.credential_helper import read_session_info_from_file
import datetime

router = APIRouter()
import asyncio

portfolio_value_lock = asyncio.Lock()

portfolioId = "14"
strategyId = "1"
blingToken = "g4CjqsMDK-lfxwG"

# Modify the program to accept portfolioId, strategyId, and blingToken as command-line arguments

# Set up argument parser
# parser = argparse.ArgumentParser(description="Momentum Strategy Script")
# parser.add_argument("--portfolioId", type=str, required=True, help="Portfolio ID")
# parser.add_argument("--strategyId", type=str, required=True, help="Strategy ID")
# parser.add_argument("--blingToken", type=str, required=True, help="Bling Token")

# # Parse the arguments
# args = parser.parse_args()

# # Assign the parsed arguments to variables
# portfolioId = args.portfolioId
# strategyId = args.strategyId
# blingToken = args.blingToken


class MomentumStrategy:
    def __init__(self) -> None:
        self.symboluniverse = MarketUniverse()
        self.indicatorCalculator = IndicatorAdder()
        self.dataframewindowfilter = DataWindowFilter
        
granularity = "1d"
# #periodInString = "28d"
# start_date_to_download = '2024-12-30'
# end_date_to_download = '2025-04-25'
# filter_start_date = '2024-01-01'
# filter_end_date = '2024-09-29'
# filter_start_time = '09:20::00'
# filter_end_time  = '15:30:00'
# STRATEGY_TYPE = SmaCross
# candleDownloadChart = False
CSV_FILE_PATH = GlobalConstants.historicMarketData_csv_dir
# if __name__ == "__main__":
strategy = MomentumStrategy()
current_date = Utils.get_current_date()
previous_date = Utils.calculate_dates(current_date, 1, 1)['past_date']

symbolListDataframe = strategy.symboluniverse.optionBackedEquityUniverse()
#symbolToSectorDict = strategy.symboluniverse.classify_stocks_to_sector()
#symbolListDataframe['Sector'] = symbolListDataframe['Symbol'].apply(lambda x :  symbolToSectorDict[x] if symbolToSectorDict.get(x) else "Others")
dirname = GlobalConstants.historicMarketData_dir
Utils.createDirectory(dirname)
Utils.save_df_to_csv(symbolListDataframe, dirname, 'equitySchema.csv')

def getNifty200PortfolioValues(first_date, last_date, all_dates, filterTypeDays):
    def convert_volume(val):
        if pd.isna(val):
            return None
        val = val.strip()
        multiplier = 1
        if val.endswith('K'):
            multiplier = 1_000
            val = val[:-1]
        elif val.endswith('M'):
            multiplier = 1_000_000
            val = val[:-1]
        elif val.endswith('B'):
            multiplier = 1_000_000_000
            val = val[:-1]
        try:
            return int(float(val.replace(',', '')) * multiplier)
        except ValueError:
            return None
    nifty200csv = pd.read_csv(GlobalConstants.historicMarketData_dir + 'Nifty200.csv')
    nifty200csv = Utils.convert_yf_datetime_to_pandas_datetime(nifty200csv)
    
    # Convert Price, Open, High, Low to float
    cols_to_float = ['Price', 'Open', 'High', 'Low']
    for col in cols_to_float:
        nifty200csv[col] = nifty200csv[col].str.replace(',', '').astype(float)
    # Convert Vol. to numeric
    nifty200csv['Volume'] = nifty200csv['Vol.'].apply(convert_volume)
    # Convert 'Date' column from datetime64[ns]  to object format which is JSON serializable
    nifty200csv['Date'] = nifty200csv['Date'].dt.strftime('%Y-%m-%d')

    # Convert Change % to float
    nifty200csv['Change %'] = nifty200csv['Change %'].str.replace('%', '').str.replace(',', '').astype(float)

    nifty200csv = Utils.filter_pands_df_column_filter_on_conditionlist(nifty200csv, 'Date', all_dates)
    return nifty200csv

def geometric_mean(x):
    return x.mean()
def classify_strength_alternate(row):
    cr = row['CloseCR']
    cr_opp = row['CloseOppositeCR']
    bench = row['BenchmarkCR']                 # < 0
    bench_opp = row['BenchmarkOppositeCR']     # > 0

    # === Strongest case: Symbol rises in down, and outperforms in up
    if cr > 0 and cr_opp > bench_opp:
        return 100

    # Rises in fall, performs ok in rise
    elif cr > 0 and cr_opp < bench_opp:
        return 90

    # Rises in fall, matches market in rise
    elif cr > 0 and cr_opp == bench_opp:
        return 70

    # Falls less in fall, outperforms in rise
    elif cr > bench and cr_opp > bench_opp:
        return 80

    # Falls less in fall, mild rise
    elif cr > bench and cr_opp < bench_opp:
        return 60

    # Falls less in fall, equal rise
    elif cr > bench and cr_opp == bench_opp:
        return 50

    # Matches fall, strong rise
    elif cr == bench and cr_opp > bench_opp:
        return 65
    
    # Matches fall, matches rise
    elif cr == bench and cr_opp == bench_opp:
        return 45

    # Matches fall, weaker rise
    elif cr == bench and cr_opp < bench_opp:
        return 40

    # Falls more than market, strong upside
    elif cr < bench and cr_opp > bench_opp:
        return 55
    
    # Falls more, weak rise
    elif cr < bench and cr_opp < bench_opp:
        return 30

    # Falls more, but rises stronger
    elif cr < bench and cr_opp > 0:
        return 50

    # Falls in fall, and falls again in rise
    elif cr < 0 and bench < 0 and cr_opp < 0 and bench_opp > 0:
        return 10

    # Catch-all
    else:
        return 0
    
def classify_strength(row):
    cr = row['CloseCR']
    cr_opp = row['CloseOppositeCR']
    bench = row['BenchmarkCR']
    bench_opp = row['BenchmarkOppositeCR']

    # Market goes up (BenchmarkCR > 0)
    # Market goes down (BenchmarkOppositeCR < 0)

    # === Strongest case: beats both regimes ===
    if cr > bench and cr_opp > 0:
        return 100

    # Strong upside, but falls less than market
    elif cr > bench and cr_opp > bench_opp:
        return 90

    # Strong upside, but matches market in fall
    elif cr > bench and cr_opp == bench_opp:
        return 80

    # Strong upside, but worse fall
    elif cr > bench and cr_opp < bench_opp:
        return 50

    # Neutral upside, rises in fall
    elif cr == bench and cr_opp > 0:
        return 45

    # Neutral upside, better downside protection
    elif cr == bench and cr_opp > bench_opp:
        return 40

    # Neutral upside, equal downside
    elif cr == bench and cr_opp == bench_opp:
        return 35

    # Neutral upside, worse downside
    elif cr == bench and cr_opp < bench_opp:
        return 20

    # Underperforming upside, but rises in fall
    elif cr < bench and cr_opp > 0:
        return 15

    # Underperforming upside, mild downside
    elif cr < bench and cr_opp > bench_opp:
        return 10

    # Underperforming both sides
    elif cr < bench and cr_opp < bench_opp:
        return 0

    # Falls in up market (bad), falls in down market (bad)
    elif cr < 0 and bench > 0 and cr_opp < 0 and bench_opp < 0:
        return -10

    # Falls in rally, but rises in crash
    elif cr < 0 and bench > 0 and cr_opp > 0:
        return -5

    # Catch-all fallback
    else:
        return 0

def dynamic_strength_label(row):
    if row['BenchmarkCR'] == None or row['BenchmarkOppositeCR'] == None:
        return -10
    elif row['BenchmarkCR'] > 0 and row['BenchmarkOppositeCR'] < 0:
        return classify_strength(row)
    elif row['BenchmarkCR'] < 0 and row['BenchmarkOppositeCR'] > 0:
        return classify_strength_alternate(row)

    
symbolList = Utils.panda_series_toList_converter(symbolListDataframe['Symbol'])
start_date_to_read= '2014-01-01'
end_date_to_read = '2025-05-23'
symbolToDataframeDict = {}
#end_date_to_read = Utils.get_current_date()

# the weeklyPortfolioDateToValueDf should be able to change its value inside the strategy_run function
# which can be retrieved later to send to the Bling Trading Platform
weeklyPortfolioDateToValueDf = pd.DataFrame(columns=['Date', 'AccountValue'])
def strategy_run(symbolList, granularity, start_date_to_read, end_date_to_read, weeklyPortfolioDateToValueDf):
    print("-----------------")
    filterTypeDays =6
    lagFactor = 3
    symbolCount = 0
    stocksToSelect = 6
    allSymbologyDataFrame = []
    symbolNameToSymbolDataframeDict = {}
    spanList = [int(60 // filterTypeDays),  int(90 // filterTypeDays), int(126 // filterTypeDays), int(300 // filterTypeDays)]
    moveToShiftForReturn = int(120 // filterTypeDays)
    FIPWindowSpan = int (240 // filterTypeDays)
    stopLossPercentage = 3
    regimeLookBackValue = (6 // filterTypeDays)
    
    print(spanList)
    #Utils.download_Mkt_Data_For_Symbols_Without_Start_And_EndDate_With_Granularity_And_SaveFilesToDirectory(symbolList, granularity, GlobalConstants.historicMarketData_dir, ".csv")
    for symbol in symbolList:
        symbolCount += 1
        print(symbol)
        symbolDataframe = Utils.readCsv_from_startdate_enddate(symbol, granularity, start_date_to_read, end_date_to_read, dirname, ".csv")

        if symbolDataframe.empty:
            continue
        
        AllDataFrame = symbolDataframe.copy()
        AllDataFrame = Utils.convert_yf_datetime_to_pandas_datetime(AllDataFrame)
        AllDataFrame['StrDate'] = AllDataFrame['Date'].dt.strftime('%Y-%m-%d')
        symbolNameToSymbolDataframeDict[symbol] = AllDataFrame

        symbolDataframe = Utils.filter_dataframe_by_days(symbolDataframe, filterTypeDays)

        if symbolDataframe.empty:
            continue
        
        symbolDataframe = Utils.convert_yf_datetime_to_pandas_datetime(symbolDataframe)
        symbolDataframe['StrDate'] = symbolDataframe['Date'].dt.strftime('%Y-%m-%d')
        #print(symbolDataframe['StrDate'].to_list())
        nifty200Dataframe = getNifty200PortfolioValues(start_date_to_read, end_date_to_read, symbolDataframe['StrDate'].to_list(), filterTypeDays)
        
        Utils.convert_datetime64_to_user_format(symbolDataframe['Date'], '%d-%m-%Y %H:%M:%S')
        
        symbolDataframe['Time'] = Utils.convert_datetime64_to_user_format(symbolDataframe['Date'], '%H:%M:%S')
        symbolDataframe['Date1'] = pd.to_datetime(symbolDataframe['Date']).dt.tz_localize(None)
        nifty200Dataframe['Date1'] = pd.to_datetime(nifty200Dataframe['Date']).dt.tz_localize(None)
        symbolDataframe = symbolDataframe.merge(nifty200Dataframe[['Date1', 'Price']], on='Date1', how='left')
        symbolDataframe.drop(columns=['Date1'], inplace=True)
        nifty200Dataframe.drop(columns=['Date1'], inplace=True)
        symbolDataframe.rename(columns={'Price': 'BenchmarkPrice'}, inplace=True)
        symbolDataframe['BenchmarkCR'] = ((symbolDataframe['BenchmarkPrice'] - symbolDataframe['BenchmarkPrice'].shift(regimeLookBackValue)) / symbolDataframe['BenchmarkPrice'].shift(regimeLookBackValue)) * 100
        symbolDataframe['CloseCR'] = ((symbolDataframe['Close'] - symbolDataframe['Close'].shift(regimeLookBackValue)) / symbolDataframe['Close'].shift(regimeLookBackValue) ) * 100.0
        symbolDataframe.dropna(inplace=True)
        # symbolDataframe['BenchmarkCR'] = symbolDataframe['BenchmarkPctChange'].rolling(window=regimeLookBackValue).mean()
        # symbolDataframe['CloseCR'] = symbolDataframe['ClosePctChange'].rolling(window=regimeLookBackValue).mean()

        pp = symbolDataframe.loc[20:60, ['Date', 'Close', 'BenchmarkPrice',  'BenchmarkCR', 'CloseCR']]
        symbolDataframe.dropna(inplace=True)
        symbolDataframe = symbolDataframe.reset_index(drop=True)
        # from the given symbolDataframe create a new column called regimeChange which has value equal to the index above it
        # which is at least 20 places above and is considered if the given BenchmarkCR is greater than 0 then the above given
        # index should have value < 0 and vice versa

        def find_regime_change(row_idx, cr_series, window=regimeLookBackValue+1):
            if row_idx < window:
                return np.nan
            current_cr = cr_series.iloc[row_idx]
            for i in range(row_idx - window, -1, -1):
                prev_cr = cr_series.iloc[i]
                if (current_cr > 0 and prev_cr < 0) or (current_cr < 0 and prev_cr > 0):
                    return i
            return np.nan

        # Apply the function to each row to get the regime change index
        regime_change_indices = [
            find_regime_change(idx, symbolDataframe['BenchmarkCR'])
            for idx in range(len(symbolDataframe))
        ]
        symbolDataframe['regimeChange'] = regime_change_indices
        symbolDataframe = symbolDataframe.dropna()

        symbolDataframe['CloseOppositeCR'] = symbolDataframe['regimeChange'].apply(lambda idx: symbolDataframe.loc[idx, 'CloseCR'] if pd.notnull(idx) and idx in symbolDataframe.index else None)
        symbolDataframe['BenchmarkOppositeCR'] = symbolDataframe['regimeChange'].apply(lambda idx: symbolDataframe.loc[idx, 'BenchmarkCR'] if pd.notnull(idx) and idx in symbolDataframe.index else None)

        symbolDataframe['Strength'] = symbolDataframe.apply(dynamic_strength_label, axis=1)
        symbolDataframe = symbolDataframe.dropna()
        #print(symbolDataframe.loc[34:80,['CloseCR', 'BenchmarkCR', 'regimeChange', 'CloseOppositeCR', 'BenchmarkOppositeCR', 'Strength']])

        symbolDataframe = Utils.convert_yf_datetime_to_pandas_datetime(symbolDataframe)
        symbolDataframe['E'+str(spanList[0])] = symbolDataframe['Close'].shift(lagFactor).ewm(span=spanList[0], adjust=False).mean()
        symbolDataframe['E' + str(spanList[1])] = symbolDataframe['Close'].shift(lagFactor).ewm(span=spanList[1], adjust=False).mean()
        symbolDataframe['E' + str(spanList[2])] = symbolDataframe['Close'].shift(lagFactor).ewm(span=spanList[2], adjust=False).mean()
        symbolDataframe['E' + str(spanList[3])] = symbolDataframe['Close'].shift(lagFactor).ewm(span=spanList[3], adjust=False).mean()

        symbolDataframe.dropna(inplace=True)
        
        symbolDataframe['isCloseAbove' + str(spanList[0])] = symbolDataframe.apply(lambda x : 1 if x['Close'] > x['E' + str(spanList[0])] else -1, axis=1)
        symbolDataframe['isCloseAbove' + str(spanList[1])] = symbolDataframe.apply(lambda x : 1 if x['Close'] > x['E' + str(spanList[1])] else -1, axis=1)
        symbolDataframe['isCloseAbove' + str(spanList[2])] = symbolDataframe.apply(lambda x : 1 if x['Close'] > x['E' + str(spanList[2])] else -1, axis=1)
        symbolDataframe['isCloseAbove' + str(spanList[3])] = symbolDataframe.apply(lambda x : 1 if x['Close'] > x['E' + str(spanList[3])] else -1, axis=1)

        symbolDataframe['isE' + str(spanList[0]) +'AboveE' + str(spanList[1])] = symbolDataframe.apply(lambda x : 1 if x['E' + str(spanList[0])] > x['E' + str(spanList[1])] else -1, axis=1)
        symbolDataframe['isE' + str(spanList[0]) +'AboveE' + str(spanList[2])] = symbolDataframe.apply(lambda x : 1 if x['E' + str(spanList[0])] > x['E' + str(spanList[2])] else -1, axis=1)
        symbolDataframe['isE' + str(spanList[0]) +'AboveE' + str(spanList[3])] = symbolDataframe.apply(lambda x : 1 if x['E' + str(spanList[0])] > x['E' + str(spanList[3])] else -1, axis=1)
        symbolDataframe['isE' + str(spanList[1]) +'AboveE' + str(spanList[2])] = symbolDataframe.apply(lambda x : 1 if x['E' + str(spanList[1])] > x['E' + str(spanList[2])] else -1, axis=1)
        symbolDataframe['isE' + str(spanList[1]) +'AboveE' + str(spanList[3])] = symbolDataframe.apply(lambda x : 1 if x['E' + str(spanList[1])] > x['E' + str(spanList[3])] else -1, axis=1)
        symbolDataframe['isE' + str(spanList[2]) +'AboveE' + str(spanList[3])] = symbolDataframe.apply(lambda x : 1 if x['E' + str(spanList[2])] > x['E' + str(spanList[3])] else -1, axis=1)
        #symbolDataframe['isE' + str(spanList[0]) +'AboveE' + str(spanList[2])] = symbolDataframe.apply(lambda x : 1 if x['E' + str(spanList[0])] > x['E' + str(spanList[2])] else -1, axis=1)

        symbolDataframe['TotalValue'] = symbolDataframe['isCloseAbove' + str(spanList[0])] + symbolDataframe['isCloseAbove' + str(spanList[1])] + \
                                            symbolDataframe['isCloseAbove' + str(spanList[2])] + symbolDataframe['isCloseAbove' + str(spanList[3])] + symbolDataframe['isE' + str(spanList[0]) +'AboveE' + str(spanList[1])] + \
                                                symbolDataframe['isE' + str(spanList[1]) +'AboveE' + str(spanList[2])] + symbolDataframe['isE' + str(spanList[0]) +'AboveE' + str(spanList[2])] + \
                                                symbolDataframe['isE' + str(spanList[0]) +'AboveE' + str(spanList[3])] + symbolDataframe['isE' + str(spanList[1]) +'AboveE' + str(spanList[3])] + \
                                                    symbolDataframe['isE' + str(spanList[2]) +'AboveE' + str(spanList[3])]
        
        # ci = CCIIndicator(high=symbolDataframe['High'], low=symbolDataframe['Low'], close=symbolDataframe['Close'], window=3)
        # symbolDataframe['choppiness'] = ci.cci()
        # atr = AverageTrueRange(high=symbolDataframe['High'], low=symbolDataframe['Low'], close=symbolDataframe['Close'], window=2).average_true_range()
        # sum_atr = atr.rolling(window=2).sum()
        # high_max = symbolDataframe['High'].rolling(window=2).max()
        # low_min = symbolDataframe['Low'].rolling(window=2).min()
        # ci = 100 * np.log10(sum_atr / (high_max - low_min)) / np.log10(2)
        # symbolDataframe['choppiness'] = ci
        symbolDataframe['Symbol'] = symbol
        symbolDataframe['ReturnChange'] = ((symbolDataframe['Close'].shift(lagFactor) - symbolDataframe['Close'].shift(moveToShiftForReturn+lagFactor))/symbolDataframe['Close'].shift(moveToShiftForReturn+lagFactor)) * 100
        #symbolDataframe['Volatility'] = symbolDataframe['ReturnChange'].rolling(window=2).std()
        symbolDataframe.dropna(inplace=True)
        symbolDataframe['PRET'] = symbolDataframe.apply(lambda x : 1 if x['ReturnChange'] > 0 else -1, axis=1)
        symbolDataframe['Direction'] = symbolDataframe['Close'].diff()
        symbolDataframe['PositivePercentage'] = symbolDataframe['Direction'].shift(lagFactor).rolling(window=FIPWindowSpan).apply(lambda x: len([+1 for i in x if i > 0]))
        symbolDataframe['NegativePercentage'] = symbolDataframe['Direction'].shift(lagFactor).rolling(window=FIPWindowSpan).apply(lambda x: len([+1 for i in x if i < 0]))
        symbolDataframe['NoChange'] = symbolDataframe['Direction'].shift(lagFactor).rolling(window=FIPWindowSpan).apply(lambda x: len([+1 for i in x if i == 0]))
        symbolDataframe['FIPValue1'] = symbolDataframe['PRET'] * ((symbolDataframe['NegativePercentage']/FIPWindowSpan)- (symbolDataframe['PositivePercentage']/FIPWindowSpan))
        # for the above symbolDataframe create a new column called FIPValue whose value is symbolDataframe['NegativePercentage']/57 if PRET - -1 else symbolDataframe['PositivePercentage']/57
        symbolDataframe['FIPValue'] = symbolDataframe.apply(lambda x : x['NegativePercentage']/30 if x['PRET'] == -1 else x['PositivePercentage']/30, axis=1)
        symbolDataframe['StrDate'] = symbolDataframe['Date'].dt.strftime('%Y-%m-%d').copy()
        
        if symbolDataframe.empty:
            continue
        
        symbolToDataframeDict[symbol] = symbolDataframe
        allSymbologyDataFrame.append(symbolDataframe)

    for i in range(allSymbologyDataFrame.__len__()):
        allSymbologyDataFrame[i] = allSymbologyDataFrame[i][~allSymbologyDataFrame[i]['FIPValue'].isna()]
        allSymbologyDataFrame[i].reset_index(drop=True, inplace=True)

    dates = allSymbologyDataFrame[0].iloc[0:]['Date'].to_list()
    # AllDates = [date.strftime('%d-%m-%Y') for date in dates]
    # AllDates
    for i in range(allSymbologyDataFrame.__len__()):
        allSymbologyDataFrame[i].loc[:, 'StrDate'] = allSymbologyDataFrame[i]['Date'].dt.strftime('%Y-%m-%d').copy()
        allSymbologyDataFrame[i].reset_index(drop=True, inplace=True)


        
    # For allSymbologyDataFrame at index 0, get the row with the Date value as 'YYYY-MM-DD' format
    date_to_find = '2021-01-01'
    AllDates = [date.strftime('%Y-%m-%d') for date in dates]

    totalDatesToRun = AllDates.__len__()
    # startDateForRun = '2014-12-10'
    # endDateTillRun = '2027-03-27'
    startDateForRun = start_date_to_read
    endDateTillRun = end_date_to_read
    forwardValue = 1 # indicates how many candles to move forward by....
    totalScoreFilter = 5
    # Find the next nearest startDateForRun entry value in AllDates and its index
    nearest_start_date_index = next((i for i, date in enumerate(AllDates) if date >= startDateForRun), None)
    nearest_start_date = AllDates[nearest_start_date_index] if nearest_start_date_index is not None else None

    nearest_end_date_index = next((i for i, date in enumerate(AllDates) if date >= endDateTillRun), None)
    nearest_end_date = AllDates[nearest_end_date_index] if nearest_end_date_index is not None else None

    if nearest_end_date_index is None:
        nearest_end_date_index = totalDatesToRun - 1
        nearest_end_date = AllDates[nearest_end_date_index]


    cashInPortfolio = 1000000
    portfolioList = []
    symbolToPriceDict = {}
    symbolPurchasedToQtyDict = {}
    df_back_test = pd.DataFrame(columns=['Date', 'StockList'])

    weeklyPortfolioValueDf = pd.DataFrame(columns=['Date', 'AccountValue', 'StockList'])
    weeklyPortfolioForwardValueDf = pd.DataFrame(columns=['Date', 'EntryDate', 'ExitDate', 'Symbol', 'EntryPrice', 'ExitPrice'])
    AdvanceDeclineDf = pd.DataFrame(columns=['Date', 'TotalAdvance'])
    newPortfolioDf = pd.DataFrame(columns=['Date', 'EntryDate', 'ExitDate', 'Symbol', 'EntryPrice', 'ExitPrice'])

    def getSymbolClosePrice(symbol, date):
        df = symbolNameToSymbolDataframeDict[symbol]
        if df.empty:
            return 0
        else:
            filtered_df = Utils.filter_panda_df_in_range_constraint(df, 'Date', date, date)
            if filtered_df.empty:
                return 0
            else:
                return filtered_df['Close'].iloc[0]

    def getQtyPurchasedForSymbol(symbol):
        if symbolPurchasedToQtyDict.get(symbol) is None:
            return 0
        return symbolPurchasedToQtyDict[symbol]

    def get_portfolio_value():
        totalPortfolioValue = 0
        for symbol in portfolioList:
            totalPortfolioValue += symbolToPriceDict[symbol] * getQtyPurchasedForSymbol(symbol)
        return totalPortfolioValue

    def get_account_value():
        return (get_portfolio_value() + cashInPortfolio)

    for runDate in range(nearest_start_date_index, nearest_end_date_index+1, forwardValue):
        current_run_date = AllDates[runDate]
        print("Weekly date [" + current_run_date + "] " )
        next_run_date = AllDates[runDate + forwardValue] if runDate + forwardValue < totalDatesToRun else None

        portfolioSymbolsToAdd = []
        currentSymbolToPriceDict= {}
        choppinessList = []
        advanceDecline = 0
        symbolDf1 = pd.DataFrame(columns=['Symbol', 'TotalScore', 'Strength','FIPScore'])
        falseNegativesDf1 = pd.DataFrame(columns=['Symbol', 'TotalScore', 'Strength', 'FIPScore'])

        for symbolDf  in allSymbologyDataFrame:
            filtered_df = Utils.filter_panda_df_in_range_constraint(symbolDf, 'StrDate', current_run_date, current_run_date)
        
            if filtered_df.empty:
                continue
            #choppinessList.append(filtered_df['choppiness'].iloc[0])
            if filtered_df['Direction'].iloc[0] > 0:
                advanceDecline += 1
            
            symbolName = filtered_df['Symbol'].iloc[0]
    
            currentSymbolPrice = filtered_df['Close'].iloc[0]
            nextWeekSymbolPrice = getSymbolClosePrice(symbolName, next_run_date) if next_run_date else 0
            currentSymbolToPriceDict[symbolName] = getSymbolClosePrice(symbolName, current_run_date)
            meanTotalScoreValue = filtered_df['TotalValue'].mean()
            strengthScore = filtered_df['Strength'].iloc[0]
            forwardScoreValue = (nextWeekSymbolPrice - currentSymbolPrice)/currentSymbolPrice * 100 if next_run_date else -5
            
            FIPValue1 = filtered_df['FIPValue1'].iloc[0]

            # append the symbolDf above to columns 'Symbol' mapped to symbolName, TotalScore to meanTotalScoreValue and FIPValue to FIPValue1
            dfx = pd.DataFrame({
                'Symbol': [symbolName],
                'TotalScore': [meanTotalScoreValue],
                'Strength' : [strengthScore],
                'FIPScore' : [FIPValue1]
            })
            dfx1 = pd.DataFrame({
                'Symbol': [symbolName],
                'TotalScore': [forwardScoreValue],
                'Strength' : [strengthScore],
                'FIPScore' : [FIPValue1]
            })
            
            
            if symbolDf1.empty:
                symbolDf1 = dfx
            else:
                if not dfx.empty and not dfx.isna().all(axis=None):
                    symbolDf1 = pd.concat([symbolDf1, dfx.dropna(how='all')], ignore_index=True)
            
            if falseNegativesDf1.empty:
                falseNegativesDf1 = dfx1
            else:
                if not dfx1.empty and not dfx1.isna().all(axis=None):
                    falseNegativesDf1 = pd.concat([falseNegativesDf1, dfx1.dropna(how='all')], ignore_index=True)

        advanceDeclineDfx = pd.DataFrame({
                'Date': [current_run_date],
                'TotalAdvance' : [(advanceDecline/224) * 100]
        })
        
        if AdvanceDeclineDf.empty:
            AdvanceDeclineDf = advanceDeclineDfx
        else:
            if not advanceDeclineDfx.empty and not advanceDeclineDfx.isna().all(axis=None):
                AdvanceDeclineDf = pd.concat([AdvanceDeclineDf, advanceDeclineDfx.dropna(how='all')], ignore_index=True)
        

        symbolDf1 = symbolDf1.sort_values(by=['TotalScore', 'Strength', 'FIPScore'], ascending=[False, False, True])
        
        portfolioSymbolsToAdd = symbolDf1.head(stocksToSelect)['Symbol'].tolist()
        print(symbolDf1.head(stocksToSelect)['Symbol'])
        forwardPortfolioSymbolsToAdd = falseNegativesDf1.head(stocksToSelect)['Symbol'].tolist()
        
        # create a df of run_date to portfolioSymbolsToAdd
        if df_back_test.empty:
            df_back_test = pd.DataFrame({
            'Date': [current_run_date],
            'StockList': [portfolioSymbolsToAdd]})
        else:
            df_back_test = pd.concat([df_back_test, pd.DataFrame({'Date': [current_run_date], 'StockList': [portfolioSymbolsToAdd]})], ignore_index=True)
        
        dffx = pd.DataFrame({
            'Date': [current_run_date],
            'StockList': [forwardPortfolioSymbolsToAdd]
        })
        newPortfolioStructure = {}
        for symbol in forwardPortfolioSymbolsToAdd:
            newPortfolioStructure['Symbol'] = symbol
            newPortfolioStructure['EntryDate'] = current_run_date 
            newPortfolioStructure['ExitDate'] = next_run_date if next_run_date else None
            newPortfolioStructure['EntryPrice'] =  getSymbolClosePrice(symbol, current_run_date)
            newPortfolioStructure['ExitPrice']   = getSymbolClosePrice(symbol, next_run_date) if next_run_date else None
            if weeklyPortfolioForwardValueDf.empty:
                weeklyPortfolioForwardValueDf = pd.DataFrame(newPortfolioStructure, index=[0])
            else:
                weeklyPortfolioForwardValueDf = pd.concat([weeklyPortfolioForwardValueDf, pd.DataFrame(newPortfolioStructure, index=[0])], ignore_index=True)
                
        # find common elements between portfolioList and portfolioSymbolsToAdd 
        commonSymbols = list(set(portfolioList) & set(portfolioSymbolsToAdd))
        symbolsToLiquidate = list(set(portfolioList) - set(commonSymbols))
        symbolsToAdd = list(set(portfolioSymbolsToAdd) - set(commonSymbols))
        symbolAtLossPercentageDuringPreviousRun = {}
        symbolAtGainPercentageDuringPreviousRun = {}

        for symbol in symbolsToLiquidate:
            exitSymbolPrice = getSymbolClosePrice(symbol, current_run_date)
            purchaseSymbolPrice = symbolToPriceDict.get(symbol, 0)
            stopLossSymbolPrice = purchaseSymbolPrice - (purchaseSymbolPrice * stopLossPercentage / 100)
            # if symbolToDataframeDict.get(symbol) is not None:
            #     symbolDataframe = symbolToDataframeDict[symbol]
            #     filtered_df = Utils.filter_panda_df_in_range_constraint(symbolDataframe, 'StrDate', current_run_date, current_run_date)
            #     if not filtered_df.empty and filtered_df['Low'].iloc[0] < stopLossSymbolPrice:
            #             exitSymbolPrice = stopLossSymbolPrice
            
            if purchaseSymbolPrice > 0 :
                profitOrLoss = exitSymbolPrice - purchaseSymbolPrice
                if profitOrLoss < 0:
                    symbolAtLossPercentageDuringPreviousRun[symbol] = profitOrLoss/purchaseSymbolPrice * 100
            cashInPortfolio +=  exitSymbolPrice * getQtyPurchasedForSymbol(symbol)
            cashInPortfolio -=  exitSymbolPrice * getQtyPurchasedForSymbol(symbol) * 0.001
            portfolioList.remove(symbol)
        
        for symbol in commonSymbols:
            currentSymbolPrice = getSymbolClosePrice(symbol, current_run_date)
            newPortfolioStructure['Symbol'] = symbol
            newPortfolioStructure['EntryDate'] = current_run_date 
            newPortfolioStructure['ExitDate'] = next_run_date if next_run_date else None
            newPortfolioStructure['EntryPrice'] =  getSymbolClosePrice(symbol, current_run_date)
            newPortfolioStructure['ExitPrice']   = getSymbolClosePrice(symbol, next_run_date) if next_run_date else None
            if newPortfolioDf.empty:
                newPortfolioDf = pd.DataFrame(newPortfolioStructure, index=[0])
            else:
                newPortfolioDf = pd.concat([newPortfolioDf, pd.DataFrame(newPortfolioStructure, index=[0])], ignore_index=True)
        
            purchaseSymbolPrice = symbolToPriceDict.get(symbol, 0)
            
            if purchaseSymbolPrice > 0 :
                profitOrLoss = currentSymbolPrice - purchaseSymbolPrice
                if profitOrLoss < 0:
                    symbolAtLossPercentageDuringPreviousRun[symbol] = profitOrLoss/purchaseSymbolPrice * 100
                else:
                    symbolAtGainPercentageDuringPreviousRun[symbol] = profitOrLoss/purchaseSymbolPrice * 100
            
            # if stopLossPercentage > 0:
            #     stopLossSymbolPrice = purchaseSymbolPrice - (purchaseSymbolPrice * stopLossPercentage / 100)
            #     if symbolToDataframeDict.get(symbol) is not None:
            #         symbolDataframe = symbolToDataframeDict[symbol]
            #         filtered_df = Utils.filter_panda_df_in_range_constraint(symbolDataframe, 'StrDate', current_run_date, current_run_date)
            #         if not filtered_df.empty and filtered_df['Low'].iloc[0] < stopLossSymbolPrice:
            #             cashInPortfolio +=  stopLossSymbolPrice * getQtyPurchasedForSymbol(symbol)
            #             cashInPortfolio -=  stopLossSymbolPrice * getQtyPurchasedForSymbol(symbol) * 0.001
            #             symbolsToAdd.append(symbol)
                            

        if symbolsToAdd.__len__() > 0:
            totalSymbols = len(symbolsToAdd)
            cashPerStock = cashInPortfolio/len(symbolsToAdd)

            for symbol in symbolsToAdd:
                if totalSymbols <= 0:
                    break
                newPortfolioStructure['Symbol'] = symbol
                newPortfolioStructure['EntryDate'] = current_run_date 
                newPortfolioStructure['ExitDate'] = next_run_date if next_run_date else None
                newPortfolioStructure['EntryPrice'] = getSymbolClosePrice(symbol, current_run_date)
                newPortfolioStructure['ExitPrice']   = getSymbolClosePrice(symbol, next_run_date) if next_run_date else None
                if newPortfolioDf.empty:
                    newPortfolioDf = pd.DataFrame(newPortfolioStructure, index=[0])
                else:
                    newPortfolioDf = pd.concat([newPortfolioDf, pd.DataFrame(newPortfolioStructure, index=[0])], ignore_index=True)
        
                cashPerStock = cashInPortfolio/totalSymbols
                stockQty = cashPerStock/getSymbolClosePrice(symbol, current_run_date)
                symbolPurchasedToQtyDict[symbol] = stockQty
                cashInPortfolio -= cashPerStock
                cashInPortfolio -= cashPerStock * 0.001
                totalSymbols -= 1                
                portfolioList.append(symbol)
                
                
        symbolToPriceDict = currentSymbolToPriceDict
        df2 = pd.DataFrame({
            'Date': [current_run_date],
            'AccountValue': [get_account_value()],
            'StockList': [portfolioSymbolsToAdd]
        })
        # # in the above given df2, add columns from symbolAtLossDuringPreviousRun with added columns for symbol and loss
        # if symbolAtLossPercentageDuringPreviousRun:
        #     for idx, (sym, loss) in enumerate(symbolAtLossPercentageDuringPreviousRun.items()):
        #         df2[f'SymbolAtLoss_{idx+1}'] = [sym]
        #         df2[f'Loss_{idx+1}'] = [loss]
        # if symbolAtGainPercentageDuringPreviousRun:
        #     for idx, (sym, gain) in enumerate(symbolAtGainPercentageDuringPreviousRun.items()):
        #         df2[f'SymbolAtGain_{idx+1}'] = [sym]
        #         df2[f'Gain_{idx+1}'] = [gain]
        

        if weeklyPortfolioValueDf.empty:
            weeklyPortfolioValueDf = df2
        else:
            weeklyPortfolioValueDf = pd.concat([weeklyPortfolioValueDf, df2], ignore_index=True)
        print(portfolioSymbolsToAdd)
        #print(nifyvix.iloc[nearest_next_index]['percentile'])
        print("Weekly date [" + current_run_date + "] " +  str(get_account_value()))
        if weeklyPortfolioDateToValueDf.empty:
            weeklyPortfolioDateToValueDf = pd.DataFrame({
                'Date': [current_run_date],
                'AccountValue': [get_account_value()]
            })
        else:
            weeklyPortfolioDateToValueDf = pd.concat([weeklyPortfolioDateToValueDf, pd.DataFrame({
                'Date': [current_run_date],
                'AccountValue': [get_account_value()]
            })], ignore_index=True)
    #newPortfolioDf.to_csv("Learning2.csv", index=False)
    weeklyPortfolioForwardValueDf.to_csv("WeeklyPortfolioForwardValue.csv", index=False)
    df_back_test.to_csv("df_back_test.csv", index=False)
    return weeklyPortfolioDateToValueDf

# In-memory cache for results based on (start_date, end_date)
portfolio_cache: Dict[Tuple[str, str], Dict] = {}
cache_key = ("2014-01-01", Utils.get_current_date())

def get_analysis_response(start_date_to_read, end_date_to_read):
    cache_key = (start_date_to_read, end_date_to_read)
    cache_key1 = ("2014-01-01", Utils.get_current_date())
    # Return from cache if exists
    if cache_key in portfolio_cache:
        print(f"Returning cached result for {cache_key}")
        return JSONResponse(content=portfolio_cache[cache_key])
    
    if cache_key1 in portfolio_cache and (start_date_to_read >= "2014-01-01" and end_date_to_read <= Utils.get_current_date()):
        initialPortfolioValue = 1000000  # Initial portfolio value for calculations
        portfolioDateToValueDf = pd.DataFrame(portfolio_cache[cache_key1]["StrategyPortfolioValue"])       
        # Find the index of the first date >= start_date_to_read
        first_idx = portfolioDateToValueDf[portfolioDateToValueDf['Date'] >= start_date_to_read].index.min()
        # Find the index of the last date <= end_date_to_read
        last_idx = portfolioDateToValueDf[portfolioDateToValueDf['Date'] <= end_date_to_read].index.max()
        # If not found, fallback to first/last
        if pd.isna(first_idx):
            first_idx = 0
        if pd.isna(last_idx):
            last_idx = len(portfolioDateToValueDf) - 1
        # Get the dataframe between these indices
        portfolioDateToValueDf = portfolioDateToValueDf.iloc[first_idx:last_idx+1].reset_index(drop=True)
        ss = getNifty200PortfolioValues(portfolioDateToValueDf.iloc[0], portfolioDateToValueDf.iloc[-1],
                                   portfolioDateToValueDf['Date'].to_list(), 6)
        portfolioDateToValueDf['PctChange'] = portfolioDateToValueDf['PortfolioValue'].pct_change()
        portfolioDateToValueDf['PctChange'].iloc[0] = 0.0
        # Calculate percentage change between consecutive Open values
        ss['PctChange'] = ss['Open'].pct_change()

        # Fill first value with 0% change (since it's the base)
        ss['PctChange'].iloc[0] = 0.0
        ss['PortfolioValue'] = initialPortfolioValue * (1 + ss['PctChange']).cumprod()        
        portfolioDateToValueDf['PortfolioValue'] = initialPortfolioValue * (1 + portfolioDateToValueDf['PctChange']).cumprod()
        portfolioDateToValueDf = portfolioDateToValueDf[['Date', 'PortfolioValue']]
        ss = ss[['Date', 'PortfolioValue']]
        porfoliovalue_json_response = portfolioDateToValueDf.to_dict(orient='records')
        nifty200value_json_response = ss.to_dict(orient='records')
        response_data = {
            "Nifty200PortfolioValue": nifty200value_json_response,
            "StrategyPortfolioValue": porfoliovalue_json_response
        }
        portfolio_cache[cache_key] = response_data
        return response_data
    else:
        portfolioDateToValueDf = pd.DataFrame(columns=['Date', 'AccountValue'])
        portfolioDateToValueDf = strategy_run(symbolList, granularity, start_date_to_read, end_date_to_read, portfolioDateToValueDf)
        portfolioDateToValueDf['Date'] = portfolioDateToValueDf['Date'].astype(str)
        portfolioDateToValueDf['PctChange'] = portfolioDateToValueDf['AccountValue'].pct_change()
        portfolioDateToValueDf['PctChange'].iloc[0] = 0.0
        first_date = (portfolioDateToValueDf['Date'].iloc[0])
        last_date = (portfolioDateToValueDf['Date'].iloc[-1])
        
        # Get list of all dates in the portfolioDateToValueDf
        all_dates = portfolioDateToValueDf['Date'].tolist()
        
        print(f"First date: {first_date}, Last date: {last_date}")
        initialPortfolioValue = portfolioDateToValueDf['AccountValue'].iloc[0]
        ss = getNifty200PortfolioValues(first_date, last_date, all_dates, filterTypeDays=6)

        # Calculate percentage change between consecutive Open values
        ss['PctChange'] = ss['Open'].pct_change()

        # Fill first value with 0% change (since it's the base)
        ss['PctChange'].iloc[0] = 0.0

        # Compute AccountValue based on scaling from first Open value
        ss['PortfolioValue'] = initialPortfolioValue * (1 + ss['PctChange']).cumprod()
        ss = ss[['Date', 'PortfolioValue']]

        # Rename columns to match desired JSON keys
        portfolioDateToValueDf = portfolioDateToValueDf.rename(
            columns={'Date': 'Date', 'AccountValue': 'PortfolioValue'}
        )

        # Convert to list of dicts
        porfoliovalue_json_response = portfolioDateToValueDf.to_dict(orient='records')
        nifty200value_json_response = ss.to_dict(orient='records')
        response_data = {
            "Nifty200PortfolioValue": nifty200value_json_response,
            "StrategyPortfolioValue": porfoliovalue_json_response
        }
        portfolio_cache[cache_key] = response_data
        
        # create a JSON reponse  with above two response type such that it send a key "Nifty200PortfolioValue" and "StrategyPortfolioValue" with the respective values
        return response_data

portfolio_cache[cache_key] = get_analysis_response("2014-01-01", Utils.get_current_date())
@router.get("/analysis/getPortfolioValue")
async def get_portfolio_value_from_start_date_to_end_date(request: Request):

    params = request.query_params
    # Get start_date_to_read and end_date_to_read from query params, incoming into epoch time format
    # but convert it to string format 'YYYY-MM-DD' and default to '2014-01-01' and '2025-05-28' respectively
    def epoch_to_datestr(epoch, default):
        # Also check if epoch is upto milliseconds level if milleseconds are present then convert it to seconds
        try:
            if epoch is None:
                return default
            epoch = int(epoch)
            # If epoch is in milliseconds (length > 10 digits), convert to seconds
            if epoch > 1e12:
                epoch = epoch // 1000
            return datetime.datetime.utcfromtimestamp(epoch).strftime('%Y-%m-%d')
        except Exception:
            return default

    start_date_to_read = epoch_to_datestr(params.get("start_date"), "2014-01-01")
    end_date_to_read = epoch_to_datestr(params.get("end_date"), "2025-05-28")
    # start_date_to_read = params.get("start_date", "2014-01-01")
    # end_date_to_read = params.get("end_date", "2025-05-28")
    return get_analysis_response(start_date_to_read, end_date_to_read)
 

def getStockListForPortfolioAndStrategy(portfolioId, strategyId, headers):
    headers['x-bling-token'] = blingToken
    response = requests.get("https://swagger.bling-trading.com/PortfolioFile?portfolioId="+ portfolioId, headers=headers)
    print("Status Code:", response.status_code)
    stockList = []
    # from above filtered order legs get the name of all stocks and put in stockList
    if response.status_code == 201:
        response_data = response.json()
        if response_data.get("success"):
            order_legs = response_data.get("data", {}).get("OrderLegs", {})
            strategy_id = 1  # Replace with the desired StrategyId
            filtered_order_legs = {key: value for key, value in order_legs.items() if value.get("StrategyId") == strategy_id}
            
            # Extract stock names into stockList
            print(filtered_order_legs)
            stockList = [value.get("StockName") for value in filtered_order_legs.values()]
            print("Stock List:", stockList)
        else:
            print("Error Message:", response_data.get("errorMessage"))
    else:
        print("Failed to fetch portfolio data.")
    
    return stockList



# from above given stockList get the LegId corresponding to the same
def getLegIdForStockList(stockList, portfolioId, strategyId, blingToken, headers):
    headers['x-bling-token'] = blingToken
    response = requests.get("https://swagger.bling-trading.com/PortfolioFile?portfolioId="+ portfolioId, headers=headers)
    print("Status Code:", response.status_code)
    leg_ids = []
    # from above filtered order legs get the name of all stocks and put in stockList
    if response.status_code == 201:
        response_data = response.json()
        if response_data.get("success"):
            order_legs = response_data.get("data", {}).get("OrderLegs", {})
            strategy_id = 1  # Replace with the desired StrategyId
            filtered_order_legs = {key: value for key, value in order_legs.items() if value.get("StrategyId") == strategy_id}
            
            # Extract LegIds for the given stockList
            leg_ids = [key for key, value in filtered_order_legs.items() if value.get("StockName") in stockList]
            print("Leg IDs:", leg_ids)
        else:
            print("Error Message:", response_data.get("errorMessage"))
    else:
        print("Failed to fetch portfolio data.")
    return leg_ids

def sendMomentumStocksToPortfolio(stockList, url, portfolioId, strategyId, blingToken, data, headers):
    params = {
        "portfolioId": portfolioId,
        "strategyId": strategyId
    }
    
    for symbol in stockList:
        data['StockName'] = symbol
        headers['x-bling-token'] = blingToken
            # Make the POST request
        response = requests.post(url, headers=headers, params=params, json=data)
        print("Status Code:", response.status_code)
        print("Response:", response.text)
        
def deleteOrderLegForPortfolioStrategy(stockList, portfolioId, strategyId, blingToken, headers):
    headers['x-bling-token'] = blingToken
    leg_ids = getLegIdForStockList(stockList, portfolioId, strategyId, blingToken)
    print("Leg IDs to delete:", leg_ids)
    for leg_id in leg_ids:
        print("Deleting Leg ID:", leg_id)
        requests.post("https://swagger.bling-trading.com/OrderLeg/Delete?portfolioId="+ portfolioId + "&strategyId=" + strategyId + "&legId=" + leg_id, headers=headers)


def rebalancePortfolio(weeklyPortfolioValueDf, portfolioId, strategyId, blingToken):
    stockList1 = weeklyPortfolioValueDf.tail(1)['StockList'].values[0]
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Origin": "https://gui.bling-trading.com",
        "Referer": "https://gui.bling-trading.com/portfolio/14/1",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "x-bling-token": "YSkw0ZwThaVmhlB",
        "x-client-domain": "BLING",
        "x-platform": "WEB_SITE",
        "x-referrer-domain": "BLING"
    }

    data = {
        "StockName": "AA",
        "Side": "Buy",
        "WeightPercentage": 2,
        "ProfitTakingPercentage": None,
        "StopLossPercentage": None,
        "IsTrailingStopLoss": None
    }
    stockList = getStockListForPortfolioAndStrategy(portfolioId, strategyId, headers)

    # Get the intersection of stockList1 and stockList
    common_stocks = list(set(stockList1) & set(stockList))

    # Get the stocks which are not in stockList1
    stocks_to_sell = list(set(stockList) - set(stockList1))

    # Get the stocks which are in stockList1 but not in stockList
    stocks_to_buy = list(set(stockList1) - set(stockList))

    print("Common Stocks:", common_stocks)
    print("Stocks to Buy:", stocks_to_buy)
    print("Stocks to Sell", stocks_to_sell)

    deleteOrderLegForPortfolioStrategy(stocks_to_sell, portfolioId, strategyId, blingToken, headers)
    sendMomentumStocksToPortfolio(stocks_to_buy, "https://swagger.bling-trading.com/BasketOrderLeg/Create", portfolioId, strategyId, blingToken, data, headers)


