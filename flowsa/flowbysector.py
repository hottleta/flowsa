# flowbysector.py (flowsa)
# !/usr/bin/env python3
# coding=utf-8
"""
Produces a FlowBySector data frame based on a method file for the given class

To run code, specify the "Run/Debug Configurations" Parameters to the "flowsa/data/flowbysectormethods" yaml file name
you want to use.

Example: "Parameters: --m Water_national_2015_m1"

Files necessary to run FBS:
a. a method yaml in "flowsa/data/flowbysectormethods"
b. crosswalk(s) for the main dataset you are allocating and any datasets used to allocate to sectors
c. a .py file in "flowsa/" for the main dataset you are allocating if you need functions to clean up the FBA
   before allocating to FBS

"""

import flowsa
import yaml
import argparse
import sys
import pandas as pd
from flowsa.common import log, flowbysectormethodpath, flow_by_sector_fields,  \
    generalize_activity_field_names, fbsoutputpath, fips_number_key, flow_by_activity_fields, \
    flowbysectoractivitysetspath, flow_by_sector_fields_w_activity
from flowsa.mapping import add_sectors_to_flowbyactivity, get_fba_allocation_subset, map_elementary_flows, \
    get_sector_list
from flowsa.flowbyfunctions import fba_activity_fields, fbs_default_grouping_fields, agg_by_geoscale, \
    fba_fill_na_dict, fbs_fill_na_dict, fba_default_grouping_fields, \
    fbs_activity_fields, allocate_by_sector, allocation_helper, sector_aggregation, \
    filter_by_geoscale, aggregator, clean_df,subset_df_by_geoscale, \
    sector_disaggregation, return_activity_from_scale, fbs_grouping_fields_w_activities
from flowsa.datachecks import check_if_losing_sector_data, check_if_data_exists_at_geoscale, \
    check_if_data_exists_at_less_aggregated_geoscale, check_if_location_systems_match, \
    check_if_data_exists_for_same_geoscales, check_allocation_ratios,\
    check_for_differences_between_fba_load_and_fbs_output
from flowsa.USGS_NWIS_WU import usgs_fba_data_cleanup, usgs_fba_w_sectors_data_cleanup
from flowsa.Blackhurst_IO import convert_blackhurst_data_to_gal_per_year, convert_blackhurst_data_to_gal_per_employee
from flowsa.USDA_CoA_Cropland import disaggregate_coa_cropland_to_6_digit_naics, coa_irrigated_cropland_fba_cleanup
from flowsa.BLS_QCEW import clean_bls_qcew_fba, bls_clean_allocation_fba_w_sec
from flowsa.StatCan_IWS_MI import convert_statcan_data_to_US_water_use, disaggregate_statcan_to_naics_6
from flowsa.USDA_IWMS import disaggregate_iwms_to_6_digit_naics
from flowsa.stewicombo_to_sector import stewicombo_to_sector
from flowsa.EIA_MECS import mecs_energy_fba_cleanup, eia_mecs_energy_clean_allocation_fba_w_sec
from flowsa.BEA import subset_BEA_Use


def parse_args():
    """Make year and source script parameters"""
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--method", required=True, help="Method for flow by sector file. "
                                                          "A valid method config file must exist with this name.")
    args = vars(ap.parse_args())
    return args


def load_method(method_name):
    """
    Loads a flowbysector method from a YAML
    :param method_name:
    :return:
    """
    sfile = flowbysectormethodpath + method_name + '.yaml'
    try:
        with open(sfile, 'r') as f:
            method = yaml.safe_load(f)
    except IOError:
        log.error("FlowBySector method file not found.")
    return method

def load_source_dataframe(k, v):
    """
    Load the source dataframe. Data can be a FlowbyActivity or FlowBySector parquet stored in flowsa, or a FlowBySector
    formatted dataframe from another package.
    :param k: The datasource name
    :param v: The datasource parameters
    :return:
    """
    if v['data_format'] == 'FBA':
        log.info("Retrieving flowbyactivity for datasource " + k + " in year " + str(v['year']))
        flows_df = flowsa.getFlowByActivity(flowclass=[v['class']], years=[v['year']], datasource=k)
    elif v['data_format'] == 'FBS':
        log.info("Retrieving flowbysector for datasource " + k)
        flows_df = flowsa.getFlowBySector(k)
    elif v['data_format'] == 'FBS_outside_flowsa':
        log.info("Retrieving flowbysector for datasource " + k)
        flows_df = getattr(sys.modules[__name__], v["FBS_datapull_fxn"])(*v['parameters'])
    else:
        log.error("Data format not specified in method file for datasource " + k)

    return flows_df


def store_flowbysector(fbs_df, parquet_name):
    """Prints the data frame into a parquet file."""
    f = fbsoutputpath + parquet_name + '.parquet'
    try:
        fbs_df.to_parquet(f)
    except:
        log.error('Failed to save ' + parquet_name + ' file.')


def main(method_name):
    """
    Creates a flowbysector dataset
    :param method_name: Name of method corresponding to flowbysector method yaml name
    :return: flowbysector
    """

    log.info("Initiating flowbysector creation for " + method_name)
    # call on method
    method = load_method(method_name)
    # create dictionary of data and allocation datasets
    fb = method['source_names']
    # Create empty list for storing fbs files
    fbs_list = []
    for k, v in fb.items():
        # pull fba data for allocation
        flows = load_source_dataframe(k, v)

        if v['data_format'] == 'FBA':
            # clean up fba, if specified in yaml
            if v["clean_fba_df_fxn"] != 'None':
                log.info("Cleaning up " + k + " FlowByActivity")
                flows = getattr(sys.modules[__name__], v["clean_fba_df_fxn"])(flows)

            flows = clean_df(flows, flow_by_activity_fields, fba_fill_na_dict)

            # if activity_sets are specified in a file, call them here
            if 'activity_set_file' in v:
                aset_names = pd.read_csv(flowbysectoractivitysetspath + v['activity_set_file'], dtype=str)

            # create dictionary of allocation datasets for different activities
            activities = v['activity_sets']
            # subset activity data and allocate to sector
            for aset, attr in activities.items():
                # subset by named activities
                if 'activity_set_file' in v:
                    names = aset_names[aset_names['activity_set'] == aset]['name']
                else:
                    names = attr['names']

                log.info("Preparing to handle subset of flownames " + ', '.join(map(str, names)) + " in " + k)
                # subset fba data by activity
                flows_subset = flows[(flows[fba_activity_fields[0]].isin(names)) |
                                     (flows[fba_activity_fields[1]].isin(names))].reset_index(drop=True)

                # extract relevant geoscale data or aggregate existing data
                log.info("Subsetting/aggregating dataframe to " + attr['allocation_from_scale'] + " geoscale")
                flows_subset_geo = subset_df_by_geoscale(flows_subset, v['geoscale_to_use'],
                                                         attr['allocation_from_scale'])

                # Add sectors to df activity, depending on level of specified sector aggregation
                log.info("Adding sectors to " + k)
                flow_subset_wsec = add_sectors_to_flowbyactivity(flows_subset_geo,
                                                                 sectorsourcename=method['target_sector_source'])
                # clean up fba with sectors, if specified in yaml
                if v["clean_fba_w_sec_df_fxn"] != 'None':
                    log.info("Cleaning up " + k + " FlowByActivity with sectors")
                    flow_subset_wsec = getattr(sys.modules[__name__], v["clean_fba_w_sec_df_fxn"])(flow_subset_wsec, attr)

                # map df to elementary flows
                log.info("Mapping flows in " + k + ' to federal elementary flow list')
                if 'fedefl_mapping' in v:
                    mapping_files = v['fedefl_mapping']
                else:
                    mapping_files = k

                flow_subset_mapped = map_elementary_flows(flow_subset_wsec, mapping_files)

                # if allocation method is "direct", then no need to create alloc ratios, else need to use allocation
                # dataframe to create sector allocation ratios
                if attr['allocation_method'] == 'direct':
                    log.info('Directly assigning ' + ', '.join(map(str, names)) + ' to sectors')
                    fbs = flow_subset_mapped.copy()

                else:
                    # determine appropriate allocation dataset
                    log.info("Loading allocation flowbyactivity " + attr['allocation_source'] + " for year " +
                             str(attr['allocation_source_year']))
                    fba_allocation = flowsa.getFlowByActivity(flowclass=[attr['allocation_source_class']],
                                                              datasource=attr['allocation_source'],
                                                              years=[attr['allocation_source_year']]).reset_index(drop=True)

                    fba_allocation = clean_df(fba_allocation, flow_by_activity_fields, fba_fill_na_dict)

                    # subset based on yaml settings
                    if attr['allocation_flow'] != 'None':
                        fba_allocation = fba_allocation.loc[fba_allocation['FlowName'].isin(attr['allocation_flow'])]
                    if attr['allocation_compartment'] != 'None':
                        fba_allocation = fba_allocation.loc[
                            fba_allocation['Compartment'].isin(attr['allocation_compartment'])]

                    # cleanup the fba allocation df, if necessary
                    if 'clean_allocation_fba' in attr:
                        log.info("Cleaning " + attr['allocation_source'])
                        fba_allocation = getattr(sys.modules[__name__],
                                                 attr["clean_allocation_fba"])(fba_allocation, attr)
                    # reset index
                    fba_allocation = fba_allocation.reset_index(drop=True)

                    # check if allocation data exists at specified geoscale to use
                    log.info("Checking if allocation data exists at the " + attr['allocation_from_scale'] + " level")
                    check_if_data_exists_at_geoscale(fba_allocation, attr['allocation_from_scale'])

                    # aggregate geographically to the scale of the flowbyactivty source, if necessary
                    from_scale = attr['allocation_from_scale']
                    to_scale = v['geoscale_to_use']
                    # if allocation df is less aggregated than FBA df, aggregate allocation df to target scale
                    if fips_number_key[from_scale] > fips_number_key[to_scale]:
                        fba_allocation = agg_by_geoscale(fba_allocation, from_scale, to_scale,
                                                         fba_default_grouping_fields)
                    # else, if fba is more aggregated than allocation table, use fba as both to and from scale
                    else:
                        fba_allocation = filter_by_geoscale(fba_allocation, from_scale)

                    # assign sector to allocation dataset
                    # todo: add sectorsourcename col value
                    log.info("Adding sectors to " + attr['allocation_source'])
                    fba_allocation_wsec = add_sectors_to_flowbyactivity(fba_allocation,
                                                                        sectorsourcename=method['target_sector_source'])

                    # generalize activity field names to enable link to main fba source
                    log.info("Generalizing activity columns in subset of " + attr['allocation_source'])
                    fba_allocation_wsec = generalize_activity_field_names(fba_allocation_wsec)

                    # call on fxn to further clean up/disaggregate the fba allocation data, if exists
                    if 'clean_allocation_fba_w_sec' in attr:
                        log.info("Further disaggregating sectors in " + attr['allocation_source'])
                        fba_allocation_wsec = getattr(sys.modules[__name__],
                                                      attr["clean_allocation_fba_w_sec"])(fba_allocation_wsec, attr, method)

                    # subset fba datasets to only keep the sectors associated with activity subset
                    log.info("Subsetting " + attr['allocation_source'] + " for sectors in " + k)
                    fba_allocation_subset = get_fba_allocation_subset(fba_allocation_wsec, k, names)

                    # drop columns
                    fba_allocation_subset = fba_allocation_subset.drop(columns=['Activity'])

                    # if there is an allocation helper dataset, modify allocation df
                    if attr['allocation_helper'] == 'yes':
                        log.info("Using the specified allocation help for subset of " + attr['allocation_source'])
                        fba_allocation_subset = allocation_helper(fba_allocation_subset, method, attr, v)

                    # create flow allocation ratios for each activity
                    flow_alloc_list = []
                    for n in names:
                        log.info("Creating allocation ratios for " + n)
                        fba_allocation_subset_2 = get_fba_allocation_subset(fba_allocation_subset, k, [n])
                        if len(fba_allocation_subset_2)==0:
                            log.info("No data found to allocate " + n)
                        else:
                            flow_alloc = allocate_by_sector(fba_allocation_subset_2, attr['allocation_method'])
                            flow_alloc = flow_alloc.assign(FBA_Activity=n)
                            flow_alloc_list.append(flow_alloc)
                    flow_allocation = pd.concat(flow_alloc_list)

                    # check for issues with allocation ratios
                    check_allocation_ratios(flow_allocation, aset, k)

                    # create list of sectors in the flow allocation df, drop any rows of data in the flow df that \
                    # aren't in list
                    sector_list = flow_allocation['Sector'].unique().tolist()

                    # subset fba allocation table to the values in the activity list, based on overlapping sectors
                    flow_subset_mapped = flow_subset_mapped.loc[
                        (flow_subset_mapped[fbs_activity_fields[0]].isin(sector_list)) |
                        (flow_subset_mapped[fbs_activity_fields[1]].isin(sector_list))]

                    # check if fba and allocation dfs have the same LocationSystem
                    log.info("Checking if flowbyactivity and allocation dataframes use the same location systems")
                    check_if_location_systems_match(flow_subset_mapped, flow_allocation)

                    # merge fba df w/flow allocation dataset
                    log.info("Merge " + k + " and subset of " + attr['allocation_source'])
                    fbs = flow_subset_mapped.merge(
                        flow_allocation[['Location', 'Sector', 'FlowAmountRatio', 'FBA_Activity']],
                        left_on=['Location', 'SectorProducedBy', 'ActivityProducedBy'],
                        right_on=['Location', 'Sector', 'FBA_Activity'], how='left')

                    fbs = fbs.merge(
                        flow_allocation[['Location', 'Sector', 'FlowAmountRatio', 'FBA_Activity']],
                        left_on=['Location', 'SectorConsumedBy', 'ActivityConsumedBy'],
                        right_on=['Location', 'Sector', 'FBA_Activity'], how='left')

                    # merge the flowamount columns
                    fbs.loc[:, 'FlowAmountRatio'] = fbs['FlowAmountRatio_x'].fillna(fbs['FlowAmountRatio_y'])
                    # fill null rows with 0 because no allocation info
                    fbs['FlowAmountRatio'] = fbs['FlowAmountRatio'].fillna(0)

                    # check if fba and alloc dfs have data for same geoscales - comment back in after address the 'todo'
                    # log.info("Checking if flowbyactivity and allocation dataframes have data at the same locations")
                    # check_if_data_exists_for_same_geoscales(fbs, k, attr['names'])

                    # drop rows where there is no allocation data
                    fbs = fbs.dropna(subset=['Sector_x', 'Sector_y'], how='all').reset_index()

                    # calculate flow amounts for each sector
                    log.info("Calculating new flow amounts using flow ratios")
                    fbs.loc[:, 'FlowAmount'] = fbs['FlowAmount'] * fbs['FlowAmountRatio']

                    # drop columns
                    log.info("Cleaning up new flow by sector")
                    fbs = fbs.drop(columns=['Sector_x', 'FlowAmountRatio_x', 'Sector_y', 'FlowAmountRatio_y',
                                            'FlowAmountRatio', 'FBA_Activity_x', 'FBA_Activity_y'])

                # drop rows where flowamount = 0 (although this includes dropping suppressed data)
                fbs = fbs[fbs['FlowAmount'] != 0].reset_index(drop=True)

                # clean df
                fbs = clean_df(fbs, flow_by_sector_fields_w_activity, fbs_fill_na_dict)

                # aggregate df geographically, if necessary
                log.info("Aggregating flowbysector to " + method['target_geoscale'] + " level")
                if fips_number_key[v['geoscale_to_use']] < fips_number_key[attr['allocation_from_scale']]:
                    from_scale = v['geoscale_to_use']
                else:
                    from_scale = attr['allocation_from_scale']

                to_scale = method['target_geoscale']

                fbs_geo_agg = agg_by_geoscale(fbs, from_scale, to_scale, fbs_grouping_fields_w_activities)

                # aggregate data to every sector level
                log.info("Aggregating flowbysector to all sector levels")
                fbs_sec_agg = sector_aggregation(fbs_geo_agg, fbs_grouping_fields_w_activities)
                # add missing naics5/6 when only one naics5/6 associated with a naics4
                fbs_agg = sector_disaggregation(fbs_sec_agg, flow_by_sector_fields_w_activity)

                # compare flowbysector with flowbyactivity
                check_for_differences_between_fba_load_and_fbs_output(flow_subset_mapped, fbs_agg, aset, k)

                # return sector level specified in method yaml
                # load the crosswalk linking sector lengths
                sector_list = get_sector_list(method['target_sector_level'])

                # subset df, necessary because not all of the sectors are NAICS and can get duplicate rows
                fbs_1 = fbs_agg.loc[(fbs_agg[fbs_activity_fields[0]].isin(sector_list)) &
                                    (fbs_agg[fbs_activity_fields[1]].isin(sector_list))].reset_index(drop=True)
                fbs_2 = fbs_agg.loc[(fbs_agg[fbs_activity_fields[0]].isin(sector_list)) &
                                    (fbs_agg[fbs_activity_fields[1]].isnull())].reset_index(drop=True)
                fbs_3 = fbs_agg.loc[(fbs_agg[fbs_activity_fields[0]].isnull()) &
                                    (fbs_agg[fbs_activity_fields[1]].isin(sector_list))].reset_index(drop=True)
                fbs_sector_subset = pd.concat([fbs_1, fbs_2, fbs_3])

                # check if losing data by subsetting at specified sector length
                log.info('Checking if losing data by subsetting dataframe')
                fbs_sector_subset_2 = check_if_losing_sector_data(fbs_agg, fbs_sector_subset, method['target_sector_level'])

                # set source name
                fbs_sector_subset_2.loc[:, 'SectorSourceName'] = method['target_sector_source']

                # drop activity columns
                del fbs_sector_subset_2['ActivityProducedBy'], fbs_sector_subset_2['ActivityConsumedBy']

                log.info("Completed flowbysector for activity subset with flows " + ', '.join(map(str, names)))
                fbs_list.append(fbs_sector_subset_2)
        else:
            # if the loaded flow dt is already in FBS format, append directly to list of FBS
            log.info("Append " + k + " to FBS list")
            fbs_list.append(flows)
    # create single df of all activities
    log.info("Concat data for all activities")
    fbss = pd.concat(fbs_list, ignore_index=True, sort=False)
    log.info("Clean final dataframe")
    # aggregate df as activities might have data for the same specified sector length
    fbss = clean_df(fbss, flow_by_sector_fields, fbs_fill_na_dict)
    fbss = aggregator(fbss, fbs_default_grouping_fields)
    # sort df
    log.info("Sort and store dataframe")
    # add missing fields, ensure correct data type, reorder columns
    fbss = fbss.sort_values(
        ['SectorProducedBy', 'SectorConsumedBy', 'Flowable', 'Context']).reset_index(drop=True)
    # save parquet file
    store_flowbysector(fbss, method_name)


if __name__ == '__main__':
    # assign arguments
    args = parse_args()
    main(args["method"])

