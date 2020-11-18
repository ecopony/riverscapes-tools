import sqlite3
import os
import datetime
from uuid import uuid4
from xml.etree import ElementTree as ET
from jinja2 import Template
from html5print import HTMLBeautifier, CSSBeautifier
from rscommons import Logger
from rscommons.util import sizeof_fmt


class RSReport():

    def __init__(self, rs_project, filepath):
        self.log = Logger('Report')
        self.template_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'templates')

        self.log.info('Creating report at {}'.format(filepath))
        self.xml_project = rs_project
        self.filepath = filepath
        self.css_files = []
        self.footer = ''

        if os.path.isfile(self.filepath):
            os.remove(self.filepath)

        self.toc = []

        # Add in our common CSS. This can be extended
        self.add_css(os.path.join(self.template_path, 'report.css'))

        self.main_el = ET.Element('main', attrib={'id': 'ReportInner'})

    def write(self):
        css_template = "<style>\n{}\n</style>"
        html_inner = ET.tostring(self.main_el, method="html", encoding='unicode')
        styles = ''.join([css_template.format(css) for css in self.css_files])

        toc = ''
        if len(self.toc) > 0:
            toc = ET.tostring(self._table_of_contents(), method="html", encoding='unicode')
        # Get my HTML templae and render it

        with open(os.path.join(self.template_path, 'template.html')) as t:
            template = Template(t.read())

        now = datetime.datetime.now()
        final_render = HTMLBeautifier.beautify(template.render(report={
            'title': self.xml_project.XMLBuilder.find('Name').text,
            'ProjectType': self.xml_project.XMLBuilder.find('ProjectType').text,
            'MetaData': self.xml_project.get_metadata_dict(),
            'date': now.strftime('%B %d, %Y - %I:%M%p'),
            'Warehouse': self.xml_project.get_metadata_dict(tag='Warehouse'),
            'head': styles,
            'toc': toc,
            'body': html_inner,
            'footer': self.footer
        }))
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(final_render)

        self.log.debug('Report Writing Completed')

    def add_css(self, filepath):
        with open(filepath) as css_file:
            css = css_file.read()
        beautiful = CSSBeautifier.beautify(css)
        self.css_files.append(beautiful)

    def section(self, sectionid, title, el_parent=None, level=1, attrib=None):
        if attrib is None:
            attrib = {}
        the_id = sectionid if sectionid is not None else str(uuid4())

        if 'class' in attrib:
            attrib['class'] = 'report-section {}'.format(attrib['class'])
        else:
            attrib['class'] = 'report-section'

        section = ET.Element('section', attrib={'id': the_id, **attrib})
        section_inner = ET.Element('div', attrib={'class': 'section-inner'})

        hlevel = level + 1
        if title:
            h_el = RSReport.header(hlevel, title, section)
            a_el = ET.Element('a', attrib={'class': 'nav-top', 'href': '#TOC'})
            a_el.text = 'Top'
            h_el.append(a_el)

        section.append(section_inner)
        self.toc.append({
            'level': level,
            'title': title,
            'sectionid': the_id
        })
        real_parent = self.main_el if el_parent is None else el_parent
        real_parent.append(section)

        return section_inner

    def _table_of_contents(self):
        """This calls the creation of the table of contents
        in general this should only be called automatically during
        the report write process

        Returns:
            [type]: [description]
        """
        wrapper = ET.Element('nav', attrib={'id': 'TOC'})
        RSReport.header(3, 'Table of Contents', wrapper)

        def get_ol(level):
            return ET.Element('ol', attrib={'class': 'level-{}'.format(level)})

        parents = [get_ol(1)]
        wrapper.append(parents[-1])

        for item in self.toc:
            # Nothing without a title gets put into the TOC
            if item['title'] is None:
                continue
            if item['level'] > len(parents):
                for _lidx in range(item['level'] - len(parents)):
                    new_ul = get_ol(item['level'])
                    parents[-1].append(new_ul)
                    parents.append(new_ul)
            elif item['level'] < len(parents):
                for _lidx in range(len(parents) - item['level']):
                    parents.pop()

            # Now create the actual LI
            li_el = ET.Element('li')
            anchor = ET.Element('a', attrib={'href': '#{}'.format(item['sectionid'])})
            anchor.text = item['title']
            li_el.append(anchor)
            parents[-1].append(li_el)

        return wrapper

    @staticmethod
    def html_head(report_title, el_parent):

        head = ET.Element('head')
        title = ET.Element('title')
        title.text = report_title
        head.append(title)
        el_parent.append(head)

        return head

    @staticmethod
    def create_table_from_sql(col_names, sql, database, el_parent, attrib=None, id_cols=None):
        if attrib is None:
            attrib = {}
        table = ET.Element('table', attrib=attrib)

        thead = ET.Element('thead')
        theadrow = ET.Element('tr')
        thead.append(theadrow)
        table.append(thead)

        for col in col_names:
            th = ET.Element('th')
            th.text = col
            theadrow.append(th)

        conn = sqlite3.connect(database)
        conn.row_factory = RSReport._dict_factory
        curs = conn.cursor()
        curs.execute(sql)

        tbody = ET.Element('tbody')
        table.append(tbody)

        for row in curs.fetchall():
            tr = ET.Element('tr')
            tbody.append(tr)

            for col, val in row.items():
                val, class_name = RSReport.format_value(val) if id_cols and col not in id_cols else [str(val), 'idVal']
                td = ET.Element('td', attrib={'class': class_name})

                td.text = val
                tr.append(td)

        el_parent.append(table)

    @staticmethod
    def create_table_from_tuple_list(col_names, data, el_parent, attrib=None):

        if attrib is None:
            attrib = {}
        table = ET.Element('table', attrib=attrib)

        thead = ET.Element('thead')
        theadrow = ET.Element('tr')
        thead.append(theadrow)
        table.append(thead)

        for col in col_names:
            th = ET.Element('th')
            th.text = col
            theadrow.append(th)

        tbody = ET.Element('tbody')
        table.append(tbody)

        for row in data:
            tr = ET.Element('tr')
            tbody.append(tr)

            for col in row:
                val, class_name = RSReport.format_value(col)
                td = ET.Element('td', attrib={'class': class_name})

                td.text = val
                tr.append(td)

        el_parent.append(table)

    @staticmethod
    def create_table_from_dict(values, el_parent, attrib=None):
        """Keys go in first col, values in second

        Arguments:
            values {[type]} - - [description]
            database {[type]} - - [description]
            el_parent {[type]} - - [description]

        Returns:
            [type] - - [description]
        """
        if attrib is None:
            attrib = {}
        if 'class' in attrib:
            attrib['class'] = 'dictable {}'.format(attrib['class'])
        else:
            attrib['class'] = 'dictable'

        table = ET.Element('table', attrib=attrib)

        tbody = ET.Element('tbody')
        table.append(tbody)

        for key, val in values.items():

            tr = ET.Element('tr')
            tbody.append(tr)

            th = ET.Element('th')
            th.text = key
            tr.append(th)

            val, class_name = RSReport.format_value(val)
            td = ET.Element('td', attrib={'class': class_name})
            td.text = val
            tr.append(td)

        el_parent.append(table)

    @staticmethod
    def format_value(value, val_type=None):
        """[summary]

        Args:
            value ([type]): [description]
            val_type ([type], optional): Type to try and force

        Returns:
            [type]: [description]
        """
        formatted = ''
        class_name = ''

        try:
            if val_type == str or isinstance(value, str):
                formatted = value
                class_name = 'text'
            elif val_type == float or isinstance(value, float):
                formatted = '{0:,.2f}'.format(value)
                class_name = 'float num'
            elif val_type == int or isinstance(value, int):
                formatted = '{0:,d}'.format(value)
                class_name = 'int num'

        except Exception as e:
            print(e)
            return value, 'unknown'

        return formatted, class_name

    @staticmethod
    def create_ul(values, el_parent, attrib=None, ordered=False):
        if attrib is None:
            attrib = {}

        tagname = 'ul' if ordered is False else 'ol'
        outer = ET.Element(tagname, attrib=attrib)

        for key, val in values.items():
            li = ET.Element('li')
            li.text = val
            outer.append(val)

        el_parent.append(outer)

    @staticmethod
    def _dict_factory(cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d

    @staticmethod
    def header(level, text, el_parent):

        hEl = ET.Element('h{}'.format(level), attrib={'class': 'report-header', 'id': str(uuid4())})
        hEl.text = text
        el_parent.append(hEl)
        return hEl

    def layerprint(self, lyr_el, parent_el, project_root, level: int = 2):
        """Work in progress for printing Riverscapes layers

        Args:
            lyr_el ([type]): [description]
            section ([type]): [description]
            project_root ([type]): [description]
        """
        tag = lyr_el.tag
        name = lyr_el.find('Name').text
        # For geopackages
        layers = lyr_el.find('Layers')

        section = self.section(None, '{}: {}'.format(tag, name), parent_el, level=level, attrib={'class': 'rsc-layer'})

        meta = self.xml_project.get_metadata_dict(node=lyr_el)
        if meta is not None:
            self.create_table_from_dict(meta, section, attrib={'class': 'fullwidth'})

        path_el = ET.Element('pre', attrib={'class': 'path'})
        pathstr = lyr_el.find('Path').text
        size = 0
        fpath = os.path.join(project_root, pathstr)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)

        if layers is not None:
            layers_container = ET.Element('div', attrib={'class': 'inner-layer-container'})
            RSReport.header(level + 1, 'Layers', layers_container)
            for layer_el in list(layers):
                self.layerprint(layer_el, layers_container, os.path.join(project_root, pathstr), level=level + 1)

            section.append(layers_container)

        footer = ET.Element('div', attrib={'class': 'layer-footer'})
        path_el.text = 'Project path: {}  ({})'.format(pathstr, sizeof_fmt(size))
        footer.append(path_el)
        section.append(footer)