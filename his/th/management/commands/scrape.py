import re
from datetime import datetime, timedelta
from typing import List, Optional

from django.core.exceptions import FieldError
from django.core.management import BaseCommand
from django.utils.timezone import now, get_current_timezone
from random_user_agent.params import SoftwareName, OperatingSystem
from random_user_agent.user_agent import UserAgent
from selenium.common.exceptions import TimeoutException, InvalidSelectorException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.support.wait import WebDriverWait

from ...models import Meeting, Race, Runner, Outcome

RACE_TYPES = ['R', 'G', 'H']


class NoRaceError(Exception):
    """no race"""


class NoFixedOddsError(Exception):
    """odds are all N/A"""


class BadExoticsError(Exception):
    """too many weird exotics"""


class NotBothOddsError(Exception):
    """missing tote or fixed odds"""


class NotEnoughRunnersError(Exception):
    """no 3 or 4 winner"""


class WinnerNumberNotFoundError(Exception):
    """no 3 or 4 winner"""


class NoMeetings(Exception):
    """no races on day"""


class Command(BaseCommand):
    help = 'Scrape racing history'

    def handle(self, *args, **kwargs):
        self.stdout.write('started scraping...')

        day_stamp = now() - timedelta(days=365)
        last_meeting = Meeting.objects.order_by('-date').first()
        if last_meeting:
            day_stamp = datetime(last_meeting.date.year, last_meeting.date.month, last_meeting.date.day, tzinfo=get_current_timezone())

        with TabSite(self.stdout.write) as tab_site:
            while day_stamp <= now():
                try:
                    raw_races = tab_site.get_races(day_stamp)
                except NoMeetings as exc:
                    raw_races = {}
                else:
                    if not raw_races:
                        raise ValueError(f'expected races ot have data on {day_stamp}')

                for type_, raw_meeting in raw_races.items():
                    for meeting in raw_meeting:
                        for href in meeting['races']:
                            try:
                                raw_race = tab_site.get_race(href)
                                race = self.save_race(day_stamp, type_, meeting, raw_race)
                            except (NoRaceError, NoFixedOddsError, BadExoticsError, NotBothOddsError,
                                    NotEnoughRunnersError, WinnerNumberNotFoundError, TimeoutException) as exc:
                                self.stdout.write(f'{exc}')
                                continue
                            self.stdout.write(f'Created {race}')

                day_stamp += timedelta(days=1)

        self.stdout.write('scraping ended')

    def save_race(self, day_stamp, type_, raw_meeting: dict, raw_race: dict) -> Race:
        meeting = self._save_meeting(day_stamp, type_, raw_meeting, raw_race)
        race = self._save_race(meeting, raw_race)
        runners = self._save_runners(race, raw_race)
        outcome = self._save_outcome(race, raw_race, runners)
        return race

    def _save_meeting(self, day_stamp, type_, raw_meeting: dict, raw_race: dict) -> Meeting:
        meeting, created = Meeting.objects.update_or_create(
            date=day_stamp.date(),
            venue=raw_race['venue'],
            defaults={
                'region': raw_meeting['region'],
                'race_type': type_,
                'track_condition': raw_race['track_condition'],
                'weather_condition': raw_race['weather_condition'],
            }
        )
        if created:
            self.stdout.write(f'Created {meeting}')
        return meeting

    def _save_race(self, meeting: Meeting, raw_race: dict) -> Race:
        hour, min = raw_race['time'].split(':')
        race, created = Race.objects.update_or_create(
            meeting=meeting,
            number=raw_race['number'],
            defaults={
                'href': raw_race['href'],
                'distance': raw_race['distance'],
                'name': raw_race['race_name'],
                'start_time': datetime(
                    meeting.date.year, meeting.date.month, meeting.date.day,
                    int(hour), int(min), tzinfo=get_current_timezone()),
                'has_results': True,
            }
        )
        if created:
            self.stdout.write(f'Created {race}')
        return race

    def _save_runners(self, race: Race, raw_race: dict) -> List[Runner]:
        runners = []
        for raw_runner in raw_race['runners']:
            runner, created = Runner.objects.update_or_create(
                race=race,
                number=raw_runner['number'],
                defaults={
                    'name': raw_runner['name'],
                    'barrier': raw_runner['barrier'],
                    'trainer': raw_runner['trainer'],
                    'rider': raw_runner['rider'],
                    'fixed_win': raw_runner['fixed_win'],
                    'fixed_place': raw_runner['fixed_place'],
                    'tote_win': raw_runner['tote_win'],
                    'tote_place': raw_runner['tote_place'],
                }
            )
            # if created:
            #     self.stdout.write(f'Created {runner}')
            runners.append(runner)
        return runners

    def _save_outcome(self, race: Race, raw_race: dict, runners: List[Runner]) -> Outcome:
        try:
            raw_race['outcome']['first'] = [r for r in runners if r.number == int(raw_race['outcome']['first'])][0]
            raw_race['outcome']['second'] = [r for r in runners if r.number == int(raw_race['outcome']['second'])][0]
            raw_race['outcome']['third'] = [r for r in runners if r.number == int(raw_race['outcome']['third'])][0]
            if raw_race['outcome']['fourth']:
                raw_race['outcome']['fourth'] = [r for r in runners if r.number == int(raw_race['outcome']['fourth'])][0]
            else:
                del raw_race['outcome']['fourth']
        except IndexError as exc:
            raise WinnerNumberNotFoundError(str(exc))
        try:
            outcome, created = Outcome.objects.update_or_create(
                race=race,
                defaults=raw_race['outcome']
            )
        except FieldError as exc:
            raise
        if created:
            self.stdout.write(f'Created {outcome}')
        return outcome


class TabSite:

    def __init__(self, write):
        self.write = write

        software_names = [SoftwareName.CHROME.value]
        operating_systems = [OperatingSystem.WINDOWS.value]
        user_agent_rotator = UserAgent(software_names=software_names, operating_systems=operating_systems, limit=100)
        user_agent = user_agent_rotator.get_random_user_agent()

        chrome_options = Options()
        # chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-setuid-sandbox')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument(f'--user-agent={user_agent}')
        chrome_options.add_argument('--dns-prefetch-disable')
        chrome_options.add_argument('--lang=en-US')
        # chrome_options.add_argument('--start-maximized')
        chrome_options.add_argument('--window-size=1420,1080')
        chrome_prefs = {
            'intl.accept_languages': 'en-US',
        }
        chrome_options.add_experimental_option('prefs', chrome_prefs)
        self.driver = WebDriver(chrome_options=chrome_options)

        # set waiting on elements to load
        # self.driver.implicitly_wait(5)

        # load cookies
        # if account.cookies:
        #     cookies = json.loads(account.cookies)
        #     self.driver.get(URL_INSTAGRAM)
        #     for cookie in cookies:
        #         self.driver.add_cookie(cookie)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.driver.quit()

    def get_races(self, day_stamp: datetime):
        day_str = day_stamp.strftime('%Y-%m-%d')
        races = {}
        for race_type in RACE_TYPES:
            self.write(f'Scraping {race_type} on day {day_str}')
            races[race_type] = ResultsPage(
                self.write, self.driver, day_str, race_type
            ).get_races()
            break
        return races

    def get_race(self, href: str) -> dict:
        raw_race = RacePage(self.write, self.driver, href).get_race_result(href)
        if not raw_race['runners']:
            raise NoRaceError('no runners')
        return raw_race


class BasePage:
    URL_PATTERN = ''

    def __init__(self, write, driver: WebDriver, *params):
        self.write = write
        self.driver = driver
        url = self.URL_PATTERN.format(*params)
        self.write(f'Scraping {url}')
        self.driver.get(url)
        self._wait_until()

    def _wait_until(self):
        pass


class ResultsPage(BasePage):
    URL_PATTERN = 'https://www.tab.com.au/racing/meetings/results/{}/{}'

    def _wait_until(self):
        try:
            WebDriverWait(self.driver, 10).until(
                lambda driver: driver.find_element_by_xpath('//div/race-brief')
            )
        except TimeoutException as exc:
            if 'No results available' in self.driver.page_source:
                raise NoMeetings()
            raise exc

    @property
    def meeting_boxes(self):
        meetings = []
        for el in self.driver.find_elements_by_class_name('meeting-name'):
            name, reg = el.text.replace('(', '').replace(')', '').split('\n')
            meetings.append({
                'name': name,
                'region': reg,
            })
        return meetings

    @property
    def racing_lines(self) -> List:
        races = []
        for el in self.driver.find_elements_by_class_name('race-card-row'):
            boxes = el.find_elements_by_class_name('race-wrapper')
            hrefs = [b.get_attribute('href') for b in boxes]
            races.append(hrefs)
        return races

    def get_races(self) -> List[dict]:
        races = []
        for meeting, boxes in zip(self.meeting_boxes, self.racing_lines):
            meeting['races'] = boxes
            races.append(meeting)
        return races


class RacePage(BasePage):
    URL_PATTERN = '{}'

    def _wait_until(self):
        WebDriverWait(self.driver, 10).until(
            lambda driver: driver.find_element_by_xpath('//header/div/div/div[@class="race-name"]')
        )
        WebDriverWait(self.driver, 10).until(
            lambda driver: driver.find_element_by_class('race-metadata-list')
        )

    @property
    def status(self) -> str:
        return self.driver.find_element_by_class_name('status-text').text

    @property
    def venue(self) -> str:
        return self.driver.find_element_by_class_name('meeting-info-description').text.strip()

    @property
    def track_condition(self) -> str:
        return self.driver.find_element_by_class_name('meeting-info-track-condition').text

    @property
    def weather_condition(self) -> str:
        return self.driver.find_element_by_class_name('meeting-info-weather-condition-description').text

    @property
    def race_metadata(self):
        return self.driver.find_element_by_class_name('race-metadata-list')

    @property
    def distance(self) -> int:
        return int(self.race_metadata.find_elements_by_tag_name('li')[1].text.replace('m', ''))

    @property
    def number(self) -> int:
        return int(self.driver.find_element_by_class_name('race-number').text.replace('R', ''))

    @property
    def time(self) -> str:
        return self.driver.find_element_by_class_name('race-header-race-time').text

    @property
    def race_name(self) -> str:
        return self.driver.find_element_by_class_name('race-name').text.strip()

    @property
    def runners(self) -> List[dict]:
        runners = []
        runner_table = self.driver.find_element_by_class_name('pseudo-body')
        for row in runner_table.find_elements_by_class_name('row'):
            runner = self._parse_runner(row)
            if not runner:
                continue
            runners.append(runner)
        return runners

    @property
    def outcome(self) -> List[dict]:
        race_tables = self.driver.find_elements_by_class_name('race-table')
        winners = self._parse_winners(race_tables[0])
        exotics = self._parse_exotics(race_tables[1])
        return {**winners, **exotics}

    def _parse_runner(self, row) -> Optional[dict]:
        runner_title = row.find_element_by_class_name('runner-name').text
        number = row.find_element_by_class_name('number-cell').text
        name, barrier = runner_title.split('(')
        owners = row.find_element_by_class_name('runner-metadata-list')
        owners = owners.find_elements_by_class_name('full-name')
        rider, trainer = None, None
        try:
            rider = owners[0].text
            trainer = owners[1].text
        except IndexError:
            pass
        try:
            fixed_win, fixed_place, tote_win, tote_place = row.find_elements_by_class_name('price-cell')
        except ValueError as exc:
            raise NotBothOddsError(str(exc))
        if fixed_win.text in {'SCR', '(L)SCR'}:
            return
        try:
            return {
                'number': int(number),
                'name': name.strip(),
                'barrier': int(barrier.strip(')')),
                'rider': rider,
                'trainer': trainer,
                'fixed_win': float(fixed_win.text),
                'fixed_place': float(fixed_place.text),
                'tote_win': float(tote_win.text),
                'tote_place': float(tote_place.text),
            }
        except ValueError as exc:
            if 'N/A' in str(exc):
                raise NoFixedOddsError(str(exc))
            raise

    def _parse_winners(self, table) -> dict:
        rows = table.find_elements_by_class_name('runner-details')
        try:
            first_number = re.search('^(\d*)\.', rows[0].text).groups()[0]
            second_number = re.search('^(\d*)\.', rows[1].text).groups()[0]
            third_number = re.search('^(\d*)\.', rows[2].text).groups()[0]
            fourth_number = re.search('^(\d*)\.', rows[3].text).groups()[0]
        except IndexError as exc:
            raise NotEnoughRunnersError(str(exc))
        return {
            'first': first_number,
            'second': second_number,
            'third': third_number,
            'fourth': fourth_number,
        }

    def _parse_exotics(self, table) -> dict:
        duets = ['12', '13', '23']
        exotics = {}
        for row in table.find_elements_by_class_name('result-item'):
            tds = row.find_elements_by_tag_name('td')
            price = tds[2].text
            if price in {'Refunded'}:
                continue  # skip bad exotics
            name = tds[0].text.replace(' ', '_').lower()
            if any(w in name for w in ['double', 'big']):
                continue
            if name == 'duet':
                try:
                    name += duets.pop(0)
                except IndexError as exc:
                    raise BadExoticsError(str(exc))
            try:
                price = price.replace('$', '').replace(',', '')
                try:
                    ix = price.index('\n')
                    price = price[:ix]
                except ValueError:
                    pass
                exotics[name] = float(price)
            except ValueError as exc:
                raise
        return exotics

    def get_race_result(self, href: str) -> dict:
        result = {}
        if self.status == 'Abandoned':
            raise NoRaceError('race abandoned')
        result['venue'] = self.venue
        result['track_condition'] = self.track_condition
        result['weather_condition'] = self.weather_condition
        try:
            result['distance'] = self.distance
        except ValueError as exc:
            raise
        result['number'] = self.number
        result['href'] = href
        result['time'] = self.time
        result['race_name'] = self.race_name
        result['runners'] = self.runners
        result['outcome'] = self.outcome
        return result
