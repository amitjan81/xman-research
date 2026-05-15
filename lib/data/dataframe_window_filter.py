from lib.data import utils as Utils
import pandas as pd
import yfinance as yf
import requests
import json
import os

class DataWindowFilter:
    def __init__(self) -> None:
        pass
    
    def get_calendar_month_end_filter_list(df):
        # Extract month and year to group by them
        df['Month'] = df['Date'].dt.to_period('M')
        
        # Get the last date for each month present in the dataset
        last_dates = df.groupby('Month')['Date'].max().reset_index()
        df = Utils.remove_dataframe_column(df, 'Month')
        return last_dates['Date'].dt.date.tolist()

    def get_calendar_month_start_filter_list(df):
        # Extract month and year to group by them
        df['Month'] = df['Date'].dt.to_period('M')
        
        # Get the last date for each month present in the dataset
        last_dates = df.groupby('Month')['Date'].min().reset_index()
        df = Utils.remove_dataframe_column(df, 'Month')
        return last_dates['Date'].dt.date.tolist()