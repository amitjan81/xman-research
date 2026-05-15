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
from backtesting import Backtest
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/..')
from src.common.constants import *
from lib.strategy.first_bt_strategy import SmaCross

class MomentumStrategy:
    def __init__(self) -> None:
        self.symboluniverse = MarketUniverse()
        self.indicatorCalculator = IndicatorAdder()
        self.dataframewindowfilter = DataWindowFilter



granularity = "2m"
#periodInString = "28d"
start_date_to_download = '2025-01-18'
end_date_to_download = '2025-01-21'
filter_start_date = '2024-01-01'
filter_end_date = '2024-09-29'
filter_start_time = '09:20::00'
filter_end_time  = '15:30:00'
STRATEGY_TYPE = SmaCross
candleDownloadChart = False
CSV_FILE_PATH = GlobalConstants.historicMarketData_csv_dir
if __name__ == "__main__":
    strategy = MomentumStrategy()
    current_date = Utils.get_current_date()
    previous_date = Utils.calculate_dates(current_date, 1, 1)['past_date']
    
    symbolListDataframe = strategy.symboluniverse.optionBackedEquityUniverse()
    #symbolToSectorDict = strategy.symboluniverse.classify_stocks_to_sector()
    symbolToSectorDict = {}
    print(symbolToSectorDict)
    symbolListDataframe['Sector'] = symbolListDataframe['Symbol'].apply(lambda x :  symbolToSectorDict[x] if symbolToSectorDict.get(x) else "Others")
    dirname = GlobalConstants.historicMarketData_dir
    Utils.createDirectory(dirname)
    Utils.save_df_to_csv(symbolListDataframe, dirname, 'equitySchema.csv')
    
    symbolList = Utils.panda_series_toList_converter(symbolListDataframe['Symbol'])
    # symbolList = ['TRENT']
    
    #Utils.download_Mkt_Data_For_Symbols_With_Granularity_And_SaveFilesToDirectory(symbolList, start_date_to_download, granularity, periodInString, dirname, ".csv")
    
    Utils.download_Mkt_Data_For_Symbols_With_Start_And_EndDate_With_Granularity_And_SaveFilesToDirectory(symbolList, start_date_to_download, end_date_to_download, granularity, dirname, ".csv")
    #Utils.download_Mkt_Data_For_Symbols_Without_Start_And_EndDate_With_Granularity_And_SaveFilesToDirectory(symbolList, granularity, dirname, ".csv")
    #Utils.download_Mkt_Data_For_Symbols_And_SaveFilesToDirectory(symbolList, "2y", "1d", dirname, ".csv")

    for symbol in symbolList:
        #symbolDataframe = Utils.readCsv(symbol, granularity, start_date_to_download, dirname, ".csv",  periodInString)
        symbolDataframe = Utils.readCsv_from_startdate_enddate(symbol, granularity, start_date_to_download, end_date_to_download, dirname, ".csv")

        symbolDataframe = Utils.convert_yf_datetime_to_pandas_datetime(symbolDataframe)

        Utils.convert_datetime64_to_user_format(symbolDataframe['Date'], '%d-%m-%Y %H:%M:%S')
        symbolDataframe['Time'] = Utils.convert_datetime64_to_user_format(symbolDataframe['Date'], '%H:%M:%S')
        symbolDataframe = Utils.convert_yf_datetime_to_pandas_datetime(symbolDataframe)

        filteredSymbolDataFrame = Utils.filter_panda_df_in_range_constraint(symbolDataframe, 'Date', filter_start_date, filter_end_date)
        #filteredSymbolDataFrame = Utils.filter_panda_df_in_range_constraint(filteredSymbolDataFrame, 'Time', filter_start_time, filter_end_time)

        filteredSymbolDataFrame = Utils.remove_timeZoneInfo_from_datetime(filteredSymbolDataFrame, 'Date')
        filteredSymbolDataFrame['YearMonth'] = Utils.convert_datetime_to_yearmonth(filteredSymbolDataFrame, 'Date')
        
        filteredSymbolDataFrame['Date'] = pd.to_datetime(filteredSymbolDataFrame['Date'], errors='coerce')

        print(Utils.get_dataframe_size(filteredSymbolDataFrame))
        SYMBOL_CSV_FILE_NAME = CSV_FILE_PATH + symbol + "_" + filter_start_date + "_" + filter_start_time + "_" + filter_end_date + "_" + filter_end_time +   ".csv"
        
        if Utils.checkIfFileExists(SYMBOL_CSV_FILE_NAME) == False:
            filteredSymbolDataFrame.to_csv(SYMBOL_CSV_FILE_NAME)
        
        BACKTEST_INPUT_DF = Utils.read_Csv_for_backtesting_input(SYMBOL_CSV_FILE_NAME)
        BACKTEST_INPUT_DF['Date'] = pd.to_datetime(BACKTEST_INPUT_DF['Date'])
        BACKTEST_INPUT_DF.set_index('Date')
        BACKTEST_INPUT_DF.index = pd.to_datetime(BACKTEST_INPUT_DF['Date'])
        backTest = Backtest(BACKTEST_INPUT_DF, STRATEGY_TYPE, cash=10000.0, commission=0.002, trade_on_close=False)
        stats = backTest.run()
        print(stats)
        print(stats._trades)
        PLOT_FILE_NAME = GlobalConstants.backTest_plot_dir + symbol + "_" + filter_start_date + "_" + \
                            filter_start_time + "_" + filter_end_date + "_" + filter_end_time + "+" + "plot_png" 
        backTest.plot(filename=PLOT_FILE_NAME)

        # Plot Candle Chart with volume overlay and some other indicators for visual representation.
        if candleDownloadChart == True:
            filteredSymbolDataFrame["SMA20"] = (
                filteredSymbolDataFrame["Close"].rolling(window=20).mean()
            )
            
            meanVolValue = filteredSymbolDataFrame['Volume'].mean()
            std_deviation_value = filteredSymbolDataFrame['Volume'].std()
            
            
            print("MeanVolume [" + str(meanVolValue) + "]")
            print("1SD [" + str(std_deviation_value) + "]")
            print("2SD [" + str(2*std_deviation_value) + "]")

            filteredSymbolDataFrame = filteredSymbolDataFrame.dropna()

            # Calculate a 20-period SMA (adjust the window size as needed)
            candlePath = GlobalConstants.historicMarketData_dir + "/html_files/"

            fig = make_subplots(
                rows=1, cols=1,  # Single row and column
                specs=[[{"secondary_y": True}]]  # Enable secondary y-axis
            )
            # Add SMA line to the primary y-axis
            fig.add_trace(
                go.Scatter(
                    x=filteredSymbolDataFrame["Date"],
                    y=filteredSymbolDataFrame["SMA20"],
                    mode="lines",
                    name="SMA (20)",
                    line=dict(color="orange", width=2)  # Customize line color and width
                ),
                row=1, col=1, secondary_y=False  # Assign to primary y-axis
            )
            # Add candlestick chart to the primary y-axis
            fig.add_trace(
                go.Candlestick(
                    x=filteredSymbolDataFrame["Date"],
                    open=filteredSymbolDataFrame["Open"],
                    high=filteredSymbolDataFrame["High"],
                    low=filteredSymbolDataFrame["Low"],
                    close=filteredSymbolDataFrame["Close"],
                    name="Candlestick"
                ),
                row=1, col=1, secondary_y=False  # Assign to primary y-axis
            )

            # Add volume bar chart to the secondary y-axis
            fig.add_trace(
                go.Bar(
                    x=filteredSymbolDataFrame["Date"],
                    y=filteredSymbolDataFrame["Volume"],
                    name="Volume",
                    marker_color="blue",
                    opacity=0.4  # Adjust transparency for better visibility
                ),
                row=1, col=1, secondary_y=True  # Assign to secondary y-axis
            )

            # Update layout
            fig.update_layout(
                title="Candlestick Chart with Volume Overlay for stock " + symbolListDataframe.loc[symbolListDataframe["Symbol"] == symbol, "Description"].iloc[0],
                xaxis_title="Datetime",
                yaxis_title="Price",
                yaxis2_title="Volume",
                template="plotly_dark",  # Optional: dark theme
                height=640,  # Total height of the figure
            )
            # Show the chart
            #fig.show()
            fig.write_html(candlePath + symbol + "_" + granularity + "_" + filter_start_date + "-TO-" + filter_end_date +  "_candle.html")
            


        '''
           filteredSymbolDataFrame['RollingMeanVol'] = Utils.get_rollingmean_to_column(filteredSymbolDataFrame, 'Volume', 3).apply(lambda x: int(x) if not pd.isna(x) else x)
        print(filteredSymbolDataFrame.head())
        filteredSymbolDataFrame = strategy.indicatorCalculator.addAdvancesDeclinesIndicator(filteredSymbolDataFrame, 'Close', 'Advance-Decline')

        filteredSymbolDataFrame = Utils.generateDiffChangeFoGivenColumn(filteredSymbolDataFrame, 'Diff', 'Close')
        Utils.set_dataframe_value_for_index_and_columnName(filteredSymbolDataFrame, 0, 'Diff', 0)
        aa = strategy.dataframewindowfilter.get_calendar_month_end_filter_list(filteredSymbolDataFrame)
        bb = strategy.dataframewindowfilter.get_calendar_month_start_filter_list(filteredSymbolDataFrame)
        cc = Utils.create_union_of_two_pylist(aa, bb)
        print(filteredSymbolDataFrame.loc[:, ['Date', 'Close', 'Advance-Decline', 'Diff']])

        ss = Utils.filter_pands_df_column_filter_on_conditionlist(filteredSymbolDataFrame, 'Date', cc)
        print(ss.dtypes)
        #print(ss.loc[:, ['Date', 'Close', 'Advance-Decline', 'Diff', 'YearMonth']])

        #ss['Close_Diff'] = ss.groupby('YearMonth')['Close'].diff()
        #print(ss.loc[:, ['Date', 'Close', 'Advance-Decline', 'Diff', 'YearMonth', 'Close_Diff']])
        
        break
    #   
    # filtered_df.tail(10)
        
    #     # # Extract month and year
    #     filtered_df['Date'] = filtered_df['Date'].dt.tz_localize(None)
    #     filtered_df['YearMonth'] = filtered_df['Date'].dt.to_period('M').copy()
    #     filtered_df
    #     #symbolData.head(3)
    #     #symbolData.tail(3)
        
    #     # Calculate cumulative percentage change for each month
    #     aa = filtered_df.groupby('YearMonth')['Pct_Change'].cumsum()

    #     bb = filtered_df[['YearMonth', 'Pct_Change']]
    #     monthlySum = (bb.groupby('YearMonth').sum())
    #     #print(monthlySum)

    #     monthlySum.loc[:, 'Pct_Change'] = 1+(monthlySum['Pct_Change']/100)
    #     #print(monthlySum)
    #     # Calculate the product of all values in the 'Pct_Change' column
    #     product = float(monthlySum['Pct_Change'].prod()-1)
    #     #print(product)
    #     p[symbol] = (product*100)
    #     #bb.loc[:, 'Pct_Change'] = bb['Pct_Change']+1
    #     #print(p)
    #     #print(bb.groupby('YearMonth').sum())

    
    #     #p[symbol] = float(bb.groupby('YearMonth').sum().sum()['Pct_Change'])

    # #p

    # # Sorting the dictionary by float values
    # sorted_data = dict(sorted(p.items(), reverse=True, key=lambda item: item[1]))
    # sorted_data
    # cc = pd.DataFrame(list(sorted_data.items()), columns=['Stock', 'Return'])
    '''

