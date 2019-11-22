"""Script to calculate fertilzer cost."""
import os

import ecoshard
import pandas
import numpy
import taskgraph
"""
https://www.dropbox.com/s/vaklrf2tpc1orkl/Agcost_data_with_iso.xlsx?dl=0
(containing all __COST data below; by region, with countries belonging to each
 region
 https://storage.googleapis.com/nci-ecoshards/country_shapefile-20191004T192454Z-001_md5_4eb621c6c74707f038d9ac86a4f2b662.gpkg)
Fertilizer cost = NCOST* N rate + PCOST * P rate + KCOST * K rate
N, P, K rate rasters for existing yields (that i’ll use for above)
https://www.dropbox.com/sh/k7qne0hgdq2qkpz/AAB8s_IHN4NvQeZFm1FnAc8Wa?dl=0 Fertilizer2000toMarijn
"""

"""
The costs below are in the Excel Spreadsheet Agcost_data.xls

To calculate fertilizer cost we need:
    * {N, P, K}COST by area.
    * {N, P, K}RATE by area.

Other area costs:
    * labor cost = LPHERHACOST * total_ag_area
    * machinery_cost = MPERHACOST * total_ag_area
    * seed_cost = SPERHACOST * total_ag_area

We need to build a table per region that has:
    All crops (rows)
    All costs (col)
"""
AG_COST_TABLE_URL = (
    'https://storage.googleapis.com/nci-ecoshards/'
    'ag_cost_md5_872f0d09f6d7add60c733cccc3b26987.csv')

CROP_GLOBAL_COST_TABLE_URL = (
    'https://storage.googleapis.com/nci-ecoshards/'
    'crop_global_cost_md5_35b4f1a26c9829b785a18af330d68b58.csv')

FERT_COST_TABLE_URL = (
    'https://storage.googleapis.com/nci-ecoshards/'
    'fert_cost_table_md5_a904bab573d7c30633c64a93dbff4347.csv')

WORKSPACE_DIR = 'fert_cost_workspace'
ADJUSTED_GLOBAL_PRICE_TABLE_PATH = os.path.join(
    WORKSPACE_DIR, 'adjusted_global_price_map.csv')


def main():
    """Entry point."""
    try:
        os.makedirs(WORKSPACE_DIR)
    except OSError:
        pass
    task_graph = taskgraph.TaskGraph(WORKSPACE_DIR, -1)

    crop_global_cost_csv_path = os.path.join(
        WORKSPACE_DIR, os.path.basename(CROP_GLOBAL_COST_TABLE_URL))
    ag_costs_csv_path = os.path.join(
        WORKSPACE_DIR, os.path.basename(AG_COST_TABLE_URL))

    for url, target_path in [
            (CROP_GLOBAL_COST_TABLE_URL, crop_global_cost_csv_path),
            (AG_COST_TABLE_URL, ag_costs_csv_path)]:
        task_graph.add_task(
            func=ecoshard.download_url,
            args=(url, target_path),
            target_path_list=[target_path],
            task_name='download %s')
    task_graph.join()
    task_graph.close()

    ag_costs_df = pandas.read_csv(ag_costs_csv_path, skiprows=[1])
    unique_names = (
        ag_costs_df[['group', 'group_name']].drop_duplicates().dropna(
            how='any'))
    group_id_to_name_map = {x[1][0]: x[1][1] for x in unique_names.iterrows()}
    price_per_ton = ag_costs_df[[
        'group', 'group_name', 'item', 'avgPP']].dropna(how='any')
    fert_per_ha_cost = ag_costs_df[
        ['group', 'item', 'avg_N', 'avg_P', 'avg_K']].drop_duplicates().dropna(
            how='any')
    l_per_ha_cost = ag_costs_df[
        ['group', 'item', 'laborcost']].drop_duplicates().dropna(how='any')
    m_per_ha_cost = ag_costs_df[
        ['group', 'item', 'actual_mach']].drop_duplicates().dropna(how='any')
    s_per_ha_cost = ag_costs_df[
        ['group', 'item', 'actual_seed']].drop_duplicates().dropna(how='any')

    crop_global_cost_df = pandas.read_csv(
        crop_global_cost_csv_path).dropna(how='all').dropna(axis=1, how='all')

    crop_name_to_mf_cost_map = {
        (x[1][0]).lower(): {
            'monfreda_id': x[1][1],
            'avg_global_price': x[1][2]
            } for x in crop_global_cost_df.iterrows()}

    # index by region including
    adjusted_global_price_map = {}
    for row in unique_names.iterrows():
        group_name = row[1][1]
        group_id = row[1][0]

        # China has no local price data, so use Eastern China in that case
        if group_id == 9999:  # China
            group_id = 5302  # Eastern Asia

        # get the subset of group/item/avgPP for this group
        crop_group = price_per_ton.loc[price_per_ton['group'] == group_id]
        crop_items_in_global_list = [
            x
            for x in crop_group['item'].values
            if x.lower() in crop_name_to_mf_cost_map]

        # get average value of global prices
        global_cost_list = [
            float(crop_name_to_mf_cost_map[x.lower()]['avg_global_price'])
            for x in crop_items_in_global_list]

        # get average value of local prices
        local_cost_list = [
            float(crop_group.loc[crop_group['item'] == x]['avgPP'])
            for x in crop_items_in_global_list]
        global_avg = numpy.mean(global_cost_list)
        local_avg = numpy.mean(local_cost_list)
        price_adjustment_rate = local_avg / global_avg

        adjusted_global_price_map[group_name] = {}
        for crop in crop_name_to_mf_cost_map:
            if crop in crop_group['item'].values:
                cost = float(
                    crop_group.loc[crop_group['item'] == crop]['avgPP'])
            else:
                cost = (
                    crop_name_to_mf_cost_map[crop.lower()]['avg_global_price'])
                if isinstance(cost, str):
                    cost = float(cost.replace(',', ''))
                cost *= price_adjustment_rate
            adjusted_global_price_map[group_name][crop] = cost

    # lastly, stick global prices in there too:
    adjusted_global_price_map['Global'] = {}
    for crop_name in crop_name_to_mf_cost_map:
        adjusted_global_price_map['Global'][crop_name] = (
            crop_name_to_mf_cost_map[crop_name]['avg_global_price'])

    header_list = ['Global'] + [
        x for x in sorted(adjusted_global_price_map.keys())
        if x != 'Global']
    with open(ADJUSTED_GLOBAL_PRICE_TABLE_PATH, 'w') as \
            adjusted_global_price_file:
        adjusted_global_price_file.write(
            ','.join(([''] + header_list)))
        adjusted_global_price_file.write('\n')
        for crop_name in sorted(adjusted_global_price_map['Global'].keys()):
            adjusted_global_price_file.write('"%s",' % crop_name)
            for region in header_list:
                price = adjusted_global_price_map[region][crop_name]
                if isinstance(price, str):
                    price = float(price.replace(',', ''))
                adjusted_global_price_file.write('%.2f,' % price)
            adjusted_global_price_file.write('\n')


if __name__ == '__main__':
    main()
