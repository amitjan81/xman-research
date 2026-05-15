from lib.data import utils as Utils
import pandas as pd
import sys
import yfinance as yf
import requests
import json
import os
import base64
import gzip
import zlib
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/../../strategy/src/common')

import refdata_cache


class MarketUniverse:
    def __init__(self) -> None:
        pass
    

    def queryNseUrl(self, url):
        baseurl = "https://www.nseindia.com/"
        url = url
        headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'accept-language': 'en,gu;q=0.9,hi;q=0.8', 'accept-encoding': 'gzip, deflate, br'}
        session = requests.Session()
        request = session.get(baseurl, headers=headers, timeout=5)
        cookies = dict(request.cookies)
        #response = session.get(url, headers=headers, timeout=5, cookies=cookies)

        payload = {}
        headers = {
        'user-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'accept-language': 'en,gu;q=0.9,hi;q=0.8\', \'accept-encoding\': \'gzip, deflate, br'
        }

        response = requests.request("GET", url, headers=headers, cookies=cookies, data=payload)

        return response
    
    def get_All_Symbols(self, request_url):
        count = 0
        response = None
        while count < 3:
            try:
                response =  self.queryNseUrl(request_url)
                if response.status_code == 200:
                    break
                else:
                    count = count+1
                    continue
            except Exception as e:
                print("An exception occured...Tryin again")
                count = count +1
                continue
        
        return response

    def classify_stocks_to_sector(self):
        # sectorDict = {
        #     'NIFTY%20ENERGY' : 'ENERGY',
        #     'NIFTY%20AUTO' : 'AUTO',
        #     'NIFTY%20BANK' : 'BANK',
        #     'NIFTY%20FINANCIAL%20SERVICES' : 'FINANCIAL SERVICES',
        #     'NIFTY%20FINANCIAL%20SERVICES%2025%2F50' : 'FINANCIAL SERVICES',
        #     'NIFTY%20FMCG' : 'FMCG',
        #     'NIFTY%20IT' : 'IT',
        #     'NIFTY%20MEDIA' : 'MEDIA',
        #     'NIFTY%20METAL' : 'METAL',
        #     'NIFTY%20PHARMA' : 'PHARMA',
        #     'NIFTY%20REALTY' : 'REALTY',
        #     'NIFTY%20PSU%20BANK' : 'PSU BANK',
        #     'NIFTY%20PRIVATE%20BANK' : 'PRIVATE BANK',
        #     'NIFTY%20CONSUMER%20DURABLES' : 'CONSUMER DURABLES',
        #     'NIFTY%20HEALTHCARE%20INDEX' : 'HEALTHCARE',
        #     'NIFTY%20OIL%20%26%20GAS' : 'OIL&GAS',
        #     'NIFTY%20MIDSMALL%20HEALTHCARE' : 'HEALTHCARE',
        #     'NIFTY%20FINANCIAL%20SERVICES%20EX-BANK' : 'FINANCIAL SERVICES',
        #     'NIFTY%20MIDSMALL%20FINANCIAL%20SERVICES' : 'FINANCIAL SERVICES',
        #     'NIFTY%20MIDSMALL%20IT%20%26%20TELECOM' : 'IT'
        # }
        equityNameToSectorDict = {}
        csvFile = pd.read_csv('nifty500.csv')
        # read above pandas csv file and create a dictionary with key as symbol and value as sector
        csvFile = csvFile[['Symbol', 'Industry']]
        for index, row in csvFile.iterrows():   
            #print(row['Symbol'])
            #print(row['Industry'])
            equityNameToSectorDict[row['Symbol']] = row['Industry']
        # for sectorApi, sectorName in sectorDict.items():
        #     api = 'https://www.nseindia.com/api/equity-stockIndices?index=' + sectorApi
        #     sectorSymbols = self.get_All_Symbols(api)
        #     dataList = sectorSymbols.json()['data']
        #     for i in range(len(dataList)):
        #         if i == 0:
        #             continue
        #         symbolName = dataList[i]['symbol']
        #         equityNameToSectorDict[symbolName] = sectorName
        
        return equityNameToSectorDict

    def optionBackedEquityUniverse(self):
        # pp = self.get_All_Symbols("https://www.nseindia.com/api/underlying-information")
        symbolNameToUnderlierDescription = {'Symbol' : [], 'Description' : []}
        # if pp == None:
        #     return []
        # else:
        #     if pp.status_code == 200:
        #         underlierListForEquityContracts = (pp.json()['data']['UnderlyingList'])
        #         for i in range (len(underlierListForEquityContracts)):
        #             symbolNameToUnderlierDescription['Symbol'].append(underlierListForEquityContracts[i]['symbol'])
        #             symbolNameToUnderlierDescription['Description'].append(underlierListForEquityContracts[i]['underlying'])

        # symbolNameToUnderlierDescription['Symbol'].append('RELINFRA')
        # symbolNameToUnderlierDescription['Description'].append('Relaince Infra')
        refDataCache = refdata_cache.RefDataCache(None)
        symbolList = refDataCache.get_underlier_lookup_list()
        # filter symbol list with value has FINNITY NIFTY50 VIX etc...
        
        for symbol in symbolList:
            symbolNameToUnderlierDescription['Symbol'].append(symbol)
            symbolNameToUnderlierDescription['Description'].append(symbol)
        return Utils.create_Dataframe_From_PyDictionary_ListValues(symbolNameToUnderlierDescription)
    
    def universe2(self):
        pass