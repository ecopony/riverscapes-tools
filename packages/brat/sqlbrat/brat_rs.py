"""
Augment BRAT with the power of riverscapes context
"""
import argparse
import traceback
import sys
import os
from rscommons import RSProject, dotenv, Logger
from sqlbrat.brat_report import BratReport

lyrs_in_out = {
    # BRAT_ID: INPUT_ID
    'DEM': 'DEM',
    'SLOPE': 'SLOPE',
    'HILLSHADE': 'HILLSHADE',
    'EXVEG': 'EXVEG',
    'HISTVEG': 'HISTVEG',
    'FLOWLINES': 'NHDFlowline',
    'FLOW_AREA': 'NHDArea',
    'WATERBODIES': 'NHDWaterbody',
    'ROADS': 'Roads',
    'RAIL': 'Rail',
    'CANALS': 'Canals',
    'VALLEY_BOTTOM': 'VBET_50'
}


def main():

    parser = argparse.ArgumentParser(
        description='BRAT XML Augmenter',
        # epilog="This is an epilog"
    )
    parser.add_argument('out_project_xml', help='Input XML file', type=str)
    parser.add_argument('in_xmls', help='Comma-separated list of XMLs in decreasing priority', type=str)
    parser.add_argument('--verbose', help='(optional) a little extra logging ', action='store_true', default=False)

    args = dotenv.parse_args_env(parser)

    # Initiate the log file
    log = Logger('XML Augmenter')
    log.setup(verbose=args.verbose)
    log.title('XML Augmenter: {}'.format(args.out_project_xml))

    try:
        out_prj = RSProject(None, args.out_project_xml)
        out_prj.rs_meta_augment(
            args.in_xmls.split(','),
            lyrs_in_out
        )
        gpkg_path = os.path.join(out_prj.project_dir, out_prj.XMLBuilder.find('.//Outputs/Geopackage[@id="OUTPUTS"]/Path').text)

        out_prj.XMLBuilder.write()
        report_path = out_prj.XMLBuilder.find('.//HTMLFile[@id="REPORT"]/Path').text
        report = BratReport(gpkg_path, os.path.join(out_prj.project_dir, report_path), out_prj)
        report.write()

    except Exception as e:
        log.error(e)
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
