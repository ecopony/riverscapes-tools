import argparse
import sqlite3
import os
from xml.etree import ElementTree as ET

from rscommons import Logger, dotenv, ModelConfig, RSReport
from rscommons.util import safe_makedirs
from rscommons.plotting import xyscatter, box_plot

from sqlbrat.__version__ import __version__


id_cols = [
    'VegetationID',
    'Type ID'
]


def report(database, report_path, cfg):

    conn = sqlite3.connect(database)
    conn.row_factory = _dict_factory
    curs = conn.cursor()
    watershed = curs.execute('SELECT WatershedID, Name FROM Watersheds LIMIT 1').fetchone()
    report_title = 'BRAT for {} - {}'.format(watershed['WatershedID'], watershed['Name'])

    css_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'brat_report.css')

    report = RSReport(report_title, 'Model Version: {}'.format(cfg.version), report_path)
    report.add_css(css_path)

    images_dir = os.path.join(os.path.dirname(report_path), 'images')
    safe_makedirs(images_dir)

    # report_intro(database, images_dir, report.inner_div, 'BRAT', cfg.version)
    reach_attribute_summary(database, images_dir, report.inner_div)

    dam_capacity(database, report.inner_div)

    hydrology_plots(database, images_dir, report.inner_div)
    ownership(database, report.inner_div)
    vegetation(database, images_dir, report.inner_div)
    conservation(database, images_dir, report.inner_div)

    report.write()


def report_intro(database, images_dir, elParent, tool_name, version):
    section = RSReport.section('ReportIntro', 'Introduction', elParent)
    conn = sqlite3.connect(database)
    conn.row_factory = _dict_factory
    curs = conn.cursor()

    row = curs.execute('SELECT Sum(iGeo_Len) AS TotalLength, Count(ReachID) AS TotalReaches FROM Reaches').fetchone()
    values = {'Number of reaches': '{0:,d}'.format(row['TotalReaches']), 'Total reach length (km)': '{0:,.0f}'.format(row['TotalLength'] / 1000), 'Total reach length (miles)': '{0:,.0f}'.format(row['TotalLength'] * 0.000621371)}

    row = curs.execute('SELECT WatershedID "Watershed ID", W.Name "Watershed Name", E.Name Ecoregion, CAST(AreaSqKm AS TEXT) "Area (Sqkm)", States FROM Watersheds W INNER JOIN Ecoregions E ON W.EcoregionID = E.EcoregionID').fetchone()
    values.update(row)

    table_wrapper = ET.Element('div', attrib={'class': 'tableWrapper'})
    section.append(table_wrapper)

    # create_table_from_dict(values, table_wrapper, attrib={'id': 'SummTable'})

    curs.execute('SELECT KeyInfo, ValueInfo FROM Metadata')
    values.update({row['KeyInfo'].replace('_', ' '): row['ValueInfo'] for row in curs.fetchall()})

    RSReport.create_table_from_dict(values, table_wrapper, attrib={'id': 'SummTable'})

    RSReport.create_table_from_sql(
        ['Reach Type', 'Total Length (km)', '% of Total'],
        'SELECT ReachType, Sum(iGeo_Len) / 1000 As Length, 100 * Sum(iGeo_Len) / TotalLength AS TotalLength '
        'FROM vwReaches INNER JOIN (SELECT Sum(iGeo_Len) AS TotalLength FROM Reaches) GROUP BY ReachType',
        database, table_wrapper, attrib={'id': 'SummTable_sql'})


def reach_attribute(database, attribute, units, images_dir, elParent):
    # Use a class here because it repeats
    wrapper = ET.Element('div', attrib={'class': 'reachAtribute'})
    RSReport.header(4, attribute, wrapper)

    conn = sqlite3.connect(database)
    conn.row_factory = _dict_factory
    curs = conn.cursor()

    # Summary statistics (min, max etc) for the current attribute
    curs.execute('SELECT Count({0}) "Values", Max({0}) Maximum, Min({0}) Minimum, Avg({0}) Average FROM Reaches WHERE {0} IS NOT NULL'.format(attribute))
    values = curs.fetchone()

    reach_wrapper_inner = ET.Element('div', attrib={'class': 'reachAtributeInner'})
    wrapper.append(reach_wrapper_inner)

    # Add the number of NULL values
    curs.execute('SELECT Count({0}) "NULL Values" FROM Reaches WHERE {0} IS NULL'.format(attribute))
    values.update(curs.fetchone())
    RSReport.create_table_from_dict(values, reach_wrapper_inner)

    # Box plot
    image_path = os.path.join(images_dir, 'attribute_{}.png'.format(attribute))
    curs.execute('SELECT {0} FROM Reaches WHERE {0} IS NOT NULL'.format(attribute))
    values = [row[attribute] for row in curs.fetchall()]
    box_plot(values, attribute, attribute, image_path)

    img_wrap = ET.Element('div', attrib={'class': 'imgWrap'})
    img = ET.Element('img', attrib={'class': 'boxplot', 'alt': 'boxplot', 'src': '{}/{}'.format(os.path.basename(images_dir), os.path.basename(image_path))})
    img_wrap.append(img)

    reach_wrapper_inner.append(img_wrap)

    elParent.append(wrapper)


def table_of_contents(elParent):
    wrapper = ET.Element('div', attrib={'id': 'TOC'})
    RSReport.header(3, 'Table of Contents', wrapper)

    ul = ET.Element('ul')

    li = ET.Element('li')
    ul.append(li)

    anchor = ET.Element('a', attrib={'href': '#ownership'})
    anchor.text = 'Ownership'
    li.append(anchor)

    elParent.append(wrapper)


def dam_capacity(database, elParent):
    section = RSReport.section('DamCapacity', 'BRAT Dam Capacity Results', elParent)

    fields = [
        ('Existing complex size', 'Sum(mCC_EX_CT)'),
        ('Historic complex size', 'Sum(mCC_HPE_CT)'),
        ('Existing vegetation capacity', 'Sum((iGeo_len / 1000) * oVC_EX)'),
        ('Historic vegetation capacity', 'Sum((iGeo_len / 1000) * oVC_HPE)'),
        ('Existing capacity', 'Sum((iGeo_len / 1000) * oCC_EX)'),
        ('Historic capacity', 'Sum((iGeo_len / 1000) * oCC_HPE)')
    ]

    conn = sqlite3.connect(database)
    curs = conn.cursor()

    curs.execute('SELECT {} FROM Reaches'.format(', '.join([field for label, field in fields])))
    row = curs.fetchone()

    table_dict = {fields[i][0]: row[i] for i in range(len(fields))}
    RSReport.create_table_from_dict(table_dict, section)

    dam_capacity_lengths(database, section, 'oCC_EX')
    dam_capacity_lengths(database, section, 'oCC_HPE')


def dam_capacity_lengths(database, elParent, capacity_field):

    conn = sqlite3.connect(database)
    curs = conn.cursor()

    curs.execute('SELECT Name, MaxCapacity FROM DamCapacities ORDER BY MaxCapacity')
    bins = [(row[0], row[1]) for row in curs.fetchall()]

    curs.execute('SELECT Sum(iGeo_Len) / 1000 FROM Reaches')
    total_length_km = curs.fetchone()[0]

    data = []
    last_bin = 0
    cumulative_length_km = 0
    for name, max_capacity in bins:
        curs.execute('SELECT Sum(iGeo_len) / 1000 FROM Reaches WHERE {} <= {}'.format(capacity_field, max_capacity))
        rowi = curs.fetchone()
        if not rowi or rowi[0] is None:
            bin_km = 0
        else:
            bin_km = rowi[0] - cumulative_length_km
            cumulative_length_km = rowi[0]
        data.append((
            '{}: {} - {}'.format(name, last_bin, max_capacity),
            bin_km,
            bin_km * 0.621371,
            100 * bin_km / total_length_km
        ))

        last_bin = max_capacity

    data.append(('Total', cumulative_length_km, cumulative_length_km * 0.621371, 100 * cumulative_length_km / total_length_km))
    RSReport.create_table_from_tuple_list((capacity_field, 'Stream Length (km)', 'Stream Length (mi)', 'Percent'), data, elParent)


def hydrology_plots(database, images_dir, elParent):
    section = RSReport.section('HydrologyPlots', 'Hydrology', elParent)

    log = Logger('Report')

    conn = sqlite3.connect(database)
    curs = conn.cursor()

    curs.execute('SELECT MaxDrainage, QLow, Q2 FROM Watersheds')
    row = curs.fetchone()
    RSReport.create_table_from_dict({'Max Draiange (sqkm)': row[0], 'Baseflow': row[1], 'Peak Flow': row[2]}, section)

    RSReport.header(3, 'Hydrological Parameters', section)
    RSReport.create_table_from_sql(
        ['Parameter', 'Data Value', 'Data Units', 'Conversion Factor', 'Equation Value', 'Equation Units'],
        'SELECT Parameter, Value, DataUnits, Conversion, ConvertedValue, EquationUnits FROM vwHydroParams',
        database, section)

    variables = [
        ('iHyd_QLow', 'Baseflow (CFS)'),
        ('iHyd_Q2', 'Peak Flow (CFS)'),
        ('iHyd_SPLow', 'Baseflow Stream Power (Watts)'),
        ('iHyd_SP2', 'Peak Flow Stream Power (Watts)'),
        ('iGeo_Slope', 'Slope (degrees)')
    ]

    plot_wrapper = ET.Element('div', attrib={'class': 'hydroPlotWrapper'})
    section.append(plot_wrapper)

    for variable, ylabel in variables:
        log.info('Generating XY scatter for {} against drainage area.'.format(variable))
        image_path = os.path.join(images_dir, 'drainage_area_{}.png'.format(variable.lower()))

        curs.execute('SELECT iGeo_DA, {} FROM Reaches'.format(variable))
        values = [(row[0], row[1]) for row in curs.fetchall()]
        xyscatter(values, 'Drainage Area (sqkm)', ylabel, variable, image_path)

        img_wrap = ET.Element('div', attrib={'class': 'imgWrap'})
        img = ET.Element('img', attrib={'src': '{}/{}'.format(os.path.basename(images_dir), os.path.basename(image_path)), 'alt': 'boxplot'})
        img_wrap.append(img)
        plot_wrapper.append(img_wrap)


def reach_attribute_summary(database, images_dir, elParent):
    section = RSReport.section('ReachAttributeSummary', 'Geophysical Attributes', elParent)

    attribs = [
        ('iGeo_Slope', 'Slope', 'ratio'),
        ('iGeo_ElMax', 'Max Elevation', 'metres'),
        ('iGeo_ElMin', 'Min Elevation', 'metres'),
        ('iGeo_Len', 'Length', 'metres'),
        ('iGeo_DA', 'Drainage Area', 'Sqkm')
    ]
    plot_wrapper = ET.Element('div', attrib={'class': 'plots'})
    [reach_attribute(database, attribute, units, images_dir, plot_wrapper) for attribute, name, units in attribs]

    section.append(plot_wrapper)


def ownership(database, elParent):
    section = RSReport.section('Ownership', 'Ownership', elParent)

    RSReport.create_table_from_sql(
        ['Ownership Agency', 'Number of Reach Segments', 'Length (km)', '% of Total Length'],
        'SELECT IFNULL(Agency, "None"), Count(ReachID), Sum(iGeo_Len) / 1000, 100* Sum(iGeo_Len) / TotalLength FROM vwReaches'
        ' INNER JOIN (SELECT Sum(iGeo_Len) AS TotalLength FROM Reaches) GROUP BY Agency',
        database, section)


def vegetation(database, image_dir, elParent):
    section = RSReport.section('Vegetation', 'Vegetation', elParent)

    for epochid, veg_type in [(2, 'Historic Vegetation'), (1, 'Existing Vegetation')]:

        RSReport.header(3, veg_type, section)

        pEl = ET.Element('p')
        pEl.text = 'The 30 most common {} types within the 100m reach buffer.'.format(veg_type.lower())
        section.append(pEl)

        RSReport.create_table_from_sql(
            ['Vegetation ID', 'Vegetation Type', 'Total Area (sqkm)', 'Default Suitability', 'Override Suitability', 'Effective Suitability'],
            """
                    SELECT VegetationID,
                    Name, (CAST(TotalArea AS REAL) / 1000000) AS TotalAreaSqKm,
                    DefaultSuitability,
                    OverrideSuitability,
                    EffectiveSuitability
                    FROM vwReachVegetationTypes WHERE (EpochID = {}) AND (Buffer = 100) ORDER BY TotalArea DESC LIMIT 30""".format(epochid), database, section)

        try:
            # Calculate the area weighted suitability
            conn = sqlite3.connect(database)
            curs = conn.cursor()
            curs.execute("""
            SELECT WeightedSum / SumTotalArea FROM
            (SELECT Sum(CAST(TotalArea AS REAL) * CAST(EffectiveSuitability AS REAL) / 1000000) WeightedSum FROM vwReachVegetationTypes WHERE EpochID = {0} AND Buffer = 100)
            JOIN
            (SELECT CAST(Sum(TotalArea) AS REAL) / 1000000 SumTotalArea FROM vwReachVegetationTypes WHERE EpochID = {0} AND Buffer = 100)""".format(epochid))
            area_weighted_avg_suitability = curs.fetchone()[0]

            RSReport.header(3, 'Suitability Breakdown', section)
            pEl = ET.Element('p')
            pEl.text = """The area weighted average {} suitability is {}.
                The breakdown of the percentage of the 100m buffer within each suitability class across all reaches in the watershed.""".format(veg_type.lower(), RSReport.format_value(area_weighted_avg_suitability)[0])
            section.append(pEl)

            RSReport.create_table_from_sql(['Suitability Class', '% with 100m Buffer'],
                                           """
                SELECT EffectiveSuitability, 100.0 * SArea / SumTotalArea FROM 
                (SELECT CAST(Sum(TotalArea) AS REAL) / 1000000 SArea, EffectiveSuitability
                    FROM vwReachVegetationTypes WHERE EpochID = {0} AND Buffer = 100 GROUP BY EffectiveSuitability)
                JOIN
                (   SELECT CAST(Sum(TotalArea) AS REAL) / 1000000 SumTotalArea FROM vwReachVegetationTypes WHERE EpochID = {0} AND Buffer = 100)
                ORDER BY EffectiveSuitability
                """.format(epochid), database, section, id_cols=id_cols)
        except Exception as ex:
            log = Logger('Report')
            log.warning('Error calculating vegetation report')


def conservation(database, images_dir, elParent):
    section = RSReport.section('Conservation', 'Conservation', elParent)

    fields = [
        ('Risk', 'DamRisks', 'RiskID'),
        ('Opportunity', 'DamOpportunities', 'OpportunityID'),
        ('Limitation', 'DamLimitations', 'LimitationID')
    ]

    for label, table, idfield in fields:
        RSReport.header(3, label, section)
        RSReport.create_table_from_sql(
            [label, 'Total Length (km)', 'Reach Count', '%'],
            'SELECT DR.Name, Sum(iGeo_Len) / 1000, Count(R.{1}), 100 * Sum(iGeo_Len) / TotalLength'
            ' FROM {0} DR LEFT JOIN Reaches R ON DR.{1} = R.{1}'
            ' JOIN (SELECT Sum(iGeo_Len) AS TotalLength FROM Reaches)'
            ' GROUP BY DR.{1}'.format(table, idfield),
            database, section)

    RSReport.header(3, 'Conflict Attributes', section)

    for attribute in ['iPC_Canal', 'iPC_DivPts', 'iPC_Privat']:
        reach_attribute(database, attribute, 'meters', images_dir, section)


def _dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('database', help='Path to the BRAT database', type=str)
    parser.add_argument('report_path', help='Output path where report will be generated', type=str)
    args = dotenv.parse_args_env(parser)

    cfg = ModelConfig('http://xml.riverscapes.xyz/Projects/XSD/V1/BRAT.xsd', __version__)

    report(args.database, args.report_path, cfg)


if __name__ == '__main__':
    main()