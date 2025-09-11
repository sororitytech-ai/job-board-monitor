import os
import json
import time
import hashlib
import smtplib
import logging
import re
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Set, Tuple
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Configure logging
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

class JobBoardMonitor:
    def __init__(self):
        self.gmail_user = os.environ.get('GMAIL_USER')
        self.gmail_password = os.environ.get('GMAIL_PASSWORD')
        self.gist_token = os.environ.get('GIST_TOKEN')
        self.job_history = self.load_job_history()
        self.sent_jobs = self.load_sent_jobs()
        self.new_jobs = []
        
        # Updated configurations with better selectors and API endpoints
        self.job_boards = {
            'Google': {
                'url': 'https://www.google.com/about/careers/applications/jobs/results/?location=United%20States&sort_by=date&q=product%2C%20program%2C%20project',
                'method': 'playwright',
                'selectors': [
                    'li.gc-card',
                    'div.gc-card__container',
                    'a.gc-card__title-link'
                ],
                'wait_for': 7000,
                'scroll': True,
                'pagination': True
            },
            'Intrinsic': {
                'url': 'https://boards.greenhouse.io/intrinsic',
                'method': 'api',
                'api_token': 'intrinsic',
                'fallback_selectors': ['div.opening a']
            },
            'Waymo': {
                'url': 'https://careers.withwaymo.com/jobs/search?page=1&query=project%2C+program%2C+product',
                'method': 'playwright',
                'selectors': [
                    'a[data-testid="job-title"]',
                    'h3[data-testid="job-title"]',
                    'div.job-card h3'
                ],
                'wait_for': 6000,
                'pagination': True
            },
            'Wing': {
                'url': 'https://wing.com/careers',
                'method': 'playwright',
                'selectors': [
                    'div.careers-section a[href*="/careers/"]',
                    'div.job-card',
                    'h3.job-title'
                ],
                'wait_for': 6000,
                'scroll': True
            },
            'X Moonshot': {
                'url': 'https://x.company/careers/',
                'method': 'playwright',
                'selectors': [
                    'a.job-listing-link',
                    'div.job-listing h3',
                    'article.job-card h3'
                ],
                'wait_for': 6000,
                'scroll': True
            },
            'Apple': {
                'url': 'https://jobs.apple.com/en-us/search?sort=newest&key=Product%25252C%252520Program%25252C%252520Project&location=united-states-USA',
                'method': 'playwright',
                'selectors': [
                    'td.table-col-1 a',
                    'span[id*="job-title"]',
                    'a[id*="job-link"]'
                ],
                'wait_for': 7000,
                'scroll': True,
                'pagination': True
            },
            'NVIDIA': {
                'url': 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?q=product,%20program,%20project',
                'method': 'playwright',
                'selectors': [
                    'a[data-automation-id="jobTitle"]',
                    'h3[data-automation-id="jobTitle"]'
                ],
                'wait_for': 8000,
                'pagination': True
            },
            'Netflix': {
                'url': 'https://jobs.netflix.com/',
                'method': 'api',
                'api_token': 'netflix',
                'fallback_url': 'https://explore.jobs.netflix.net/careers?pid=790301701184&domain=netflix.com&sort_by=new'
            },
            'Anthropic': {
                'url': 'https://boards.greenhouse.io/anthropic',
                'method': 'api',
                'api_token': 'anthropic',
                'fallback_selectors': ['div.opening a']
            },
            'Tesla': {
                'url': 'https://www.tesla.com/careers/search/?region=5&site=US&type=1',
                'method': 'playwright',
                'selectors': [
                    'tr.tds-table-row td:first-child a',
                    'tbody tr td a[href*="/careers/"]'
                ],
                'wait_for': 8000,
                'scroll': True,
                'handle_cloudflare': True
            },
            'Amazon': {
                'url': 'https://www.amazon.jobs/en/search?offset=0&result_limit=10&sort=recent&job_type%5B%5D=Full-Time&country%5B%5D=USA&state%5B%5D=New%20York&state%5B%5D=New%20Jersey',
                'method': 'playwright',
                'selectors': [
                    'h3.job-title a',
                    'div.job h3.job-title'
                ],
                'wait_for': 5000,
                'pagination': True
            },
            'Meta': {
                'url': 'https://www.metacareers.com/jobs',
                'method': 'playwright',
                'selectors': [
                    'a[href*="/v2/jobs/"] div',
                    'div[role="heading"]',
                    'div._8sef a'
                ],
                'wait_for': 7000,
                'scroll': True,
                'pagination': True
            },
            'SpaceX': {
                'url': 'https://www.spacex.com/careers/list',
                'method': 'api',
                'api_token': 'spacex',
                'fallback_url': 'https://www.spacex.com/careers/jobs/'
            },
            'Stripe': {
                'url': 'https://stripe.com/jobs/search?office_locations=North+America--New+York',
                'method': 'playwright',
                'selectors': [
                    'a.JobsListings__link span',
                    'h3.JobsListings__title'
                ],
                'wait_for': 5000
            },
            'Uber': {
                'url': 'https://www.uber.com/us/en/careers/list/?location=USA-New%20York-New%20York&location=USA-New%20York-Bronx',
                'method': 'playwright',
                'selectors': [
                    'a[href*="/careers/list/"] h3',
                    'h3[data-baseweb]'
                ],
                'wait_for': 7000,
                'scroll': True,
                'pagination': True
            },
            'Two Sigma': {
                'url': 'https://careers.twosigma.com/careers/OpenRoles',
                'method': 'playwright',
                'selectors': [
                    'span.job-title',
                    'a[href*="JobDetail"] span'
                ],
                'wait_for': 6000,
                'scroll': True
            },
            'Microsoft': {
                'url': 'https://jobs.careers.microsoft.com/global/en/search?q=%22product%22%20OR%20%22project%22%20OR%20%22program%22&lc=United%20States&et=Full-Time&l=en_us&pg=1&pgSz=20&o=Recent',
                'method': 'playwright',
                'selectors': [
                    'h2[data-automation-id="jobTitle"]',
                    'span[data-automation-id="jobTitle"]'
                ],
                'wait_for': 6000,
                'pagination': True
            },
            'OpenAI': {
                'url': 'https://openai.com/careers/search/',
                'method': 'api',
                'api_token': 'openai',
                'fallback_selectors': ['a[href*="/careers/"] h3']
            }
        }
    
    def load_job_history(self) -> Dict:
        """Load job history from GitHub Gist"""
        try:
            if not self.gist_token:
                logger.warning("No GIST_TOKEN found, using local storage")
                return {}
                
            headers = {'Authorization': f'token {self.gist_token}'}
            response = requests.get('https://api.github.com/gists', headers=headers)
            
            if response.status_code == 200:
                gists = response.json()
                for gist in gists:
                    if 'job_history.json' in gist.get('files', {}):
                        file_url = gist['files']['job_history.json']['raw_url']
                        history_response = requests.get(file_url)
                        data = history_response.json()
                        return self.clean_old_jobs(data)
            
            return self.create_history_gist()
        except Exception as e:
            logger.error(f"Error loading job history: {e}")
            return {}
    
    def load_sent_jobs(self) -> Dict:
        """Load history of jobs we've already sent emails about"""
        try:
            if not self.gist_token:
                return {}
                
            headers = {'Authorization': f'token {self.gist_token}'}
            response = requests.get('https://api.github.com/gists', headers=headers)
            
            if response.status_code == 200:
                gists = response.json()
                for gist in gists:
                    if 'sent_jobs.json' in gist.get('files', {}):
                        file_url = gist['files']['sent_jobs.json']['raw_url']
                        history_response = requests.get(file_url)
                        return history_response.json()
            return {}
        except Exception as e:
            logger.error(f"Error loading sent jobs: {e}")
            return {}
    
    def clean_old_jobs(self, job_data: Dict) -> Dict:
        """Remove jobs older than 7 days"""
        week_ago = datetime.now() - timedelta(days=7)
        cleaned_data = {}
        
        for company, jobs in job_data.items():
            if isinstance(jobs, dict):
                cleaned_jobs = {}
                for job_id, job_info in jobs.items():
                    if 'first_seen' in job_info:
                        try:
                            first_seen = datetime.fromisoformat(job_info['first_seen'])
                            if first_seen > week_ago:
                                cleaned_jobs[job_id] = job_info
                        except:
                            cleaned_jobs[job_id] = job_info
                    else:
                        cleaned_jobs[job_id] = job_info
                cleaned_data[company] = cleaned_jobs
            else:
                # Legacy format
                cleaned_data[company] = jobs[-100:] if isinstance(jobs, list) else jobs
        
        return cleaned_data
    
    def create_history_gist(self) -> Dict:
        """Create new GitHub Gist for job history"""
        try:
            if not self.gist_token:
                return {}
                
            headers = {'Authorization': f'token {self.gist_token}'}
            data = {
                'description': 'Job Board Monitor History',
                'public': False,
                'files': {
                    'job_history.json': {'content': json.dumps({})},
                    'sent_jobs.json': {'content': json.dumps({})}
                }
            }
            requests.post('https://api.github.com/gists', headers=headers, json=data)
            return {}
        except Exception as e:
            logger.error(f"Error creating history gist: {e}")
            return {}
    
    def extract_job_id(self, job_text: str, company: str) -> str:
        """Extract a stable job ID from job text"""
        # Try to extract actual job ID
        job_id_patterns = [
            r'Job ID:\s*(\d+)',
            r'job[_-]?id[:\s]+(\w+)',
            r'#(\d{5,})',
            r'req[_-]?(\d+)',
            r'ID:\s*(\w+)'
        ]
        
        for pattern in job_id_patterns:
            match = re.search(pattern, job_text, re.IGNORECASE)
            if match:
                return f"{company}_{match.group(1)}"
        
        # Clean and use title as ID
        clean_text = job_text.strip()
        clean_text = re.sub(r'(Today|Yesterday|\d+ days? ago).*', '', clean_text)
        clean_text = re.sub(r'(Posted|Updated|Location).*', '', clean_text)
        clean_text = clean_text.split('•')[0].split('|')[0].split('\n')[0]
        clean_text = clean_text.strip()[:80]
        
        return hashlib.md5(f"{company}_{clean_text}".encode()).hexdigest()
    
    def is_junk_text(self, text: str) -> bool:
        """Check if text is junk/navigation element"""
        if not text or len(text) < 5:
            return True
        
        text_lower = text.lower().strip()
        
        # Comprehensive junk patterns
        junk_patterns = [
            'cookie', 'consent', 'privacy', 'manage preferences',
            'do not sell', 'help center', 'about us', 'newsroom',
            'careers blog', 'submit resume', 'view role', 'read more',
            'all departments', 'all locations', 'no positions available',
            'load more', 'show more', 'view all', 'sign in', 'log in',
            'create account', 'subscribe', 'follow us', 'contact us'
        ]
        
        for pattern in junk_patterns:
            if pattern in text_lower:
                return True
        
        # Single word filters
        if ' ' not in text and len(text) < 20:
            if text_lower in ['engineering', 'sales', 'marketing', 'design', 
                             'global', 'meta', 'facebook', 'instagram', 'careers']:
                return True
        
        # Must contain job-related keywords
        if len(text) < 30:
            job_keywords = ['product', 'program', 'project', 'manager', 
                          'engineer', 'developer', 'analyst', 'designer', 
                          'scientist', 'director', 'lead', 'senior']
            if not any(kw in text_lower for kw in job_keywords):
                return True
        
        return False
    
    def is_truly_new_job(self, job_id: str, company: str) -> bool:
        """Check if this job is truly new (not sent before)"""
        # Fixed: Only takes 2 parameters now
        if company in self.sent_jobs and job_id in self.sent_jobs.get(company, []):
            return False
        return True
    
    def scrape_greenhouse_api(self, company: str, token: str) -> List[Tuple[str, str]]:
        """Use Greenhouse API to get jobs"""
        jobs = []
        try:
            # Get all departments first
            dept_url = f'https://boards-api.greenhouse.io/v1/boards/{token}/departments'
            response = requests.get(dept_url, timeout=10)
            
            department_ids = []
            if response.status_code == 200:
                departments = response.json().get('departments', [])
                logger.info(f"Found {len(departments)} departments for {company}")
                department_ids = [d['id'] for d in departments]
            
            # Get jobs from main endpoint
            jobs_url = f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs'
            response = requests.get(jobs_url, timeout=10)
            
            if response.status_code == 200:
                job_list = response.json().get('jobs', [])
                logger.info(f"Found {len(job_list)} total jobs for {company}")
                
                for job in job_list:
                    title = job.get('title', '')
                    job_id = str(job.get('id', ''))
                    location = job.get('location', {}).get('name', '')
                    
                    # Filter for relevant jobs
                    if self.is_relevant_job(title, location):
                        unique_id = f"{company}_api_{job_id}"
                        jobs.append((unique_id, title))
                        
                        # Track new jobs
                        if company not in self.job_history:
                            self.job_history[company] = {}
                        
                        if unique_id not in self.job_history[company]:
                            self.job_history[company][unique_id] = {
                                'title': title,
                                'first_seen': datetime.now().isoformat()
                            }
                            
                            if self.is_truly_new_job(unique_id, company):
                                self.new_jobs.append({
                                    'company': company,
                                    'job_title': title,
                                    'location': location,
                                    'url': f'https://boards.greenhouse.io/{token}',
                                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                                })
                                logger.info(f"NEW JOB: {company} - {title}")
            
            logger.info(f"Total unique jobs found for {company} via API: {len(jobs)}")
            
        except Exception as e:
            logger.error(f"Error with {company} API: {e}")
            return []
        
        return jobs
    
    def is_relevant_job(self, title: str, location: str = '') -> bool:
        """Check if job is relevant based on title and location"""
        # Check for relevant keywords
        keywords = ['product', 'program', 'project', 'manager', 'technical', 
                   'engineering', 'lead', 'director', 'principal']
        
        title_lower = title.lower()
        if not any(kw in title_lower for kw in keywords):
            return False
        
        # Check location if provided
        if location:
            us_locations = ['United States', 'USA', 'US', 'New York', 'NY',
                          'San Francisco', 'SF', 'Remote', 'Seattle', 'Mountain View',
                          'Austin', 'Boston', 'Chicago', 'Los Angeles']
            if not any(loc in location for loc in us_locations):
                return False
        
        return True
    
    def scrape_job_board(self, company: str, config: Dict) -> List[Tuple[str, str]]:
        """Enhanced scraping with better error handling and pagination"""
        jobs = []
        
        # Try API first if configured
        if config.get('method') == 'api' and config.get('api_token'):
            api_jobs = self.scrape_greenhouse_api(company, config['api_token'])
            if api_jobs:
                return api_jobs
            logger.info(f"API failed for {company}, falling back to web scraping")
        
        try:
            logger.info(f"Checking {company}...")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage'
                    ]
                )
                
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                
                page = context.new_page()
                
                # Handle Cloudflare if needed
                if config.get('handle_cloudflare'):
                    page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        });
                    """)
                
                # Navigate to page
                logger.info(f"Loading {company} careers page...")
                page.goto(config['url'], wait_until='domcontentloaded', timeout=30000)
                
                # Wait for content
                page.wait_for_timeout(config.get('wait_for', 5000))
                
                # Handle cookies/popups
                self.handle_popups(page)
                
                # Check multiple pages
                pages_checked = 0
                max_pages = 5 if config.get('pagination') else 1
                
                while pages_checked < max_pages:
                    pages_checked += 1
                    logger.info(f"Checking page {pages_checked} for {company}")
                    
                    # Load more content if needed
                    if config.get('scroll'):
                        self.handle_infinite_scroll(page)
                    
                    # Try all selectors
                    found_elements = False
                    for selector in config.get('selectors', []):
                        try:
                            elements = page.locator(selector).all()
                            if elements:
                                logger.info(f"Found {len(elements)} job elements for {company} on page {pages_checked}")
                                found_elements = True
                                
                                for element in elements:
                                    try:
                                        job_text = element.text_content()
                                        if job_text and not self.is_junk_text(job_text):
                                            job_id = self.extract_job_id(job_text, company)
                                            
                                            # Avoid duplicates
                                            if job_id in [j[0] for j in jobs]:
                                                continue
                                            
                                            job_title = job_text.strip()[:100]
                                            jobs.append((job_id, job_title))
                                            
                                            # Track job
                                            if company not in self.job_history:
                                                self.job_history[company] = {}
                                            
                                            if job_id not in self.job_history[company]:
                                                self.job_history[company][job_id] = {
                                                    'title': job_title,
                                                    'first_seen': datetime.now().isoformat()
                                                }
                                                
                                                if self.is_truly_new_job(job_id, company):
                                                    self.new_jobs.append({
                                                        'company': company,
                                                        'job_title': job_title,
                                                        'url': config['url'],
                                                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                                                    })
                                                    logger.info(f"NEW JOB: {company} - {job_title}")
                                    except Exception as e:
                                        logger.debug(f"Error processing element: {e}")
                                        continue
                                break
                        except Exception as e:
                            logger.debug(f"Selector {selector} failed: {e}")
                            continue
                    
                    # Try pagination if configured
                    if config.get('pagination') and pages_checked < max_pages:
                        if not self.navigate_next_page(page, pages_checked):
                            logger.info(f"No more pages for {company}")
                            break
                    elif not found_elements:
                        logger.warning(f"No job elements found for {company} on page {pages_checked}")
                        break
                
                if jobs:
                    logger.info(f"Total jobs found for {company}: {len(jobs)}")
                else:
                    logger.warning(f"No jobs found for {company}")
                
                browser.close()
                
        except Exception as e:
            logger.error(f"Error scraping {company}: {e}")
        
        return jobs
    
    def handle_popups(self, page):
        """Handle cookie banners and popups"""
        try:
            popup_selectors = [
                'button:has-text("Accept")',
                'button:has-text("OK")',
                'button:has-text("Got it")',
                'button[aria-label*="close"]',
                'button[aria-label*="dismiss"]',
                'button:has-text("Continue")'
            ]
            for selector in popup_selectors:
                if page.locator(selector).count() > 0:
                    page.locator(selector).first.click()
                    page.wait_for_timeout(1000)
                    break
        except:
            pass
    
    def handle_infinite_scroll(self, page):
        """Handle infinite scroll and load more buttons"""
        try:
            # Try load more buttons first
            load_selectors = [
                'button:has-text("View More")',
                'button:has-text("Load More")',
                'button:has-text("Show More")',
                'a:has-text("View More")'
            ]
            
            for _ in range(3):
                clicked = False
                for selector in load_selectors:
                    if page.locator(selector).count() > 0:
                        try:
                            page.locator(selector).first.click()
                            page.wait_for_timeout(2000)
                            clicked = True
                            break
                        except:
                            pass
                
                if not clicked:
                    # Scroll instead
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    page.wait_for_timeout(1500)
        except:
            pass
    
    def navigate_next_page(self, page, current_page: int) -> bool:
        """Navigate to next page"""
        try:
            next_selectors = [
                f'a:has-text("{current_page + 1}")',
                f'button:has-text("{current_page + 1}")',
                'a:has-text("Next")',
                'button:has-text("Next")',
                'a[aria-label*="Next"]',
                'button[aria-label*="Next"]'
            ]
            
            for selector in next_selectors:
                if page.locator(selector).count() > 0:
                    page.locator(selector).first.click()
                    page.wait_for_timeout(3000)
                    logger.info(f"Navigated to page {current_page + 1}")
                    return True
        except Exception as e:
            logger.debug(f"Pagination error: {e}")
        
        return False
    
    def check_all_boards(self):
        """Check all job boards for new postings"""
        for company, config in self.job_boards.items():
            try:
                jobs = self.scrape_job_board(company, config)
                
                # Update sent jobs tracking
                if company not in self.sent_jobs:
                    self.sent_jobs[company] = []
                
                for job_id, _ in jobs:
                    if job_id not in self.sent_jobs[company]:
                        self.sent_jobs[company].append(job_id)
                
                # Keep only recent sent jobs
                self.sent_jobs[company] = self.sent_jobs[company][-200:]
                
                # Rate limiting
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error checking {company}: {e}")
                continue
    
    def save_job_history(self):
        """Save both job history and sent jobs"""
        try:
            if not self.gist_token:
                logger.warning("No GIST_TOKEN found, skipping save")
                return
                
            headers = {'Authorization': f'token {self.gist_token}'}
            
            # Find existing gist
            response = requests.get('https://api.github.com/gists', headers=headers)
            if response.status_code != 200:
                return
                
            gists = response.json()
            gist_id = None
            
            for gist in gists:
                if 'job_history.json' in gist.get('files', {}):
                    gist_id = gist['id']
                    break
            
            if gist_id:
                # Update both files
                data = {
                    'files': {
                        'job_history.json': {
                            'content': json.dumps(self.job_history, indent=2)
                        },
                        'sent_jobs.json': {
                            'content': json.dumps(self.sent_jobs, indent=2)
                        }
                    }
                }
                requests.patch(f'https://api.github.com/gists/{gist_id}', headers=headers, json=data)
                logger.info("Job history and sent jobs saved successfully")
        except Exception as e:
            logger.error(f"Error saving history: {e}")
    
    def send_email_notification(self):
        """Send email notification for truly new jobs only"""
        if not self.new_jobs:
            logger.info("No new jobs found in this run")
            return
        
        try:
            # Remove duplicates
            seen = set()
            unique_jobs = []
            for job in self.new_jobs:
                key = f"{job['company']}_{job['job_title']}"
                if key not in seen:
                    seen.add(key)
                    unique_jobs.append(job)
            
            if not unique_jobs:
                logger.info("No unique new jobs to report")
                return
            
            logger.info(f"Preparing to send email with {len(unique_jobs)} new jobs...")
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'🎯 {len(unique_jobs)} New Job Postings Found!'
            msg['From'] = self.gmail_user
            msg['To'] = 'sororitytech@gmail.com'
            
            # Create HTML email body
            html_body = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; padding: 20px; }}
                    h2 {{ color: #2c3e50; }}
                    .summary {{ background: #e8f4f8; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                    .job {{ margin: 15px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; background: #f9f9f9; }}
                    .company {{ font-weight: bold; color: #2c3e50; font-size: 16px; margin-bottom: 10px; }}
                    .job-title {{ color: #34495e; margin: 5px 0; padding-left: 20px; }}
                    .no-jobs {{ color: #95a5a6; font-style: italic; margin: 5px 0; padding-left: 20px; }}
                    .timestamp {{ color: #7f8c8d; font-size: 12px; }}
                    a {{ color: #3498db; text-decoration: none; }}
                    a:hover {{ text-decoration: underline; }}
                    .new-badge {{ background: #27ae60; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px; }}
                </style>
            </head>
            <body>
                <h2>🚀 New Job Postings Alert</h2>
                <div class="summary">
                    <strong>Total new jobs: {len(unique_jobs)}</strong><br>
                    Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
                    <span class="new-badge">NEW</span> = Job posting created since last check<br>
                    <em>Note: Only showing jobs that were JUST posted</em>
                </div>
            """
            
            # Group jobs by company
            jobs_by_company = {}
            for job in unique_jobs:
                if job['company'] not in jobs_by_company:
                    jobs_by_company[job['company']] = []
                jobs_by_company[job['company']].append(job)
            
            # Show ALL companies
            all_companies = sorted(self.job_boards.keys())
            
            for company in all_companies:
                jobs = jobs_by_company.get(company, [])
                company_url = self.job_boards[company]['url']
                
                if jobs:
                    html_body += f"""
                    <div class="job">
                        <div class="company">🏢 {company} ({len(jobs)} NEW positions)</div>
                    """
                    # Show ALL jobs, not limited
                    for job in jobs:
                        location = job.get('location', '')
                        location_text = f" - {location}" if location else ""
                        html_body += f"""
                        <div class="job-title">• {job['job_title']}{location_text} <span class="new-badge">NEW</span></div>
                        """
                else:
                    html_body += f"""
                    <div class="job">
                        <div class="company">🏢 {company}</div>
                        <div class="no-jobs">No new job postings since last check</div>
                    """
                
                html_body += f"""
                    <div style="margin-top: 10px;"><a href="{company_url}">View All {company} Jobs →</a></div>
                </div>
                """
            
            html_body += """
                <hr>
                <p style="color: #7f8c8d; font-size: 12px;">
                    Automated Job Board Monitor<br>
                    Checking: Every hour | Companies: 18<br>
                    Apply within 24 hours for best results!
                </p>
            </body>
            </html>
            """
            
            part = MIMEText(html_body, 'html')
            msg.attach(part)
            
            # Send email
            logger.info("Connecting to Gmail SMTP server...")
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(self.gmail_user, self.gmail_password)
                server.send_message(msg)
            
            logger.info(f"✅ Email sent successfully with {len(unique_jobs)} new jobs!")
            
        except Exception as e:
            logger.error(f"❌ Error sending email: {e}")
    
    def run(self):
        """Main execution method"""
        logger.info("="*50)
        logger.info("Starting Job Board Monitor")
        logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Monitoring {len(self.job_boards)} companies")
        logger.info("="*50)
        
        # Check all boards
        self.check_all_boards()
        
        # Send email if new jobs found
        if self.new_jobs:
            logger.info(f"Total new jobs found: {len(self.new_jobs)}")
            self.send_email_notification()
        else:
            logger.info("No new jobs found in this run")
        
        # Save updated history
        self.save_job_history()
        
        logger.info("Job Board Monitor completed successfully!")
        logger.info("="*50)

if __name__ == "__main__":
    monitor = JobBoardMonitor()
    monitor.run()
