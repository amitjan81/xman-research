from lib.data import utils as Utils
import pandas as pd
import yfinance as yf
import requests
import json
import os




class IndicatorAdder:
    def __init__(self) -> None:
        pass
    
    def indicator1(self):
        pass
    
    def addAdvancesDeclinesIndicator(self, dataframe, indicatorColumn, newColumnValue):
        dataframe[newColumnValue] = None
        for i in range(Utils.get_dataframe_size(dataframe)):
            print(i)
            if i == 0:
                dataframe.loc[dataframe.index[i], newColumnValue] = 0
            else:
                diff = dataframe.loc[dataframe.index[i], indicatorColumn] - dataframe.loc[dataframe.index[i-1], indicatorColumn]
                if diff > 0:
                    dataframe.loc[dataframe.index[i], newColumnValue] = 1
                elif diff < 0:
                    dataframe.loc[dataframe.index[i], newColumnValue] = -1
                else:
                    dataframe.loc[dataframe.index[i], newColumnValue] = 0
        return dataframe