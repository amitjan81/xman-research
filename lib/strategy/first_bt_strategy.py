import os
import sys
import yfinance as yf
import numpy as np

from backtesting import Strategy
from backtesting.lib import crossover
from backtesting import Backtest
from hurst import compute_Hc


import datetime
import pandas as pd


def computeHc(ts, max_lag=20):
    """Compute the Hurst Exponent of the time series vector ts"""
    H, _, _ = compute_Hc(ts)
    # return hurst_exponent
    return H


def SMA(values, n):
    """
    Return simple moving average of `values`, at
    each step taking into account `n` previous values.
    """
    #return pd.Series(values).rolling(n).mean()
    return pd.Series(values).ewm(span=n, adjust=False).mean()

def SMA2(values, n):
    """
    Return simple moving average of `values`, at
    each step taking into account `n` previous values.
    """
    return pd.Series(values).rolling(n).mean()

def ONESTD(values, n):
    """
    Return simple moving average of `values`, at
    each step taking into account `n` previous values.
    """
    #return pd.Series(values).rolling(n).mean()
    return (pd.Series(values).rolling(n).std() +  pd.Series(values).rolling(n).mean())

def TWOSTD(values, n):
    """
    Return simple moving average of `values`, at
    each step taking into account `n` previous values.
    """
    #return pd.Series(values).rolling(n).mean()
    return (pd.Series(values).rolling(n).std() * 2 +  pd.Series(values).rolling(n).mean())

def MINUSTWOSTD(values, n):
    """
    Return simple moving average of `values`, at
    each step taking into account `n` previous values.
    """
    #return pd.Series(values).rolling(n).mean()
    
    return (pd.Series(values).rolling(n).mean() - pd.Series(values).rolling(n).std() * 2)

def hurst_exp(values, n):
    
    hurst_exp = (pd.Series(values).rolling(n).apply(lambda x: computeHc(x, max_lag=50), raw=True))
    
    return hurst_exp

def Volume(bs):
    return pd.Series(bs)

class SmaCross(Strategy):
    # Define the two MA lags as *class variables*
    # for later optimization
    n1 = 20
    n2 = 20
    n3 = 101
    
    def init(self):
        # Precompute the two moving averages
        #self.sma1 = self.I(SMA, self.data.Close, self.n1)
        #self.sma2 = self.I(SMA2, self.data.Close, self.n2)
        self.volume = self.I(Volume, self.data.Volume)
        self.SMA = self.I(SMA, self.data.Close, self.n1)
        ##self.onestdp = self.I(ONESTD, self.data.Close, self.n2)
        self.twostdp = self.I(TWOSTD, self.data.Close, self.n2)
        self.minustwostdp = self.I(MINUSTWOSTD, self.data.Close, self.n2)
        self.hurstexp = self.I(hurst_exp, self.data.Close, self.n3)

    def next(self):
        pass
        # if (self.volume[-1] > 1000000) and (self.position.size) == 0:
        #     print (self.volume[-1])
        #     print("Buying")
        #     self.buy()
        # elif (self.position.size) > 0:
        #     print("Selling")
        #     self.position.close()
        #print(self.bs[-1])
        # print(self.bs)
        # print(self.sma1[-1])
        # if self.bs[-1] == 1:
        #     self.position.close()
        #     self.buy()
        # elif self.bs[1] == -1:
        #     self.position.close()
        #     self.sell()
        # If sma1 crosses above sma2, close any existing
        # short trades, and buy the asset
        
        # if ((self.sma2[-1] -self.sma1[-1])/self.sma2[-1]) > 0.04 and (self.sma1[-1] > self.sma1[-2]):
        #     print(self.orders)
        #     print(self.position)
        #     if (self.position.size) == 0:
        #         self.position.close()
        #         #print(self.orders)
        #         print("Buying")
        #         self.buy()
        #         print(self.orders)
        #     #print(self.closed_trades)

        # # Else, if sma1 crosses below sma2, close any existing
        # # long trades, and sell the asset
        # elif crossover(self.sma1, self.sma2):
        #     if (self.position.size) > 0:
        #         print("Selling")
        #         self.position.close()
                #self.sell()
            #print (self.closed_trades)