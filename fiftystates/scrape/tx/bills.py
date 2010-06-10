from __future__ import with_statement
import urlparse
import datetime as dt

from fiftystates.scrape.tx import metadata
from fiftystates.scrape.tx.utils import chamber_name, parse_ftp_listing
from fiftystates.scrape.bills import BillScraper, Bill

import lxml.etree


class TXBillScraper(BillScraper):
    state = 'tx'
    _ftp_root = 'ftp://ftp.legis.state.tx.us/'

    def scrape(self, chamber, year):
        if int(year) < 2009 or int(year) > dt.date.today().year:
            raise NoDataForYear(year)

        # Expect the first year of a session
        if int(year) % 2 == 0:
            raise NoDataForYear(year)

        session_num = str((int(year) - 1989) / 2 + 71)
        subs = []
        for s in metadata['sessions']:
            if s['name'] == session_num:
                subs = s['sub_sessions']
                break

        self.scrape_session(chamber, session_num + 'R')
        for session in subs:
            self.scrape_session(chamber, session)

    def scrape_session(self, chamber, session):
        billdirs_path = '/bills/%s/billhistory/%s_bills/' % (
            session, chamber_name(chamber))
        billdirs_url = urlparse.urljoin(self._ftp_root, billdirs_path)

        with self.urlopen(billdirs_url) as bill_dirs:
            for dir in parse_ftp_listing(bill_dirs):
                bill_url = urlparse.urljoin(billdirs_url, dir) + '/'
                with self.urlopen(bill_url) as bills:
                    for history in parse_ftp_listing(bills):
                        self.scrape_bill(chamber, session,
                                         urlparse.urljoin(bill_url, history))

    def scrape_bill(self, chamber, session, url):
        with self.urlopen(url) as data:
            bill = self.parse_bill_xml(chamber, session, data)
            bill.add_source(url)

            versions_url = url.replace('billhistory', 'billtext/html')
            versions_url = '/'.join(versions_url.split('/')[0:-1])

            bill_prefix = bill['bill_id'].split()[0]
            bill_num = int(bill['bill_id'].split()[1])
            long_bill_id = "%s%05d" % (bill_prefix, bill_num)

            with self.urlopen(versions_url) as versions_list:
                bill.add_source(versions_url)
                for version in parse_ftp_listing(versions_list):
                    if version.startswith(long_bill_id):
                        version_name = version.split('.')[0]
                        version_url = urlparse.urljoin(versions_url + '/',
                                                       version)
                        bill.add_version(version_name, version_url)

            self.save_bill(bill)

    def parse_bill_xml(self, chamber, session, txt):
        root = lxml.etree.fromstring(txt)
        bill_id = ' '.join(root.attrib['bill'].split(' ')[1:])
        bill_title = root.findtext("caption")

        if session[2] == 'R':
            session = session[0:2]

        bill = Bill(session, chamber, bill_id, bill_title)

        for action in root.findall('actions/action'):
            act_date = dt.datetime.strptime(action.findtext('date'),
                                            "%m/%d/%Y")

            extra = {}
            extra['action_number'] = action.find('actionNumber').text
            comment = action.find('comment')
            if comment is not None and comment.text:
                extra['comment'] = comment.text.strip()

            actor = {'H': 'lower',
                     'S': 'upper',
                     'E': 'executive'}[extra['action_number'][0]]

            bill.add_action(actor, action.findtext('description'),
                            act_date, **extra)

        for author in root.findtext('authors').split(' | '):
            if author != "":
                bill.add_sponsor('author', author)
        for coauthor in root.findtext('coauthors').split(' | '):
            if coauthor != "":
                bill.add_sponsor('coauthor', coauthor)
        for sponsor in root.findtext('sponsors').split(' | '):
            if sponsor != "":
                bill.add_sponsor('sponsor', sponsor)
        for cosponsor in root.findtext('cosponsors').split(' | '):
            if cosponsor != "":
                bill.add_sponsor('cosponsor', cosponsor)

        bill['subjects'] = []
        for subject in root.iterfind('subjects/subject'):
            bill['subjects'].append(subject.text.strip())

        return bill