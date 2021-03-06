# EIA_MECS.py (flowsa)
# !/usr/bin/env python3
# coding=utf-8

import pandas as pd
import numpy as np
import io
from flowsa.common import *
from flowsa.flowbyfunctions import assign_fips_location_system
import yaml

"""
MANUFACTURING ENERGY CONSUMPTION SURVEY (MECS)
https://www.eia.gov/consumption/manufacturing/data/2014/
Last updated: 8 Sept. 2020
"""

def eia_mecs_URL_helper(build_url, config, args):
    """
    Takes the build url and performs substitutions based on the EIA MECS year 
    and data tables of interest. Returns the finished url.
    """
    
    # initiate url list
    urls = []
    
    # for all tables listed in the source config file...
    for table in config['tables']:
        # start with build url
        url = build_url
        # replace '__year__' in build url
        url = url.replace('__year__', args['year'])
        # 2014 files are in .xlsx format; 2010 files are in .xls format
        if(args['year'] == '2010'):
            url = url[:-1]
        # replace '__table__' in build url
        url = url.replace('__table__', table)
        # add to list of urls
        urls.append(url)
        
    return urls


def eia_mecs_land_call(url, cbesc_response, args):
    # Convert response to dataframe
    df_raw_data = pd.io.excel.read_excel(io.BytesIO(cbesc_response.content), sheet_name='Table 9.1')
    df_raw_rse = pd.io.excel.read_excel(io.BytesIO(cbesc_response.content), sheet_name='RSE 9.1')
    if (args["year"] == "2014"):
        df_rse = pd.DataFrame(df_raw_rse.loc[12:93]).reindex()
        df_data = pd.DataFrame(df_raw_data.loc[16:97]).reindex()
        df_description = pd.DataFrame(df_raw_data.loc[16:97]).reindex()
        # skip rows and remove extra rows at end of dataframe

        df_description.columns = ["NAICS Code(a)", "Subsector and Industry",
                           "Approximate Enclosed Floorspace of All Buildings Onsite (million sq ft)",
                           "Establishments(b) (counts)", "Average Enclosed Floorspace per Establishment (sq ft)",
                           "Approximate Number of All Buildings Onsite (counts)",
                           "Average Number of Buildings Onsite per Establishment (counts)",
                           "n8", "n9", "n10", "n11", "n12"]
        df_data.columns = ["NAICS Code(a)", "Subsector and Industry",
                           "Approximate Enclosed Floorspace of All Buildings Onsite (million sq ft)",
                           "Establishments(b) (counts)", "Average Enclosed Floorspace per Establishment (sq ft)",
                           "Approximate Number of All Buildings Onsite (counts)",
                           "Average Number of Buildings Onsite per Establishment (counts)",
                           "n8", "n9", "n10", "n11", "n12"]
        df_rse.columns = ["NAICS Code(a)", "Subsector and Industry",
                          "Approximate Enclosed Floorspace of All Buildings Onsite (million sq ft)",
                          "Establishments(b) (counts)", "Average Enclosed Floorspace per Establishment (sq ft)",
                          "Approximate Number of All Buildings Onsite (counts)",
                          "Average Number of Buildings Onsite per Establishment (counts)",
                          "n8", "n9", "n10", "n11", "n12"]

        #Drop unused columns
        df_description = df_description.drop(columns=["Approximate Enclosed Floorspace of All Buildings Onsite (million sq ft)",
                       "Establishments(b) (counts)", "Average Enclosed Floorspace per Establishment (sq ft)",
                       "Approximate Number of All Buildings Onsite (counts)",
                       "Average Number of Buildings Onsite per Establishment (counts)",
                       "n8", "n9", "n10", "n11", "n12"])

        df_data = df_data.drop(columns=["Subsector and Industry", "n8", "n9", "n10", "n11", "n12"])
        df_rse = df_rse.drop(columns=["Subsector and Industry", "n8", "n9", "n10", "n11", "n12"])
    else:
        df_rse = pd.DataFrame(df_raw_rse.loc[14:97]).reindex()
        df_data = pd.DataFrame(df_raw_data.loc[16:99]).reindex()
        df_description = pd.DataFrame(df_raw_data.loc[16:99]).reindex()
        df_description.columns = ["NAICS Code(a)", "Subsector and Industry",
                                  "Approximate Enclosed Floorspace of All Buildings Onsite (million sq ft)",
                                  "Establishments(b) (counts)", "Average Enclosed Floorspace per Establishment (sq ft)",
                                  "Approximate Number of All Buildings Onsite (counts)",
                                  "Average Number of Buildings Onsite per Establishment (counts)"]
        df_data.columns = ["NAICS Code(a)", "Subsector and Industry",
                           "Approximate Enclosed Floorspace of All Buildings Onsite (million sq ft)",
                           "Establishments(b) (counts)", "Average Enclosed Floorspace per Establishment (sq ft)",
                           "Approximate Number of All Buildings Onsite (counts)",
                           "Average Number of Buildings Onsite per Establishment (counts)"]
        df_rse.columns = ["NAICS Code(a)", "Subsector and Industry",
                          "Approximate Enclosed Floorspace of All Buildings Onsite (million sq ft)",
                          "Establishments(b) (counts)", "Average Enclosed Floorspace per Establishment (sq ft)",
                          "Approximate Number of All Buildings Onsite (counts)",
                          "Average Number of Buildings Onsite per Establishment (counts)"]
        # Drop unused columns
        df_description = df_description.drop(
            columns=["Approximate Enclosed Floorspace of All Buildings Onsite (million sq ft)",
                     "Establishments(b) (counts)", "Average Enclosed Floorspace per Establishment (sq ft)",
                     "Approximate Number of All Buildings Onsite (counts)",
                     "Average Number of Buildings Onsite per Establishment (counts)"])
        df_data = df_data.drop(columns=["Subsector and Industry"])
        df_rse = df_rse.drop(columns=["Subsector and Industry"])

    df_data = df_data.melt(id_vars=["NAICS Code(a)"],
                           var_name="FlowName",
                           value_name="FlowAmount")
    df_rse = df_rse.melt(id_vars=["NAICS Code(a)"],
                           var_name="FlowName",
                           value_name="Spread")

    df = pd.merge(df_data, df_rse)
    df = pd.merge(df, df_description)
    
    return df

 
def eia_mecs_land_parse(dataframe_list, args):
    df_array = []
    for dataframes in dataframe_list:

        dataframes = dataframes.rename(columns={'NAICS Code(a)': 'ActivityConsumedBy'})
        dataframes = dataframes.rename(columns={'Subsector and Industry': 'Description'})
        dataframes.loc[dataframes.Description == "Total", "ActivityConsumedBy"] = "31-33"
        unit = []
        for index, row in dataframes.iterrows():
            if row["FlowName"] == "Establishments(b) (counts)":
                row["FlowName"] = "Establishments (counts)"
            flow_name_str = row["FlowName"]
            flow_name_array = flow_name_str.split("(")
            row["FlowName"] = flow_name_array[0]
            unit_text = flow_name_array[1]
            unit_text_array = unit_text.split(")")
            if unit_text_array[0] == "counts":
                unit.append(("p"))
            else:
                unit.append(unit_text_array[0])
            ACB = row["ActivityConsumedBy"]
            ACB_str = str(ACB).strip()
            row["ActivityConsumedBy"] = ACB_str
        df_array.append(dataframes)
    df = pd.concat(df_array, sort=False)

    # replace withdrawn code
    df.loc[df['FlowAmount'] == "Q", 'FlowAmount'] = withdrawn_keyword
    df.loc[df['FlowAmount'] == "N", 'FlowAmount'] = withdrawn_keyword
    df["Class"] = 'Land'
    df["SourceName"] = 'EIA_MBECS_Land'
    df['Year'] = args["year"]
    df["Compartment"] = None
    df['MeasureofSpread'] = "RSE"
    df['Location'] = "US_FIPS"
    df['Unit'] = unit
    df = assign_fips_location_system(df, args['year'])

    return df


def eia_mecs_energy_call(url, mecs_response, args):
    """
    Takes the .xlsx or .xls file returned from the url call and reads it into a dataframe.
    Grabs data for each of the census regions and "unpivots" dataframe.
    Adds columns for census region, relative standard error, units.
    Concatenates census region data into master dataframe.
    Returns master dataframe containing data for all 4 census regions, plus U.S. totals.
    """
    
    ## load .yaml file containing information about each energy table
    ## (the .yaml includes information such as column names, units, and which rows to grab)
    filename = 'EIA_MECS_energy tables'
    sourcefile = datapath + filename + '.yaml'
    with open(sourcefile, 'r') as f:
        table_dict = yaml.safe_load(f)
    
    ## read raw data into dataframe
    ## (include both Sheet 1 (data) and Sheet 2 (relative standard errors))
    df_raw_data = pd.io.excel.read_excel(io.BytesIO(mecs_response.content), sheet_name=0, header=None)
    df_raw_rse = pd.io.excel.read_excel(io.BytesIO(mecs_response.content), sheet_name=1, header=None)
    
    ## retrieve table name from cell A3 of Excel file
    table = df_raw_data.iloc[2][0]
    # drop the table description (retain only table name)
    table = table.split('    ')[0]
    
    ## for each of the census regions...
    ## - grab the appropriate rows and columns
    ## - add column names
    ## - "unpivot" dataframe from wide format to long format
    ## - add columns denoting census region, relative standard error, units
    ## - concatenate census region data into master dataframe
    df_data = pd.DataFrame()
    for region in table_dict[args['year']][table]['regions']:
        
        ## grab relevant columns
        ## (this is a necessary step because code was retaining some seemingly blank columns)
        # determine number of columns in table, based on number of column names
        num_cols = len(table_dict[args['year']][table]['col_names'])
        # keep only relevant columns
        df_raw_data = df_raw_data.iloc[:,0:num_cols]
        df_raw_rse = df_raw_rse.iloc[:,0:num_cols]
        
        ## grab relevant rows
        # get indices for relevant rows
        grab_rows = table_dict[args['year']][table]['regions'][region]
        grab_rows_rse = table_dict[args['year']][table]['rse_regions'][region]
        # keep only relevant rows
        df_data_region = pd.DataFrame(df_raw_data.loc[grab_rows[0]-1:grab_rows[1]-1]).reindex()
        df_rse_region = pd.DataFrame(df_raw_rse.loc[grab_rows_rse[0]-1:grab_rows_rse[1]-1]).reindex()
        
        # assign column names
        df_data_region.columns = table_dict[args['year']][table]['col_names']
        df_rse_region.columns = table_dict[args['year']][table]['col_names']
        
        # "unpivot" dataframe from wide format to long format
        # ('NAICS code' and 'Subsector and Industry' are identifier variables)
        # (all other columns are value variables)
        df_data_region = pd.melt(df_data_region, 
                                 id_vars = table_dict[args['year']][table]['col_names'][0:2], 
                                 value_vars = table_dict[args['year']][table]['col_names'][2:],
                                 var_name = 'FlowName',
                                 value_name = 'FlowAmount')
        df_rse_region = pd.melt(df_rse_region, 
                                 id_vars = table_dict[args['year']][table]['col_names'][0:2], 
                                 value_vars = table_dict[args['year']][table]['col_names'][2:],
                                 var_name = 'FlowName',
                                 value_name = 'Spread')

        # add census region
        df_data_region['Location'] = region
        
        # add relative standard error data
        df_data_region = pd.merge(df_data_region, df_rse_region)
        
        ## add units
        # if table name ends in 1, units must be extracted from flow names
        if table[-1] == '1':
            flow_name_array = df_data_region['FlowName'].str.split('\s+\|+\s')
            df_data_region['FlowName'] = flow_name_array.str[0] 
            df_data_region['Unit'] = flow_name_array.str[1]
        # if table name ends in 2, units are 'trillion Btu'
        elif table[-1] == '2':
            df_data_region['Unit'] = 'Trillion Btu'
            df_data_region['FlowName'] = df_data_region['FlowName']
        
        data_type = table_dict[args['year']][table]['data_type']
        if data_type == 'nonfuel consumption':
            df_data_region['Class']='Other'    
        elif data_type == 'fuel consumption':
            df_data_region['Class']='Energy'
        # remove extra spaces before 'Subsector and Industry' descriptions
        df_data_region['Subsector and Industry'] = df_data_region['Subsector and Industry'].str.lstrip(' ')
        
        # concatenate census region data with master dataframe
        df_data = pd.concat([df_data, df_data_region])
        
    return df_data


def eia_mecs_energy_parse(dataframe_list, args):
    
    # concatenate dataframe list into single dataframe
    df = pd.concat(dataframe_list, sort=True)
    
    # rename columns to match standard flowbyactivity format
    df = df.rename(columns={'NAICS Code' : 'ActivityConsumedBy',
                            'Subsector and Industry' : 'Description'})
    df['ActivityConsumedBy'] = df['ActivityConsumedBy'].str.strip()
    # add hardcoded data
    df["SourceName"] = args['source']
    df["Compartment"] = None
    df['FlowType'] = 'TECHNOSPHERE_FLOWS'
    df['Year'] = args["year"]
    df['MeasureofSpread'] = "RSE"
    df['LocationSystem'] = 'Census_Region'
    df.loc[df['Location']=='Total United States','Location'] = US_FIPS
    df.loc[df['Description'] == 'Total', 'ActivityConsumedBy'] = '31-33'
    
    # drop rows that reflect subtotals (only necessary in 2014)
    df.dropna(subset=['ActivityConsumedBy'], inplace=True)
        
        
    ## replace withheld/unavailable data
    # * = estimate is less than 0.5
    # W = withheld to avoid disclosing data for individual establishments
    # Q = withheld because relative standard error is greater than 50 percent
    # NA = not available
    df.loc[df['FlowAmount'] == '*', 'FlowAmount'] = None
    df.loc[df['FlowAmount'] == 'W', 'FlowAmount'] = withdrawn_keyword
    df.loc[df['FlowAmount'] == 'Q', 'FlowAmount'] = withdrawn_keyword
    df.loc[df['FlowAmount'] == 'NA', 'FlowAmount'] = None
    # * = estimate is less than 0.5
    # W = withheld to avoid disclosing data for individual establishments
    # Q = withheld because relative standard error is greater than 50 percent
    # NA = not available
    # X = not defined because relative standard error corresponds to a value of zero
    # at least one 'empty' cell appears to contain a space
    df.loc[df['Spread'] == '*', 'Spread'] = None
    df.loc[df['Spread'] == 'W', 'Spread'] = withdrawn_keyword
    df.loc[df['Spread'] == 'Q', 'Spread'] = withdrawn_keyword
    df.loc[df['Spread'] == 'NA', 'Spread'] = None
    df.loc[df['Spread'] == 'X', 'Spread'] = None
    df.loc[df['Spread'] == ' ', 'Spread'] = None

    return df

def mecs_energy_fba_cleanup(fba, attr):
    
    fba = fba.loc[fba['Unit']=='MJ']
    return fba

def eia_mecs_energy_clean_allocation_fba_w_sec(df_w_sec, attr, method):
    """
    clean up eia_mecs_energy df with sectors by estimating missing data
    :param df_w_sec:
    :param attr:
    :param method:
    :return:
    """

    df = estimate_missing_data(df_w_sec, [3,4,5])

    return df
    
def estimate_missing_data(df, sector_lengths):
    """
    For a given dataframe where data is reported by NAICS, but not all nested NAICS are listed,
    this function applies the unaccounted for amounts equally across unreported children
    """
    df.dropna(subset=['Sector'], inplace=True)
    cw = load_sector_length_crosswalk()
    suppressed_list = []
    for i in sector_lengths:

        # create df with sectors of i length, need to disaggregate to i+1
        df_parent = df.loc[df['Activity'].apply(lambda x: len(x) == i)]
        parentlist = df_parent['Activity'].drop_duplicates().tolist()

        # create df with sectors of length > i (i.e. children)
        df_child = df.loc[df['Activity'].apply(lambda x: len(x) > i)]
        df_child.loc[:, 's_tmp'] = df_child['Activity'].apply(lambda x: x[0:i])
        
        cw2 = cw[['NAICS_'+str(i),'NAICS_'+str(i+1)]]
        new_df = pd.DataFrame(columns=df.columns)
        
        for sector in parentlist:
            df_temp_parent = df_parent[df_parent['Activity']==sector]
            # extract the children of the given sector of level i that exist in the dataframe
            df_temp_child = df_child[df_child['s_tmp'] == sector]
            childlist = df_temp_child['Activity'].tolist()
            df_temp_child['s_tmp'] = df_child['Activity'].apply(lambda x: x[0:i+1])
            df_temp_child['length'] = df_child['Activity'].str.len()

            # drop children that have the same sector of i+1 (because these are double counting), as long as they are not the same length
            net_flow = df_temp_child.groupby(['length','s_tmp']).agg({'FlowAmount':['sum']}).reset_index()
            net_flow.columns=['length','s_tmp','FlowAmount']
            # calculate the amount supplied by existing sectors
            net_flow = net_flow.drop_duplicates(subset=['s_tmp'])
            
            cw_temp = cw2[cw2['NAICS_'+str(i)]==sector]
            cw_childlist = cw_temp['NAICS_'+str(i+1)].drop_duplicates().tolist()
            sectors_to_add = list(set(cw_childlist).difference(childlist))

            if len(sectors_to_add) != 0:
                new_flow_amount = (df_temp_parent['FlowAmount'].sum()-net_flow['FlowAmount'].sum())/len(sectors_to_add)
                # Add new children to dataframe as new Activities, and assign flow amount,
                # all other data remains the same as the parent (update DQI?)
                new_child = pd.DataFrame(sectors_to_add, columns=['Sector'])
                new_child['Activity']= sector
                new_child = df_temp_parent.merge(new_child, how='left', on='Activity')
                new_child['Sector']=new_child['Sector_y']
                new_child.drop(columns=['Sector_x','Sector_y'], inplace=True)
                new_child['FlowAmount']=new_flow_amount
                new_df = pd.concat([new_df,new_child],axis=0, ignore_index=True)
                suppressed_list.extend(sectors_to_add)
        
        df = pd.concat([df,new_df],axis=0, ignore_index=True)
        # drop the parent list from original df
        df = df[~df['Sector'].isin(parentlist)]
  
    return df