import os
import json
import time
import hashlib
import smtplib
import logging
import re
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional
import requests
from playwright.sync_api import sync_playwright

# ==============================
# Logging
# ==============================
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/job_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==============================
# Helpers
# ==============================
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_dt_safe(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return datetime.fromisoformat(s)
    except Exception:
        return None

def hours_ago(dt: datetime) -> float:
    return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0

def stable_hash(*parts: str) -> str:
    joined = '||'.join(p.strip() for p in parts if p)
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()[:24]

def normalize_space(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()

# ==============================
# Core class
# ==============================
class JobBoardMonitor:
    NEW_WINDOW_HOURS = 48  # include only postings within last 24–48h; use 48h window

    def __init__(self):
        self.gmail_user = os.environ.get('GMAIL_USER')
        self.gmail_password = os.environ.get('GMAIL_PASSWORD')
        self.gist_token = os.environ.get('GIST_TOKEN')
        self.job_history: Dict[str, Dict[str, dict]] = self.load_gist_file('job_history.json') or {}
        self.sent_jobs: Dict[str, List[str]] = self.load_gist_file('sent_jobs.json') or {}
        self.found_jobs: Dict[str, Dict[str, dict]] = {}  # per-run catalog of *all* jobs discovered
        self.candidate_new_jobs: List[dict] = []          # after filtering + age-window

        # Company configurations (selectors tightened; fallbacks added)
        self.job_boards = {
            'Google': {
                'url': 'https://www.google.com/about/careers/applications/jobs/results/?location=United%20States&sort_by=date&q=product%2C%20program%2C%20project',
                'method': 'playwright',
                'selectors': [
                    'a.gc-card__title-link',
                    'div[jsname] a[href*="/jobs/results/"]'
                ],
                'wait_for': 12000,
                'scroll': True,
                'pagination': True
            },
            'Intrinsic': {
                'url': 'https://boards.greenhouse.io/intrinsic',
                'method': 'greenhouse_api',
                'board_token': 'intrinsic'
            },
            'Waymo': {
                'url': 'https://careers.withwaymo.com/jobs/search?page=1&query=project%2C+program%2C+product',
                'method': 'playwright',
                'selectors': ['a[data-testid="job-title"]'],
                'wait_for': 6000,
                'pagination': True
            },
            'Wing': {
                'url': 'https://wing.com/careers',
                'method': 'playwright',
                'selectors': [
                    'a[href*="/careers/roles/"] h3',
                    'a[href*="/careers/roles/"] .c-card__title'
                ],
                'wait_for': 6000,
                'scroll': True
            },
            'X Moonshot': {
                'url': 'https://x.company/careers/',
                'method': 'playwright',
                'selectors': ['a[href*="/careers/"] h3', 'article a[href*="jobs"]'],
                'wait_for': 6000,
                'scroll': True
            },
            'Apple': {
                'url': 'https://jobs.apple.com/en-us/search?sort=newest&key=Product%25252C%252520Program%25252C%252520Project&location=united-states-USA',
                'method': 'playwright',
                'selectors': [
                    'table#tblResultSet td[class*="table-col-1"] a[id*="job-link"]'
                ],
                'wait_for': 9000,
                'scroll': True,
                'pagination': True
            },
            'NVIDIA': {
                'url': 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?q=product,%20program,%20project',
                'method': 'playwright',
                'selectors': ['a[data-automation-id="jobTitle"]'],
                'wait_for': 8000,
                'pagination': True
            },
            'Netflix': {
                'url': 'https://explore.jobs.netflix.net/careers?domain=netflix.com&sort_by=new',
                'method': 'playwright',  # fallback to scraping; GH-like JSON is not public
                'selectors': [
                    'a[href*="/careers/jobs/"] h3',
                    'a[data-testid="job-card"] h3'
                ],
                'wait_for': 8000,
                'scroll': True,
                'pagination': True
            },
            'Anthropic': {
                'url': 'https://boards.greenhouse.io/anthropic',
                'method': 'greenhouse_api',
                'board_token': 'anthropic'
            },
            'Tesla': {
                'url': 'https://www.tesla.com/careers/search/?region=5&site=US&type=1',
                'method': 'playwright',
                'selectors': ['tbody tr td:first-child a[href*="/careers/"]'],
                'wait_for': 15000,
                'scroll': True,
                'handle_cloudflare': True
            },
            'Amazon': {
                'url': 'https://www.amazon.jobs/en/search?offset=0&result_limit=10&sort=recent&job_type%5B%5D=Full-Time&country%5B%5D=USA&state%5B%5D=New%20York&state%5B%5D=New%20Jersey',
                'method': 'playwright',
                'selectors': ['h3.job-title a'],
                'wait_for': 6000,
                'pagination': True
            },
            'Meta': {
                'url': 'https://www.metacareers.com/jobs',
                'method': 'playwright',
                'selectors': [
                    'a[href^="/v2/jobs/"] div[role="heading"]',
                    'a[href^="/v2/jobs/"] span'
                ],
                'wait_for': 9000,
                'scroll': True,
                'pagination': True
            },
            'SpaceX': {
                'url': 'https://www.spacex.com/careers/jobs/',
                'method': 'hybrid',  # try GH API then PW fallback
                'board_token': 'spacex',
                'selectors': [
                    'a[href*="/careers/detail/"] h3',
                    'a[href*="/careers/detail/"]'
                ],
                'wait_for': 7000,
                'scroll': True
            },
            'Stripe': {
                'url': 'https://stripe.com/jobs/search?office_locations=North+America--New+York',
                'method': 'playwright',
                'selectors': ['a.JobsListings__link', 'a[href*="/jobs/positions/"]'],
                'wait_for': 6000
            },
            'Uber': {
                'url': 'https://www.uber.com/us/en/careers/list/?location=USA-New%20York-New%20York&location=USA-New%20York-Bronx',
                'method': 'playwright',
                'selectors': [
                    'a[data-baseweb="card"] h3',
                    'a[href*="/careers/list/positions/"] h3'
                ],
                'wait_for': 8000,
                'scroll': True,
                'pagination': True
            },
            'Two Sigma': {
                'url': 'https://careers.twosigma.com/careers/OpenRoles',
                'method': 'playwright',
                'selectors': ['a[href*="JobDetail"] .job-title', 'span.job-title'],
                'wait_for': 6000,
                'scroll': True
            },
            'Microsoft': {
                'url': 'https://jobs.careers.microsoft.com/global/en/search?q=%22product%22%20OR%20%22project%22%20OR%20%22program%22&lc=United%20States&et=Full-Time&l=en_us&pg=1&pgSz=20&o=Recent',
                'method': 'playwright',
                'selectors': [
                    'a[data-bi-name="jobTitleLink"]',
                    'div.job-title a',
                    'h2[data-automation-id="jobTitle"]',
                    'span[data-automation-id="jobTitle"]'
                ],
                'wait_for': 7000,
                'pagination': True
            },
            'OpenAI': {
                'url': 'https://openai.com/careers/search/',
                'method': 'hybrid',  # try GH first, then PW
                'board_token': 'openai',
                'selectors': [
                    'a[href*="/careers/jobs/"] h3',
                    'a[href*="/careers/jobs/"] span'
                ],
                'wait_for': 8000,
                'scroll': True,
            }
        }

    # ------------------------------
    # Gist I/O
    # ------------------------------
    def _auth_headers(self):
        return {'Authorization': f'token {self.gist_token}'} if self.gist_token else {}

    def ensure_gist_exists(self) -> Optional[str]:
        if not self.gist_token:
            logger.warning("No GIST_TOKEN set — using ephemeral in-memory storage.")
            return None
        try:
            r = requests.get('https://api.github.com/gists', headers=self._auth_headers(), timeout=20)
            if r.status_code == 200:
                for g in r.json():
                    files = g.get('files', {}) or {}
                    if 'job_history.json' in files and 'sent_jobs.json' in files:
                        return g['id']
            # Create new gist
            payload = {
                'description': 'Job Board Monitor History',
                'public': False,
                'files': {
                    'job_history.json': {'content': json.dumps({})},
                    'sent_jobs.json': {'content': json.dumps({})}
                }
            }
            cr = requests.post('https://api.github.com/gists', headers=self._auth_headers(), json=payload, timeout=20)
            if cr.status_code in (200, 201):
                return cr.json()['id']
        except Exception as e:
            logger.error(f'ensure_gist_exists error: {e}')
        return None

    def load_gist_file(self, filename: str):
        if not self.gist_token:
            return None
        try:
            r = requests.get('https://api.github.com/gists', headers=self._auth_headers(), timeout=20)
            if r.status_code == 200:
                for g in r.json():
                    files = g.get('files', {}) or {}
                    if filename in files:
                        raw = files[filename].get('raw_url')
                        if raw:
                            fr = requests.get(raw, timeout=20)
                            if fr.status_code == 200:
                                try:
                                    return json.loads(fr.text or '{}')
                                except Exception:
                                    return {}
        except Exception as e:
            logger.error(f'load_gist_file({filename}) error: {e}')
        return None

    def save_gist_files(self):
        gist_id = self.ensure_gist_exists()
        if not gist_id or not self.gist_token:
            logger.warning("Skipping Gist save (no token or gist).")
            return
        try:
            payload = {
                'files': {
                    'job_history.json': {'content': json.dumps(self.job_history, indent=2)},
                    'sent_jobs.json': {'content': json.dumps(self.sent_jobs, indent=2)},
                }
            }
            pr = requests.patch(f'https://api.github.com/gists/{gist_id}', headers=self._auth_headers(), json=payload, timeout=20)
            if pr.status_code not in (200, 201):
                logger.error(f'Gist save failed {pr.status_code}: {pr.text[:200]}')
            else:
                logger.info(f"Gist {gist_id} updated.")
        except Exception as e:
            logger.error(f'save_gist_files error: {e}')

    # ------------------------------
    # Junk filtering
    # ------------------------------
    def is_junk_text(self, text: str) -> bool:
        if not text or len(text.strip()) < 2:
            return True
        t = normalize_space(text).lower()

        junk_substrings = [
            'cookie', 'consent', 'privacy', 'manage preferences', 'do not sell',
            'help center', 'about us', 'newsroom', 'careers blog', 'submit resume',
            'view role', 'read more', 'all departments', 'all locations',
            'no positions available', 'load more', 'show more', 'view all',
            'sign in', 'log in', 'create account', 'subscribe', 'follow us',
            'contact us', 'search results', 'filters', 'apply filters',
            # extra noise seen in real boards
            'inside uber', 'view all jobs', 'browse jobs', 'global nav', 'site map',
            'learn more', 'open positions', 'clear filters', 'reset filters',
            'locations•', '+ locations', ' +', '•engineering', 'help / support'
        ]
        if any(s in t for s in junk_substrings):
            return True

        # drop heavy UI strings with separators but no role words
        if '•' in t and not any(w in t for w in [
            'engineer','manager','product','program','project','designer','director','analyst','scientist','lead','pm'
        ]):
            return True

        # drop single-word headings
        if len(t.split()) == 1 and t in {'global','careers','jobs','teams','about','meta','facebook','instagram'}:
            return True

        # Must include at least one job-ish keyword
        jobish = ['product','program','project','manager','engineer','developer','analyst',
                  'designer','scientist','director','lead','senior','technical','pm']
        if not any(k in t for k in jobish):
            return True

        return False

    # ------------------------------
    # Relevance (relaxed to title-only to improve coverage)
    # ------------------------------
    def is_relevant_job(self, title: str, location: str = '') -> bool:
        t = (title or '').lower()
        return any(k in t for k in ['product', 'program', 'project'])

    # ------------------------------
    # Job key & storage
    # ------------------------------
    def make_job_key(self, company: str, title: str, href: Optional[str], external_id: Optional[str]) -> str:
        # Prefer external_id, then URL, then title
        if external_id:
            return f'{company}:{external_id}'
        if href:
            return f'{company}:{stable_hash(href)}'
        return f'{company}:{stable_hash(title)}'

    def record_discovery(self, company: str, key: str, title: str, url: str, posted_at: Optional[datetime], location: Optional[str] = None):
        """Update run catalog + persistent job_history first_seen"""
        if company not in self.found_jobs:
            self.found_jobs[company] = {}
        self.found_jobs[company][key] = {
            'title': title, 'url': url, 'posted_at': posted_at.isoformat() if posted_at else None,
            'discovered_at': now_utc_iso(), 'location': location or ''
        }

        if company not in self.job_history:
            self.job_history[company] = {}
        if key not in self.job_history[company]:
            self.job_history[company][key] = {
                'title': title, 'first_seen': now_utc_iso(), 'url': url,
                'posted_at': posted_at.isoformat() if posted_at else None, 'location': location or ''
            }

    # ------------------------------
    # Greenhouse API
    # ------------------------------
    def scrape_greenhouse_api(self, company: str, board_token: str) -> int:
        count = 0
        try:
            jobs_url = f'https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs'
            r = requests.get(jobs_url, timeout=20)
            if r.status_code != 200:
                logger.warning(f'{company} GH API {r.status_code}')
                return 0

            for j in r.json().get('jobs', []):
                title = (j.get('title') or '').strip()
                location = (j.get('location', {}) or {}).get('name', '')
                if not self.is_relevant_job(title, location):
                    continue
                absolute_url = j.get('absolute_url') or f'https://boards.greenhouse.io/{board_token}'
                external_id = str(j.get('id')) if j.get('id') is not None else None
                posted_at = parse_dt_safe(j.get('updated_at') or j.get('created_at'))

                key = self.make_job_key(company, title, absolute_url, external_id)
                self.record_discovery(company, key, title, absolute_url, posted_at, location)
                count += 1
        except Exception as e:
            logger.error(f'{company} GH API error: {e}')
        return count

    # ------------------------------
    # Playwright scraping
    # ------------------------------
    def scrape_playwright(self, company: str, config: Dict) -> int:
        added = 0
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled']
                )
                context = browser.new_context(
                    viewport={'width': 1280, 'height': 900},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                if config.get('handle_cloudflare'):
                    context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                page = context.new_page()
                page.goto(config['url'], wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(config.get('wait_for', 6000))

                # try dismissing popups
                self.dismiss_popups(page)

                pages_checked = 0
                max_pages = 5 if config.get('pagination') else 1
                while pages_checked < max_pages:
                    pages_checked += 1

                    if config.get('scroll'):
                        self.infinite_scroll(page)

                    found_any = False
                    for sel in config.get('selectors', []):
                        try:
                            els = page.locator(sel).all()
                        except Exception:
                            els = []
                        if not els:
                            continue
                        found_any = True
                        for el in els:
                            raw_text = normalize_space(el.text_content() or '')
                            href = None
                            try:
                                href = el.get_attribute('href')
                                if (not href) and el.locator('xpath=ancestor-or-self::a[1]').count() > 0:
                                    href = el.locator('xpath=ancestor-or-self::a[1]').first.get_attribute('href')
                            except Exception:
                                pass

                            if self.is_junk_text(raw_text):
                                continue

                            title = raw_text[:200]
                            url = href if href and href.startswith('http') else config['url']
                            key = self.make_job_key(company, title, url, None)
                            # No reliable 'posted_at' from scraped UIs -> defer to first_seen for freshness window
                            before = len(self.found_jobs.get(company, {}))
                            self.record_discovery(company, key, title, url, posted_at=None)
                            after = len(self.found_jobs.get(company, {}))
                            if after > before:
                                added += 1

                        break  # stop after first selector that yielded results

                    if not found_any:
                        break

                    if config.get('pagination') and not self.next_page(page, pages_checked):
                        break

                browser.close()
        except Exception as e:
            logger.error(f'{company} Playwright error: {e}')
        return added

    def dismiss_popups(self, page):
        sels = [
            'button:has-text("Accept")','button:has-text("OK")','button:has-text("Got it")',
            'button[aria-label*="close"]','button[aria-label*="dismiss"]','button:has-text("Continue")',
            'button:has-text("Agree")','button:has-text("Allow all")'
        ]
        for s in sels:
            try:
                if page.locator(s).count() > 0:
                    page.locator(s).first.click()
                    page.wait_for_timeout(800)
            except Exception:
                pass

    def infinite_scroll(self, page):
        try:
            load_more = ['button:has-text("View More")','button:has-text("Load More")','button:has-text("Show More")','a:has-text("View More")']
            for _ in range(3):
                clicked = False
                for s in load_more:
                    try:
                        if page.locator(s).count() > 0:
                            page.locator(s).first.click()
                            page.wait_for_timeout(1500)
                            clicked = True
                            break
                    except Exception:
                        pass
                if not clicked:
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    page.wait_for_timeout(1200)
        except Exception:
            pass

    def next_page(self, page, current_page: int) -> bool:
        sels = [
            f'a:has-text("{current_page + 1}")', f'button:has-text("{current_page + 1}")',
            'a:has-text("Next")','button:has-text("Next")','a[aria-label*="Next"]','button[aria-label*="Next"]'
        ]
        for s in sels:
            try:
                if page.locator(s).count() > 0:
                    page.locator(s).first.click()
                    page.wait_for_timeout(2500)
                    return True
            except Exception:
                pass
        return False

    # ------------------------------
    # Orchestrate scraping with fallbacks
    # ------------------------------
    def scrape_company(self, company: str, cfg: Dict):
        method = cfg.get('method', 'playwright')
        added = 0

        if method == 'greenhouse_api':
            added = self.scrape_greenhouse_api(company, cfg['board_token'])

        elif method == 'playwright':
            added = self.scrape_playwright(company, cfg)

        elif method == 'hybrid':
            # Try GH API first; if nothing added, try Playwright fallback (if selectors exist)
            gh_added = 0
            if 'board_token' in cfg:
                gh_added = self.scrape_greenhouse_api(company, cfg['board_token'])
            added += gh_added
            if gh_added == 0 and cfg.get('selectors'):
                logger.info(f'{company}: GH API yielded 0 — trying Playwright fallback.')
                added += self.scrape_playwright(company, cfg)

        else:
            # Default to Playwright
            added = self.scrape_playwright(company, cfg)

        logger.info(f'{company}: discovered {added} items this run.')

    def collect_all(self):
        for company, cfg in self.job_boards.items():
            logger.info(f'=== {company} ===')
            try:
                self.scrape_company(company, cfg)
            except Exception as e:
                logger.error(f'{company} scrape error: {e}')
            time.sleep(1.2)  # gentle rate limit

    # ------------------------------
    # New-job filtering (24–48h window) and dedupe
    # ------------------------------
    def compute_new_jobs(self):
        window_hours = self.NEW_WINDOW_HOURS

        for company, jobs in self.found_jobs.items():
            for key, info in jobs.items():
                # Determine "posted time" to enforce age window
                posted_at = parse_dt_safe(info.get('posted_at'))
                if not posted_at:
                    # Fallback: first_seen from history for this key
                    hist = (self.job_history.get(company) or {}).get(key, {})
                    posted_at = parse_dt_safe(hist.get('posted_at') or hist.get('first_seen'))
                if not posted_at:
                    # Last fallback: discovered_at in this run
                    posted_at = parse_dt_safe(info.get('discovered_at'))

                if not posted_at:
                    # If still missing, skip (we can't confirm "new")
                    continue

                if hours_ago(posted_at) > window_hours:
                    continue  # too old

                # Skip if already emailed before
                if key in (self.sent_jobs.get(company) or []):
                    continue

                self.candidate_new_jobs.append({
                    'company': company,
                    'key': key,
                    'title': info.get('title'),
                    'url': info.get('url'),
                    'timestamp': posted_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                    'location': info.get('location','')
                })

        # De-duplicate by (company + title + url)
        seen = set()
        unique = []
        for j in self.candidate_new_jobs:
            sig = (j['company'], normalize_space(j['title']), j['url'])
            if sig not in seen:
                seen.add(sig)
                unique.append(j)
        self.candidate_new_jobs = unique

    # ------------------------------
    # Email
    # ------------------------------
    def build_email_html(self) -> str:
        all_companies = sorted(self.job_boards.keys())
        jobs_by_company: Dict[str, List[dict]] = {c: [] for c in all_companies}
        for j in self.candidate_new_jobs:
            jobs_by_company[j['company']].append(j)

        html = f"""
        <html>
        <head>
            <meta charset="utf-8" />
            <style>
                body {{ font-family: Arial, sans-serif; padding: 20px; }}
                h2 {{ color: #2c3e50; }}
                .summary {{ background: #e8f4f8; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .section {{ margin: 15px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; background: #f9f9f9; }}
                .company {{ font-weight: bold; color: #2c3e50; font-size: 16px; margin-bottom: 10px; }}
                .job-title a {{ color: #34495e; text-decoration: none; }}
                .job-title a:hover {{ text-decoration: underline; }}
                .job-title {{ margin: 6px 0; }}
                .no-jobs {{ color: #95a5a6; font-style: italic; margin: 5px 0; }}
                .timestamp {{ color: #7f8c8d; font-size: 12px; padding-left: 6px; }}
                .new-badge {{ background: #27ae60; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px; margin-left:6px; }}
            </style>
        </head>
        <body>
            <h2>🚀 New Job Postings Alert</h2>
            <div class="summary">
                <strong>Total new jobs: {len(self.candidate_new_jobs)}</strong><br>
                Check time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}<br>
                <span class="new-badge">NEW</span> = Posting created in the last {self.NEW_WINDOW_HOURS} hours
            </div>
        """
        for company in all_companies:
            company_url = self.job_boards[company]['url']
            jobs = jobs_by_company.get(company, [])
            if jobs:
                html += f'<div class="section"><div class="company">🏢 {company} ({len(jobs)} NEW postings)</div>'
                for j in jobs:
                    loc_text = f" — {j['location']}" if j.get('location') else ''
                    html += f'<div class="job-title">• <a href="{j["url"]}">{j["title"]}</a>{loc_text}<span class="new-badge">NEW</span><span class="timestamp">{j["timestamp"]}</span></div>'
            else:
                html += f'<div class="section"><div class="company">🏢 {company}</div><div class="no-jobs">No new job postings since last check</div>'
            html += f'<div style="margin-top: 10px;"><a href="{company_url}">View all {company} jobs →</a></div></div>'
        html += """
            <hr>
            <p style="color: #7f8c8d; font-size: 12px;">
                Automated Job Board Monitor • Runs hourly via GitHub Actions • Data persisted to GitHub Gists
            </p>
        </body>
        </html>
        """
        return html

    def send_email_notification(self):
        if not self.candidate_new_jobs:
            logger.info("No truly NEW jobs to email.")
            return False
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'🎯 {len(self.candidate_new_jobs)} New Job Postings Found!'
            msg['From'] = self.gmail_user
            msg['To'] = self.gmail_user  # send to self

            html_body = self.build_email_html()

            # Save the rendered email to logs so it appears in Actions artifacts
            try:
                with open('logs/latest_email.html', 'w', encoding='utf-8') as f:
                    f.write(html_body)
            except Exception:
                pass

            msg.attach(MIMEText(html_body, 'html'))

            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(self.gmail_user, self.gmail_password)
                server.send_message(msg)

            logger.info(f"✅ Email sent with {len(self.candidate_new_jobs)} job(s).")
            return True
        except Exception as e:
            logger.error(f"❌ Email send failed: {e}")
            return False

    # ------------------------------
    # Run
    # ------------------------------
    def run(self):
        logger.info("="*50)
        logger.info("Starting Job Board Monitor")
        logger.info(f"Time (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Monitoring {len(self.job_boards)} companies")
        logger.info("="*50)

        # 1) Scrape all boards (with GH→PW fallbacks where configured)
        self.collect_all()

        # 2) Compute NEW-within-window and not previously sent
        self.compute_new_jobs()

        # 3) Email (only if we truly have brand-new jobs)
        emailed = self.send_email_notification()

        # 4) Persist: save history always; update sent_jobs ONLY after successful email
        if emailed:
            for j in self.candidate_new_jobs:
                company = j['company']
                key = j['key']
                self.sent_jobs.setdefault(company, [])
                if key not in self.sent_jobs[company]:
                    self.sent_jobs[company].append(key)
                    # Trim to recent N to keep gist small
                    self.sent_jobs[company] = self.sent_jobs[company][-500:]

        self.save_gist_files()

        logger.info("Job Board Monitor completed.")
        logger.info("="*50)


if __name__ == "__main__":
    JobBoardMonitor().run()
