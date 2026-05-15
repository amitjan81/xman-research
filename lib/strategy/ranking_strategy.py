from lib.data import utils as Utils
import pandas as pd
import yfinance as yf
import requests
import json
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
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/..')
from src.common.constants import *



class MomentumStrategy:
    def __init__(self) -> None:
        self.symboluniverse = MarketUniverse()
        self.indicatorCalculator = IndicatorAdder()
        self.dataframewindowfilter = DataWindowFilter



granularity = "5m"
periodInString = "28d"
start_date_to_download = '2024-12-16' 

meanChangeCloseToSDValues = {
    'Symbol': [],
    'Mean': [],
    'StdDev' : []
}

if __name__ == "__main__":
    strategy = MomentumStrategy()
    current_date = Utils.get_current_date()
    previous_date = Utils.calculate_dates(current_date, 1, 1)['past_date']
    
    symbolListDataframe = strategy.symboluniverse.optionBackedEquityUniverse()
    symbolToSectorDict = strategy.symboluniverse.classify_stocks_to_sector()
    print(symbolToSectorDict)
    symbolListDataframe['Sector'] = symbolListDataframe['Symbol'].apply(lambda x :  symbolToSectorDict[x] if symbolToSectorDict.get(x) else "Others")
    dirname = GlobalConstants.historicMarketData_dir
    Utils.createDirectory(dirname)
    Utils.save_df_to_csv(symbolListDataframe, dirname, 'equitySchema.csv')
    
    symbolList = Utils.panda_series_toList_converter(symbolListDataframe['Symbol'])

    for symbol in symbolList:        
        symbolDataframe = Utils.readCsv(symbol, granularity, start_date_to_download, dirname, ".csv",  periodInString)
        symbolDataframe = Utils.convert_yf_datetime_to_pandas_datetime(symbolDataframe)

        Utils.convert_datetime64_to_user_format(symbolDataframe['Date'], '%d-%m-%Y %H:%M:%S')
        symbolDataframe['Time'] = Utils.convert_datetime64_to_user_format(symbolDataframe['Date'], '%H:%M:%S')
        symbolDataframe = Utils.convert_yf_datetime_to_pandas_datetime(symbolDataframe)
                
        print(symbolDataframe.dtypes)
        start_date = '2024-11-21'
        end_date = '2024-12-16'
        time_start_range = '10:15::00'
        time_end_range = '14:50:00'

        filteredSymbolDataFrame = Utils.filter_panda_df_in_range_constraint(symbolDataframe, 'Date', start_date, end_date)
        filteredSymbolDataFrame = Utils.filter_panda_df_in_range_constraint(filteredSymbolDataFrame, 'Time', time_start_range, time_end_range)

        filteredSymbolDataFrame = Utils.remove_timeZoneInfo_from_datetime(filteredSymbolDataFrame, 'Date')
        filteredSymbolDataFrame['YearMonth'] = Utils.convert_datetime_to_yearmonth(filteredSymbolDataFrame, 'Date')
        
        filteredSymbolDataFrame['Date'] = pd.to_datetime(filteredSymbolDataFrame['Date'], errors='coerce')

        filteredSymbolDataFrame.to_csv("zomato_csv")
        
        filteredSymbolDataFrame["SMA20"] = (
            filteredSymbolDataFrame["Close"].rolling(window=20).mean()
        )
        
        meanVolValue = filteredSymbolDataFrame['Volume'].mean()
        std_deviation_value = filteredSymbolDataFrame['Volume'].std()
        
        
        print("MeanVolume [" + str(meanVolValue) + "]")
        print("1SD [" + str(std_deviation_value) + "]")
        print("2SD [" + str(2*std_deviation_value) + "]")
        
        filteredSymbolDataFrame['ChangeInClose'] = ((filteredSymbolDataFrame['Close'] - filteredSymbolDataFrame['Open'])/filteredSymbolDataFrame['Open'])* 100
        
        meanChangeClose = filteredSymbolDataFrame['ChangeInClose'].mean()
        close_std_deviation = filteredSymbolDataFrame['ChangeInClose'].std()
        
        print("MeanChangeClosing [" + str(meanChangeClose) + "]")
        print("1SD [" + str(close_std_deviation) + "]")
        print("2SD [" + str(2*close_std_deviation) + "]")
        
        
        # sym1 mean1 sd1
        # sym2 mean2, sd2
        meanChangeCloseToSDValues['Symbol'].append(symbol)
        meanChangeCloseToSDValues['Mean'].append(meanChangeClose)
        meanChangeCloseToSDValues['StdDev'].append(close_std_deviation)
        
        print(meanChangeCloseToSDValues)

