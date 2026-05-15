import pandas as pd 
import yfinance as yf
import yfinance
import os
import requests
import numpy as np
from datetime import date, datetime, timedelta
import re
import sys
sys.path.append('/home/qa/BlingTradePlatform/strategy/MomentumLearning/')
sys.path.append('/home/qa/BlingTradePlatform/strategy')
from src.common.constants import *

#import statsmodels.api as sm

def is_valid_date(date_string, date_format="%Y-%m-%d"):
    try:
        datetime.strptime(date_string, date_format)
        return True
    except ValueError:
        return False

'''
'''
def checkIfFileExists(filename):
    return os.path.exists(filename)

"""
    Check if the input date lies between (and includes) the start and end dates.

    Parameters:
    input_date (str): The date to check in 'YYYY-MM-DD' format.
    start_date (str): The start date in 'YYYY-MM-DD' format.
    end_date (str): The end date in 'YYYY-MM-DD' format.

    Returns:
    bool: True if input_date lies between or is equal to start_date and end_date, otherwise False.
"""
def is_date_in_range(input_date, start_date, end_date):

    # Convert string dates to datetime objects
    input_dt = datetime.strptime(input_date, '%Y-%m-%d')
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')

    # Check if the input date is within the range (inclusive)
    return start_dt <= input_dt <= end_dt

"""
    Calculate the difference in days between two dates.
    
    Parameters:
    start_date (str): The start date in 'YYYY-MM-DD' format.
    end_date (str): The end date in 'YYYY-MM-DD' format.
    
    Returns:
    int: The difference in days between the two dates.
"""
def days_difference(start_date, end_date):

    # Convert string dates to datetime objects
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    # Calculate the difference in days
    difference = (end - start).days
    return difference

'''
boolean return if the given string data in YYYY-MM-DD is weekend or not
'''
def is_weekend(date_string):
    # Convert the string to a datetime object
    date = datetime.strptime(date_string, "%Y-%m-%d")
    
    # Check if the day is Saturday (5) or Sunday (6)
    return date.weekday() in (5, 6)


'''
For the given location return the csv file format to a pandas dataframe
'''
def read_csvFile_to_dataframe(fileLocation):
    aa = pd.read_csv(fileLocation)
    return aa

'''
    Calculate dates by adding and subtracting days from the input date.
    
    Args:
        input_date (str): Input date in 'YYYY-MM-DD' format.
        days_to_add (int): Number of days to add.
        days_to_subtract (int): Number of days to subtract.
    
    Returns:
        dict: A dictionary with the calculated future and past dates.
'''
def calculate_dates(input_date, days_to_add, days_to_subtract):

    # Convert input_date string to datetime object
    input_date_obj = datetime.strptime(input_date, "%Y-%m-%d")
    
    # Calculate future and past dates
    future_date = input_date_obj + timedelta(days=days_to_add)
    past_date = input_date_obj - timedelta(days=days_to_subtract)
    
    # Return results as a dictionary
    return {
        "future_date": future_date.strftime("%Y-%m-%d"),
        "past_date": past_date.strftime("%Y-%m-%d")
    }

def get_current_date():
    return datetime.now().strftime("%Y-%m-%d")

'''
Save the given dataframe object to csv format in the location
'''
def save_df_to_csv(df, dirLocation, filename):
    if not os.path.exists(dirLocation + "/" + filename):
        df.to_csv(dirLocation + "/" + filename)

'''
Create Dataframe from python dictionary
'''
def create_Dataframe_From_PyDictionary_ListValues(dictionary):
    return pd.DataFrame(dictionary)

'''
Take the input as dataframe and columnName
and for the given columnName extract the UniqueElements in a series format
'''
def dataFrame_to_uniqueList_for_Column(dataframe, columnName):
    return dataframe[columnName].unique()


'''
Take a Dataframe Series and convert the series to Python List type
'''
def panda_series_toList_converter(dataframeSeries):
    return dataframeSeries.tolist()

'''
For the given symbol name extract the historical price data
from yahoo finance with the given period and interval in string format
e.g 
period : str Valid periods: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max

interval : str Valid intervals: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
Intraday data cannot extend last 60 days
'''
def read_Historical_Data_From_Yf_with_period(symbolName, periodInString, intervalInString):
    try:
        stockTicker = yfinance.Ticker(symbolName)
        df = stockTicker.history(period=periodInString, interval=intervalInString)
        if df.empty:
            print("No data returned, possibly due to invalid parameters.")
        return df

    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

'''
interval : str Valid intervals: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
Intraday data cannot extend last 60 days

start: str Download start date string (YYYY-MM-DD) or _datetime, inclusive.
Default is 99 years ago
E.g. for start="2020-01-01", the first data point will be on "2020-01-01"

end: str Download end date string (YYYY-MM-DD) or _datetime, exclusive.
Default is now
'''
def read_Historical_Data_From_Yf_with_startdate_and_enddate(symbolName, startDateInYYYYMMDD, endDateInYYYYMMDD, intervalInString):
    try:
        stockTicker = yfinance.Ticker(symbolName)
        #df= stockTicker.history(startDateInYYYYMMDD, endDateInYYYYMMDD, intervalInString)
        df = stockTicker.history(interval=intervalInString, start = startDateInYYYYMMDD, end=endDateInYYYYMMDD)
        if df.empty:
            print("No data returned, possibly due to invalid parameters.")
        return df
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None


'''
modify the Yahoo Finance Date Column Series into pandas datetype column Series of
datetime64[ns, UTC+05:30] having datetime and timezone info
'''
def convert_yf_datetime_to_pandas_datetime(dataframe):
    if 'Date' in dataframe.columns:
        dataframe['Date'] = pd.to_datetime(dataframe['Date'])
    elif 'Datetime' in dataframe.columns:
        dataframe['Date'] = pd.to_datetime(dataframe['Datetime'])

    dataframe = dataframe.sort_values(by='Date')
    return dataframe

'''
modify the Yahoo Finance Date Column Series into pandas datetype column Series of
datetime64[ns, UTC+05:30] having datetime using time value
'''
def convert_yf_datetime_to_pandas_time(dataframe):
    if 'Time' in dataframe.columns:
        dataframe['Time'] = pd.to_datetime(dataframe['Time'])
    
    return dataframe

'''
Convert Pandas datetime64 series formatString into a user specified format(python datetime)
format e.g '%d-%m-%Y'
'''
def convert_datetime64_to_user_format(pandaSeries, formatString):
    return pandaSeries.dt.strftime(formatString)

'''
Filter pandas dataframe for the given column within the given range filter
[rangeStart, rangeEnd]
for e.g Filter pandas dataframe Datetime (in datetime64 ) format between 
given start_date and end_date ...Example below 
    rangeStart = '2024-03-07'
    rangeEnd = '2024-08-31'
'''
def filter_panda_df_in_range_constraint(dataframe, columnName, rangeStart, rangeEnd):
    return dataframe[(dataframe[columnName] >= rangeStart) & (dataframe[columnName] <= rangeEnd)].copy()

'''
Filter pandas dataframe wrt specifi column condition
'''
def filter_pands_df_column_filter(dataframe, columnName, filterConditionValue):
    return dataframe[dataframe[columnName] == filterConditionValue]

    """
    Filter the DataFrame based on a list of values for a specified column.
    
    Parameters:
    dataframe: pd.DataFrame - The DataFrame to filter.
    columnName: str - The column name to apply the filter on.
    filterConditionList: list - The list of values to filter by.
    
    Returns:
    pd.DataFrame - The filtered DataFrame.
    """
def filter_pands_df_column_filter_on_conditionlist(dataframe, columnName, filterConditionList):
    # Filter the DataFrame based on the condition list
    filtered_df = dataframe[dataframe[columnName].isin(filterConditionList)]
    return filtered_df



'''
Create a Pandas Series With Percentage Change for the given
input series with the given columnName having float/int values
columnToAdd -> Is the new column Name which has to added which stores output
columnName -> Is the input column in the dataframe against which pct_change is applied
Return panda dataframe
'''

'''
Create a Pandas Series With Diff Change for the given
input series with the given columnName having float/int values
columnToAdd -> Is the new column Name which has to added which stores output
columnName -> Is the input column in the dataframe against which diff() is applied
Return panda dataframe
'''
def generatePctChangeForGivenColumn(dataFrame, columnToAdd, columnName):
    dataFrame[columnToAdd] = dataFrame[columnName].pct_change() * 100
    return dataFrame

def generateDiffChangeFoGivenColumn(dataFrame, columnToAdd, columnName):
    dataFrame[columnToAdd] = dataFrame[columnName].diff()
    return dataFrame


'''
Remove TimeZone Info from the DateTime64 Series ColumnName
'''
def remove_timeZoneInfo_from_datetime(dataFrame, columnName):
    dataFrame[columnName]  = dataFrame[columnName].dt.tz_localize(None)
    return dataFrame

'''
Get the Year and Month from the panda Datetime Series Column
Example 2024-09-14 will result in 2024-08
'''
def convert_datetime_to_yearmonth(dataframe, columnName):
    return dataframe[columnName].dt.to_period('M').copy()

'''
Get the given column rolling mean over the specified dataframe column and return series
'''
def get_rollingmean_to_column(dataframe, columnName, window):
    return dataframe[columnName].rolling(window=window).mean()

 
'''
Return the product of all elements in Series
'''
def get_product_of_series_date(dataframe, columnName):
    return dataframe[columnName].prod()


'''
Gives Size of dataframe
'''
def get_dataframe_size(dataframe):
    return dataframe.shape[0]

'''
Sets a given value for the dataframe for an index and column
rowNumber -> Given row index
columnName -> given column label
'''
def set_dataframe_value_for_index_and_columnName(dataframe, rowNumber, columnName, value):
    ind = dataframe.index[rowNumber]
    dataframe.loc[ind, columnName] = value
    return dataframe

'''
Sets a given value for the dataframe for conditional value of the given column
cond -> Given condition when its true
columnName -> given column label
'''
def set_dataframe_value_for_index_and_columnName_for_conditionalCheck(dataframe, cond, columnName, value):
    sz = get_dataframe_size(dataframe)
    for i in range(sz):
        index = dataframe.index[i]
        if dataframe.loc[index, columnName] == cond:
            dataframe.loc[index, columnName] = value
    
    return dataframe

'''
Remove column from dataframe
'''
def remove_dataframe_column(dataframe, columnName):
    dataframe = dataframe.drop(columns=[columnName])  # Drop the specified column
    return dataframe

'''
For a given dictionary return the dictionary in a sorted way
in descending order(reverse=True) and sorting in the value of the elements
'''
def return_sorted_dictionary_from_dict(dictionary, descending=True):
    return dict(sorted(dictionary.items(), reverse = descending, key=lambda item: item[1]))

'''
Create the 2 series dataframe from the given python dictionary
'''
def create_df_from_pydictionary(dictionary):
    columnList = list(dictionary.keys())
    return pd.DataFrame(list(dictionary.items()), columns=columnList)

'''
Merge Two dataframe based on certain column condition value
'''
def get_intersection_of_two_dataframe(df1, df2, columnName, condition):
    pd.merge(df1[df1[columnName] == condition], df2[df2[columnName] == condition], on=columnName)

'''
Get the dataframe with given integer index  values
'''
def get_dataframe_rows_with_index_range(df1, indexRange1, indexRange2):
    df1.iloc[indexRange1:indexRange2, :]

'''
Get the dataframe with given index label values
'''
def get_dataframe_rows_with_labelindex_range(df1, label1, label2):
    df1.loc[label1:label2, :]

'''
Filter dataframe with given column labels list
e.g     a	b
    0	12	34
    1	23	33

    df.loc[:, ['b']] will result in 
    	b
    0	34
    1	33
'''
def get_dataframe_with_columnlabel_list(df, columnList):
    df.loc[:, columnList]

def dropAllNan_Row_Entries_InDataframe(df):
    df.dropna()


def add_row_to_dataframe(df, row_values):
    """
    Adds a new row to an existing DataFrame.

    Parameters:
    df (pd.DataFrame): The DataFrame to which the row will be added.
    row_values (dict): A dictionary where keys are column names and values are the row values.

    Returns:
    pd.DataFrame: The DataFrame with the new row added.
    """
    # Convert the dictionary to a DataFrame and append it
    new_row = pd.DataFrame([row_values])
    
    # Append the new row to the existing DataFrame and reset the index
    df = pd.concat([df, new_row], ignore_index=True)
    
    return df

def find_current_directory():
    return os.path.dirname(os.path.abspath(__file__))

def createDirectory(pathDirectory):
    # Define the path to the new directory
    directory_path = pathDirectory
    # Create the directory
    try:
        os.makedirs(directory_path, exist_ok=True)
        print(f"Directory created: {directory_path}")
    except OSError as e:
        print(f"Error creating directory: {e}")

'''
Download the symbols from Yahoo and store in the given directory
with the specified format...Also Put the period and interval in the input
for the date range and intervals for which the data has to be downloaded
'''
def download_Mkt_Data_For_Symbols_And_SaveFilesToDirectory(symbolList, periodInString, intervalInString, dirname, format):
    for i in range (len(symbolList)):
        currentSymbol = symbolList[i] + ".NS"
        if os.path.exists(dirname + "/" + currentSymbol + format):
            return
        stockHistoricalDf = read_Historical_Data_From_Yf_with_period(symbolName=currentSymbol, periodInString=periodInString, intervalInString=intervalInString)
        if stockHistoricalDf.empty == False:
            save_df_to_csv(stockHistoricalDf, dirname, currentSymbol + format)
        else:
            print ("The symbol " + currentSymbol + " doesnt have historical data")


def read_Csv_for_backtesting_input(filename):
    from os.path import dirname, join

    return pd.read_csv(join(dirname(__file__), filename),
                       index_col=0, parse_dates=True, infer_datetime_format=True)



def download_Mkt_Data_For_Symbols_With_Start_And_EndDate_With_Granularity_And_SaveFilesToDirectory(symbolList, start_date, end_date, granularity, dirname, format):
    
    parent_dir = dirname  + granularity
    createDirectory (parent_dir)

    for i in range (len(symbolList)):
        currentSymbol = symbolList[i] + ".NS"
        
        #1d,5d,1mo,3mo,6mo,1y,2y,5y,10y
        days_interval = days_difference(start_date, end_date) + 1
        if days_interval < 0:
            print("Start Date is greater than end date>>>>Please provide right input in YYYY-MM-DD formats")
            return
            
            
        periodToCalculate = days_interval
        if granularity == "2m" or granularity == "5m" or granularity == "15m" or granularity == "30m" or granularity == "60m":
            # you can only max collect last 60 days data from today's current date
            max_lookback_date = calculate_dates(get_current_date(), 59, 59)['past_date']

            if is_date_in_range(start_date, max_lookback_date, get_current_date()) == False or is_date_in_range(end_date, max_lookback_date, get_current_date()) == False:
                print("We can only get the given granularity of [" + granularity + "]" + 
                  "from max_lookback_period [" + max_lookback_date + "] to [" + get_current_date() + "]" )
                return
            if days_interval > 59:
                periodToCalculate = 59
        elif granularity == "1m":
            # you can only max collect last 60 days data from today's current date
            max_lookback_date = calculate_dates(get_current_date(), 29, 29)['past_date']
            if is_date_in_range(start_date, max_lookback_date, get_current_date()) == False or is_date_in_range(end_date, max_lookback_date, get_current_date()) == False:
                print("We can only get the given granularity of [" + granularity + "]" + 
                  "from max_lookback_period [" + max_lookback_date + "] to [" + get_current_date() + "]" )
                return
            if days_interval > 30:
                periodToCalculate = 29
        
        
        initialDate = start_date
        endDate = calculate_dates(end_date, 1, 1)['future_date']
        
        while initialDate != endDate:
            stockHistoricalDf = pd.DataFrame()
            lookAheadPeriod = 1
            starting_date = initialDate
            ending_date = calculate_dates(initialDate, lookAheadPeriod, lookAheadPeriod)['future_date']
           
            filePath = parent_dir + "/" + currentSymbol + "_" +  initialDate + format
            if os.path.exists(filePath) == True or is_weekend(initialDate):
                initialDate = ending_date
                continue
            
            stockHistoricalDf = read_Historical_Data_From_Yf_with_startdate_and_enddate(currentSymbol, starting_date,
                                    ending_date, granularity)                    

        
            if stockHistoricalDf.empty == False:
                save_df_to_csv(stockHistoricalDf, parent_dir, currentSymbol + "_" +  initialDate + format)
            else:
                print ("The symbol " + currentSymbol + " doesnt have historical data for date [" + initialDate + "]")
            
            initialDate = ending_date


'''
Download the symbols from Yahoo with the given granularity and store in the given directory
with the specified format...Also Put the period and interval in the input
for the date range and intervals for which the data has to be downloaded
'''
def download_Mkt_Data_For_Symbols_With_Granularity_And_SaveFilesToDirectory(symbolList, start_date, granularity, periodInString, dirname, format):
    
    parent_dir = dirname  + granularity
    createDirectory (parent_dir)
    #dirToDownload = dirname + "/" + granularity + "_" + start_date
    #createDirectory( dirToDownload )

    for i in range (len(symbolList)):
        currentSymbol = symbolList[i] + ".NS"
        # fileName = dirToDownload + "/" + currentSymbol + format
        # if os.path.exists(fileName):
        #     return
        
        #1d,5d,1mo,3mo,6mo,1y,2y,5y,10y
        period = 1
        numeric_value = -1
        character_part = "d"
        match = re.match(r"(\d+)([a-zA-Z]+)", periodInString)
        if match:
            numeric_value = int(match.group(1))  # First group: the numeric part
            character_part = match.group(2)  # Second group: the character part
            print(f"Numeric: {numeric_value}, Character: {character_part}")
        else:
            print(f"Invalid format: {periodInString}")
            return

        if numeric_value == -1: 
            print(f"Invalid format: {periodInString}")
            return
            
        if character_part == 'y':
            period = 363 * numeric_value 
        
        if character_part == "mo":
            period = 30 * numeric_value
            
        if character_part == "d":
            period = 1 * numeric_value
            
            
        periodToCalculate = period
        if granularity == "2m" or granularity == "5m" or granularity == "15m" or granularity == "30m" or granularity == "60m":
            # you can only max collect last 60 days data from today's current date
            if period > 59:
                periodToCalculate = 59
        elif granularity == "1m":
            # you can only max collect last 60 days data from today's current date
            if period > 30:
                periodToCalculate = 29
        
        
        initialDate = start_date
        endDate = calculate_dates(start_date, period, period)['past_date']
        
        while initialDate != endDate:
            stockHistoricalDf = pd.DataFrame()
            lookBackPeriod = 1
            starting_date = initialDate
            end_date = calculate_dates(initialDate, lookBackPeriod, lookBackPeriod)['future_date']
            next_date = calculate_dates(initialDate, lookBackPeriod, lookBackPeriod)['past_date']
            # if granularity != "1m":
            #     stockHistoricalDf = read_Historical_Data_From_Yf_with_startdate_and_enddate(currentSymbol, start_date,
            #                                 end_date, granularity)
            # elif granularity == "1m":
            filePath = parent_dir + "/" + currentSymbol + "_" +  initialDate + format
            if os.path.exists(filePath) == True or is_weekend(initialDate):
                initialDate = next_date
                continue
            
            stockHistoricalDf = read_Historical_Data_From_Yf_with_startdate_and_enddate(currentSymbol, starting_date,
                                    end_date, granularity)                    
                    #stockHistoricalDf = pd.concat([stockHistoricalDf, read_Historical_Data_From_Yf_with_startdate_and_enddate(currentSymbol, start_date,
                            #end_date, granularity)])
        
            if stockHistoricalDf.empty == False:
                save_df_to_csv(stockHistoricalDf, parent_dir, currentSymbol + "_" +  initialDate + format)
            else:
                print ("The symbol " + currentSymbol + " doesnt have historical data for date [" + initialDate + "]")
            
            initialDate = next_date



def download_Mkt_Data_For_Symbols_With_Start_And_EndDate_With_Granularity_And_SaveFilesToDirectory(symbolList, start_date, end_date, granularity, dirname, format):
    
    parent_dir = dirname  + granularity
    createDirectory (parent_dir)

    for i in range (len(symbolList)):
        currentSymbol = symbolList[i] + ".NS"
        
        #1d,5d,1mo,3mo,6mo,1y,2y,5y,10y
        days_interval = days_difference(start_date, end_date) + 1
        if days_interval < 0:
            print("Start Date is greater than end date>>>>Please provide right input in YYYY-MM-DD formats")
            return
            
            
        periodToCalculate = days_interval
        if granularity == "2m" or granularity == "5m" or granularity == "15m" or granularity == "30m" or granularity == "60m":
            # you can only max collect last 60 days data from today's current date
            max_lookback_date = calculate_dates(get_current_date(), 59, 59)['past_date']

            if is_date_in_range(start_date, max_lookback_date, get_current_date()) == False or is_date_in_range(end_date, max_lookback_date, get_current_date()) == False:
                print("We can only get the given granularity of [" + granularity + "]" + 
                  "from max_lookback_period [" + max_lookback_date + "] to [" + get_current_date() + "]" )
                return
            if days_interval > 59:
                periodToCalculate = 59
        elif granularity == "1m":
            # you can only max collect last 60 days data from today's current date
            max_lookback_date = calculate_dates(get_current_date(), 29, 29)['past_date']
            if is_date_in_range(start_date, max_lookback_date, get_current_date()) == False or is_date_in_range(end_date, max_lookback_date, get_current_date()) == False:
                print("We can only get the given granularity of [" + granularity + "]" + 
                  "from max_lookback_period [" + max_lookback_date + "] to [" + get_current_date() + "]" )
                return
            if days_interval > 30:
                periodToCalculate = 29
        
        
        initialDate = start_date
        endDate = calculate_dates(end_date, 1, 1)['future_date']
        
        while initialDate != endDate:
            stockHistoricalDf = pd.DataFrame()
            lookAheadPeriod = 1
            starting_date = initialDate
            ending_date = calculate_dates(initialDate, lookAheadPeriod, lookAheadPeriod)['future_date']
           
            filePath = parent_dir + "/" + currentSymbol + "_" +  initialDate + format
            if os.path.exists(filePath) == True or is_weekend(initialDate):
                initialDate = ending_date
                continue
            
            stockHistoricalDf = read_Historical_Data_From_Yf_with_startdate_and_enddate(currentSymbol, starting_date,
                                    ending_date, granularity)                    

        
            if stockHistoricalDf.empty == False:
                save_df_to_csv(stockHistoricalDf, parent_dir, currentSymbol + "_" +  initialDate + format)
            else:
                print ("The symbol " + currentSymbol + " doesnt have historical data for date [" + initialDate + "]")
            
            initialDate = ending_date

'''
Dwonload Utility without Start and End Date for a given granularity
'''
def download_Mkt_Data_For_Symbols_Without_Start_And_EndDate_With_Granularity_And_SaveFilesToDirectory(symbolList, granularity, dirname, format):
    start_date = calculate_dates(get_current_date(), 14, 14)['past_date']
    end_date  = get_current_date()

    parent_dir = dirname  + granularity
    createDirectory (parent_dir)

    for i in range (len(symbolList)):
        currentSymbol = symbolList[i] + ".NS"
        
        #1d,5d,1mo,3mo,6mo,1y,2y,5y,10y            
        periodToCalculate = 1000
        if granularity == "2m" or granularity == "5m" or granularity == "15m" or granularity == "30m" or granularity == "60m":
            # you can only max collect last 60 days data from today's current date
            start_date = calculate_dates(get_current_date(), 50, 50)['past_date']
            periodToCalculate = 50
        
        elif granularity == "1m":
            # you can only max collect last 60 days data from today's current date
            start_date = calculate_dates(get_current_date(), 29, 29)['past_date']
            periodToCalculate = 29
        else:
            periodToCalculate = days_difference(start_date, end_date) + 1

        
        
        initialDate = start_date
        endDate = calculate_dates(end_date, 1, 1)['future_date']
        
        while initialDate != endDate:
            stockHistoricalDf = pd.DataFrame()
            lookAheadPeriod = 1
            starting_date = initialDate
            ending_date = calculate_dates(initialDate, lookAheadPeriod, lookAheadPeriod)['future_date']
           
            filePath = parent_dir + "/" + currentSymbol + "_" +  initialDate + format
            if os.path.exists(filePath) == True or is_weekend(initialDate):
                initialDate = ending_date
                continue
            
            stockHistoricalDf = read_Historical_Data_From_Yf_with_startdate_and_enddate(currentSymbol, starting_date,
                                    ending_date, granularity)                    

        
            if stockHistoricalDf.empty == False:
                save_df_to_csv(stockHistoricalDf, parent_dir, currentSymbol + "_" +  initialDate + format)
            else:
                print ("The symbol " + currentSymbol + " doesnt have historical data for date [" + initialDate + "]")
            
            initialDate = ending_date


def download_market_data(symbol_list, granularity, directory, file_extension, start_date=None, end_date=None):
    """
    Downloads market data for each symbol in `symbol_list` with the specified `granularity`
    and saves the results to CSV files in a designated directory.

    For granularity "1d":
        - Both start_date and end_date (in "YYYY-MM-DD" format) must be provided.
    For all other granularities:
        - end_date is automatically set to today's date.
        - start_date is optional; if not provided, it defaults to the maximum allowed lookback period.
          If provided and it is earlier than the allowed lookback date, it is adjusted accordingly.

    Parameters:
        symbol_list (list): List of symbol strings (without any exchange suffix).
        granularity (str): Data granularity. Supported values include "1d", "1m", "2m", "5m", "15m", "30m", "60m".
        directory (str): Base directory where the files will be saved.
        file_extension (str): File extension for the saved files (e.g., ".csv").
        start_date (str, optional): Start date in "YYYY-MM-DD" format.
        end_date (str, optional): End date in "YYYY-MM-DD" format.
    """
    # Create output directory (append granularity as subfolder)
    output_dir = os.path.join(directory, granularity)
    createDirectory(output_dir)
    
    # Get today's date as a date object.
    today_dt = date.today()
    
    # For "1d" granularity, both dates must be provided.
    if granularity == "1d":
        if start_date is None or end_date is None:
            raise ValueError("For '1d' granularity, start_date and end_date must be provided.")
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    else:
        # For non-daily granularities, force end_date to today.
        end_dt = today_dt
        
        # Define allowed lookback limits (in days) for non-daily granularities.
        # For example: For "1m", a maximum of 30 days is allowed;
        # for "2m", "5m", "15m", "30m", and "60m", a maximum of 60 days is allowed.
        lookback_limits = {
            "1m": 30,
            "2m": 60,
            "5m": 60,
            "15m": 60,
            "30m": 60,
            "60m": 60
        }
        
        days_allowed = lookback_limits.get(granularity, 60)
        allowed_start_dt = end_dt - timedelta(days=days_allowed - 1)
        
        if start_date is None:
            start_dt = allowed_start_dt
        else:
            # Convert provided start_date to date object.
            provided_start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            # Adjust start_dt if provided value exceeds allowed lookback.
            if provided_start_dt < allowed_start_dt:
                print(f"For granularity '{granularity}', the maximum allowed lookback period is "
                      f"{days_allowed} days. Adjusting start_date from {provided_start_dt} "
                      f"to {allowed_start_dt}.")
                start_dt = allowed_start_dt
            else:
                start_dt = provided_start_dt

    # Ensure that start_dt is not later than end_dt.
    if start_dt > end_dt:
        raise ValueError("start_date cannot be later than end_date.")

    # Compute the final date for iteration: one day after end_dt.
    final_dt = end_dt + timedelta(days=1)

    # Process each symbol.
    for symbol in symbol_list:
        # Append exchange suffix.
        symbol_with_suffix = f"{symbol}.NS"
        current_dt = start_dt
        
        while current_dt < final_dt:
            # Compute next day.
            next_dt = current_dt + timedelta(days=1)
            # Format dates back to string.
            current_date_str = current_dt.strftime("%Y-%m-%d")
            next_date_str = next_dt.strftime("%Y-%m-%d")
            
            # Construct file name and full file path.
            file_name = f"{symbol_with_suffix}_{current_date_str}{file_extension}"
            file_path = os.path.join(output_dir, file_name)
            
            # Skip download if the file already exists.
            if os.path.exists(file_path) or is_weekend(current_date_str):
                current_dt = next_dt
                continue
            
            # Download historical data for the current day.
            df_historical = read_Historical_Data_From_Yf_with_startdate_and_enddate(
                symbol_with_suffix, current_date_str, next_date_str, granularity
            )
            
            if not df_historical.empty:
                save_df_to_csv(df_historical, output_dir, file_name)
            else:
                print(f"No historical data for {symbol_with_suffix} on {current_date_str}.")
            
            # Move to the next day.
            current_dt = next_dt


'''
'''
def readCsv(symbol, granularity, start_date, dirname, format,  periodInString):
    period = 1
    numeric_value = -1
    character_part = "d"
    match = re.match(r"(\d+)([a-zA-Z]+)", periodInString)
    if match:
        numeric_value = int(match.group(1))  # First group: the numeric part
        character_part = match.group(2)  # Second group: the character part
        print(f"Numeric: {numeric_value}, Character: {character_part}")
    else:
        print(f"Invalid format: {periodInString}")
        return

    if numeric_value == -1: 
        print(f"Invalid format: {periodInString}")
        return
        
    if character_part == 'y':
        period = 363 * numeric_value 
    
    if character_part == "mo":
        period = 30 * numeric_value
        
    if character_part == "d":
        period = 1 * numeric_value

    startDate = calculate_dates(start_date, period, period)['past_date']
    endDate = calculate_dates(start_date, 1, 1)['future_date']
    parent_dir = dirname + granularity + "/"
    symbolDataFrame = pd.DataFrame()
    while startDate != endDate:
        stockDataFrame = pd.DataFrame()
        filePath = parent_dir + symbol + ".NS_" +  startDate + format
        if os.path.exists(filePath) == False:
            startDate = calculate_dates(startDate, 1, 1)['future_date']
            continue
        stockDataFrame = pd.read_csv(filePath)
        if stockDataFrame.empty == False:
            symbolDataFrame = pd.concat([symbolDataFrame, stockDataFrame])
        
        startDate = calculate_dates(startDate, 1, 1)['future_date']
    
    return symbolDataFrame

def readCsv_from_startdate_enddate(symbol, granularity, start_date, end_date,  dirname, format, dirToCheck = ''):
    if is_valid_date(start_date) == False or  is_valid_date(end_date) == False:
        print("Inpuuted start/end date is incorrect")
        return
    # Check if directory exists with a given path
    dirToCheck = '/home/qa/runtime/data/historicMktData/strategy_data_local/'
    if dirToCheck != '':
        if os.path.exists(dirToCheck + granularity):
            #print(f"Directory exist: {dirname} and reading from there")
            if os.path.exists(dirToCheck + granularity + "/" + symbol + "_" + start_date + "-" + end_date):
                return pd.read_csv(dirToCheck + granularity + "/" + symbol + "_" + start_date + "-" + end_date)
        else:
            print(f"Directory doesnt exist: {dirToCheck + granularity} and creating directory")
            createDirectory(dirToCheck + granularity)
            
    period = 1
    # check upto what oldest start_date and newest end_date the data has been saved already for the symbol
    required_columns = ["Date", "Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"]

    # find all files in the directory having symbol as prefix
    files = [f for f in os.listdir(dirToCheck + granularity) if f.startswith(symbol)]
    # iterate through the files and find the oldest start_date and newest end_date such that files in the directory have names
    # with values symbol_start_date-end_date with start_date and end_date in YYYY-MM-DD format
    date_ranges = []
    for f in files:
        # Expecting file names like SYMBOL_YYYY-MM-DD-YYYY-MM-DD
        match = re.match(rf"{re.escape(symbol)}_(\d{{4}}-\d{{2}}-\d{{2}})-(\d{{4}}-\d{{2}}-\d{{2}})", f)
        if match:
            file_start = match.group(1)
            file_end = match.group(2)
            # add code to have oldest file_start and newest file_end
            date_ranges.append((file_start, file_end))
    # date_ranges will now contain tuples of (start_date, end_date) for each file now
    # sort above tuple of list in ascending order of file_start date value
    date_ranges.sort(key=lambda x: x[0])
    startDate = None
    endDate = None
    symbolDataFrame = pd.DataFrame()
    if date_ranges:
        oldest_start_date = date_ranges[0][0]
        if start_date >= oldest_start_date:
            startDate = oldest_start_date
            current_end_date = date_ranges[0][1]
            for file_start, file_end in date_ranges:
                if file_start == startDate and file_end >= current_end_date:
                    endDate = file_end
    
   # if startDate is not None and endDate is not None:
    if startDate != None and endDate != None:
        if endDate >= end_date:
            return pd.read_csv(dirToCheck + granularity + "/" + symbol + "_" + startDate + "-" + endDate)
        symbolDataFrame = pd.read_csv(dirToCheck + granularity + "/" + symbol + "_" + startDate + "-" + endDate)
        symbolDataFrame = symbolDataFrame[[col for col in required_columns if col in symbolDataFrame.columns]]
        symbolDataFrame.reset_index(drop=True, inplace=True)
        startDate = calculate_dates(endDate, 1, 1)['future_date']

    
    if startDate == None:
        startDate = start_date
        
    endDate = calculate_dates(end_date, 1, 1)['future_date']
    parent_dir = dirname + granularity + "/"
 
    
    while startDate != endDate:
        stockDataFrame = pd.DataFrame()
        filePath = parent_dir + symbol + ".NS_" +  startDate + format
        if os.path.exists(filePath) == False:
            startDate = calculate_dates(startDate, 1, 1)['future_date']
            continue
        stockDataFrame = pd.read_csv(filePath)
        stockDataFrame = stockDataFrame[required_columns]
        stockDataFrame.reset_index(drop=True, inplace=True)

        if stockDataFrame.empty == False:
            symbolDataFrame = pd.concat([symbolDataFrame, stockDataFrame])
        
        startDate = calculate_dates(startDate, 1, 1)['future_date']
    
    # save the symbolDataframe to csv
    symbolDataFrame.to_csv(dirToCheck + granularity + "/" + symbol + "_" + start_date + "-" + end_date)
    return symbolDataFrame

'''
Create a union using set
'''
def create_union_of_two_pylist(list1, list2):
    union_list = list(set(list1) | set(list2))
    return union_list


def get_mean_of_dataFrameSeries(dataframe, columnName):
    N = get_dataframe_size(dataframe)
    
    columnPyList = panda_series_toList_converter(dataframe[columnName])
    sum_of_values = np.sum(columnPyList)
    
    return (sum_of_values*1.0)/N

def get_std_deviation_of_df_series(dataframe, columnName):
    N = get_dataframe_size(dataframe)
    
    columnPyList = panda_series_toList_converter(dataframe[columnName])
    return np.std(columnPyList)

'''
column1 refers to the asset prices vector
column2 refers to the overall market price vector
'''
def covariance_x_y(dataframe, column1, column2):
    
    x = np.array(panda_series_toList_converter(dataframe[column1]))
    y = np.array(panda_series_toList_converter(dataframe[column2]))
    covariance = np.cov(x, y)
    return (covariance[0,1]/get_std_deviation_of_df_series(dataframe, column2))

'''
Useful for curent Volumn Z Score 
Higher Z Score for near values penalises moemntum value trend
'''
def get_Z_Score(dataframe, currentValueListForZScore, column1):
    zScoreList = []
    for value in currentValueListForZScore:
        zScoreList.append(((value - get_mean_of_dataFrameSeries(dataframe, column1))*1.0)/get_std_deviation_of_df_series(dataframe, column1))
    
    return np.mean(zScoreList)

'''
column 1 is like market return list
column2 is like individual stock return list
'''
def get_linear_regression_coefficients(dataframe, column1, column2, beta):
    # Example data: y (dependent variable), X (independent variable)
    
    X = np.array(panda_series_toList_converter(dataframe[column1]))
    y = np.array(panda_series_toList_converter(dataframe[column2]))

    # Known beta
    beta_i = beta  # Example beta value

    # Compute alpha and residual (error terms)
    # Fit regression: r_i = alpha + beta * r_m
    # Rearranging the formula to calculate alpha:
    alpha_i = np.mean(Y) - beta_i * np.mean(X)

    # Calculate the error terms (residuals)
    epsilon_i = y - (alpha_i + beta_i * X)

    return {'alpha' : alpha_i, 'error' : epsilon_i}

def downloadYFinanceDataAndSaveToFilesin1DFormatInCsv(symbolList, period, interval, dirname):
    for symbol in symbolList:
        symbolTicker  = yf.Ticker(symbol+ ".NS").history(period=period, interval=interval)
        symbolTicker.reset_index(inplace=True)
        
        symbolTicker["Date"] = pd.to_datetime(symbolTicker["Date"])

        # Save each row as a separate CSV file
        for _, row in symbolTicker.iterrows():
            date_str = row["Date"].strftime("%Y-%m-%d")  # Format date as YYYY-MM-DD
            file_path = dirname + "1d/" + symbol +  ".NS_" + date_str + ".csv"
            # Convert single row to DataFrame and save to CSV
            row_df = pd.DataFrame([row])  # Convert Series to DataFrame
            row_df.set_index("Date", inplace=True)  # Set Date as index

            if not os.path.exists(file_path):
                row_df.to_csv(file_path, index=True)


# from above symbolDataframe only keep the entries which are filterTypeDays rows apart from each other
def filter_dataframe_by_days(dataframe, filterTypeDays, columnList=['Date', 'High', 'Low', 'Open', 'Volume', 'Close']):
    # Create a copy with only the specified columns
    # create dataframeToProcess with only the columns in columnList
    dataframeToProcess = dataframe[columnList].copy()
    columns_to_process = set(columnList)

    if 'High' in columns_to_process and 'High' in dataframeToProcess.columns:
        dataframeToProcess['High'] = dataframeToProcess['High'].rolling(window=filterTypeDays).max()
    if 'Low' in columns_to_process and 'Low' in dataframeToProcess.columns:
        dataframeToProcess['Low'] = dataframeToProcess['Low'].rolling(window=filterTypeDays).min()
    if 'Open' in columns_to_process and 'Open' in dataframeToProcess.columns:
        dataframeToProcess['Open'] = dataframeToProcess['Open'].shift(filterTypeDays)
    if 'Volume' in columns_to_process and 'Volume' in dataframeToProcess.columns:
        dataframeToProcess['Volume'] = dataframeToProcess['Volume'].rolling(window=filterTypeDays).sum()

    filtered_dataframe = dataframeToProcess.iloc[::filterTypeDays].copy()
    filtered_dataframe.dropna(inplace=True)
    
    return filtered_dataframe
    