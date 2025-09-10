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
        self.sent_jobs = self.load_sent_jobs()  # Track what we've already emailed
        self.new_jobs = []
        
        # Updated job board configurations with better selectors and methods
        self.job_boards = {
            'Google': {
                'url': 'https://www.google.com/about/careers/applications/jobs/results/?location=United%20States&sort_by=date&q=product%2C%20program%2C%20project',
                'method': 'playwright',
                'selectors': [
                    'li[class*="job"]',
                    'div[class*="job-item"]',
                    'h2.gc-card__title',
                    'a.gc-card__title-link',
                    'div[role="listitem"]'
                ],
                'wait_for': 5000,
                'scroll': True
            },
            'Intrinsic': {
                'url': 'https://boards.greenhouse.io/intrinsic',
                'method': 'playwright',
                'selectors': ['div.opening a'],
                'wait_for': 3000
            },
            'Waymo': {
                'url': 'https://careers.withwaymo.com/jobs/search?page=1&query=project%2C+program%2C+product',
                'method': 'playwright',
                'selectors': [
                    'div[data-testid="job-card"] h3',
                    'a[href*="/jobs/"] h3',
                    'h3'
                ],
                'wait_for': 5000
            },
            'Wing': {
                'url': 'https://wing.com/careers',
                'method': 'playwright',
                'selectors': [
                    'div.job-listing h3',
                    'div.careers-listing h3',
                    'a[href*="job"] h3'
                ],
                'wait_for': 5000
            },
            'X Moonshot': {
                'url': 'https://x.company/careers/',
                'method': 'playwright',
                'selectors': [
                    'div.job-listing h3',
                    'a[href*="careers"] h3',
                    'h3.job-title'
                ],
                'wait_for': 5000
            },
            'Apple': {
                'url': 'https://jobs.apple.com/en-us/search?sort=newest&key=Product%25252C%252520Program%25252C%252520Project&location=united-states-USA',
                'method': 'playwright',
                'selectors': [
                    'tbody.table-tbody tr[role="row"] td.table-col-1',
                    'td.table-col-1 a',
                    'span.table-col-1-link'
                ],
                'wait_for': 5000,
                'scroll': True
            },
            'NVIDIA': {
                'url': 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?q=product,%20program,%20project',
                'method': 'playwright',
                'selectors': [
                    'a[data-automation-id="jobTitle"]',
                    'div[data-automation-id="promptOption"]'
                ],
                'wait_for': 7000
            },
            'Netflix': {
                'url': 'https://explore.jobs.netflix.net/careers?pid=790301701184&Region=ucan&domain=netflix.com&sort_by=new',
                'method': 'playwright',
                'selectors': [
                    'a[data-card-type="job"]',
                    'div[data-card-type="job"]',
                    'article[class*="job"]'
                ],
                'wait_for': 5000,
                'scroll': True
            },
            'Anthropic': {
                'url': 'https://boards.greenhouse.io/anthropic',
                'method': 'playwright',
                'selectors': ['div.opening a'],
                'wait_for': 3000
            },
            'Tesla': {
                'url': 'https://www.tesla.com/careers/search/?region=5&site=US&type=1',
                'method': 'playwright',
                'selectors': [
                    'tr.tds-table-row td:first-child',
                    'tbody tr td a'
                ],
                'wait_for': 5000,
                'scroll': True
            },
            'Amazon': {
                'url': 'https://www.amazon.jobs/en/search?offset=0&result_limit=10&sort=recent&job_type%5B%5D=Full-Time&country%5B%5D=USA&state%5B%5D=New%20York&state%5B%5D=New%20Jersey',
                'method': 'playwright',
                'selectors': [
                    'div.job-tile h3.job-title',
                    'h3.job-title'
                ],
                'wait_for': 3000
            },
            'Meta': {
                'url': 'https://www.metacareers.com/jobs',
                'method': 'playwright',
                'selectors': [
                    'a[href*="/jobs/"] div[role="heading"]',
                    'div._8sef',
                    'div._8sel'
                ],
                'wait_for': 5000,
                'scroll': True
            },
            'SpaceX': {
                'url': 'https://www.spacex.com/careers/jobs/',
                'method': 'playwright',
                'selectors': [
                    'div[id*="job"] h3',
                    'tr[class*="job"] td',
                    'a[href*="/careers/"] span'
                ],
                'wait_for': 5000,
                'scroll': True
            },
            'Stripe': {
                'url': 'https://stripe.com/jobs/search?office_locations=North+America--New+York',
                'method': 'playwright',
                'selectors': [
                    'a.JobsListings__link h3',
                    'h3.JobsListings__title'
                ],
                'wait_for': 3000
            },
            'Uber': {
                'url': 'https://www.uber.com/us/en/careers/list/?location=USA-New%20York-New%20York&location=USA-New%20York-Bronx',
                'method': 'playwright',
                'selectors': [
                    'a[data-baseweb="link"] h3',
                    'div[data-baseweb] h3',
                    'h3'
                ],
                'wait_for': 5000,
                'scroll': True
            },
            'Two Sigma': {
                'url': 'https://careers.twosigma.com/careers/OpenRoles/%22product%22%20OR%20%22project%22%20OR%20%22program%22',
                'method': 'playwright',
                'selectors': [
                    'div.job-result span.job-title',
                    'a[href*="JobDetail"] span'
                ],
                'wait_for': 5000
            },
            'Microsoft': {
                'url': 'https://jobs.careers.microsoft.com/global/en/search?q=%22product%22%20OR%20%22project%22%20OR%20%22program%22&lc=United%20States&et=Full-Time&l=en_us&pg=1&pgSz=20&o=Recent&flt=true',
                'method': 'playwright',
                'selectors': [
                    'span[data-automation-id="jobTitle"]',
                    'h2[data-automation-id="jobTitle"]',
                    'div.ms-List-cell'
                ],
                'wait_for': 5000
            },
            'OpenAI': {
                'url': 'https://openai.com/careers/search/',
                'method': 'playwright',
                'selectors': [
                    'li a[href*="/careers/"]',
                    'div[class*="job"] h3',
                    'article h3'
                ],
                'wait_for': 5000,
                'scroll': True
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
                        # Clean old entries (older than 7 days)
                        return self.clean_old_jobs(data)
            
            # Create new gist if not found
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
            
            # Create new file if not found
            return {}
        except Exception as e:
            logger.error(f"Error loading sent jobs: {e}")
            return {}
    
    def clean_old_jobs(self, job_data: Dict) -> Dict:
        """Remove jobs older than 7 days"""
        week_ago = datetime.now() - timedelta(days=7)
        cleaned_data = {}
        
        for company, jobs in job_data.items():
            if isinstance(jobs, list):
                # Legacy format - just keep last 100
                cleaned_data[company] = jobs[-100:]
            elif isinstance(jobs, dict):
                # New format with timestamps
                cleaned_jobs = {}
                for job_id, job_info in jobs.items():
                    if 'first_seen' in job_info:
                        try:
                            first_seen = datetime.fromisoformat(job_info['first_seen'])
                            if first_seen > week_ago:
                                cleaned_jobs[job_id] = job_info
                        except:
                            # Keep if can't parse date
                            cleaned_jobs[job_id] = job_info
                cleaned_data[company] = cleaned_jobs
        
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
        # Try to extract job ID from text
        job_id_patterns = [
            r'Job ID:\s*(\d+)',
            r'job[_-]?id[:\s]+(\w+)',
            r'#(\d{5,})',
            r'ID:\s*(\w+)'
        ]
        
        for pattern in job_id_patterns:
            match = re.search(pattern, job_text, re.IGNORECASE)
            if match:
                return f"{company}_{match.group(1)}"
        
        # Extract just the job title (first line or up to first delimiter)
        clean_text = job_text.strip()
        # Remove dates, locations, and other metadata
        clean_text = re.sub(r'(Today|Yesterday|\d+ days? ago).*', '', clean_text)
        clean_text = re.sub(r'(Locations?|Posted|Updated).*', '', clean_text)
        clean_text = clean_text.split('•')[0].split('|')[0].split('\n')[0]
        clean_text = clean_text.strip()[:100]  # First 100 chars of title
        
        # Create hash from cleaned title
        return hashlib.md5(f"{company}_{clean_text}".encode()).hexdigest()
    
    def is_junk_text(self, text: str) -> bool:
        """Check if text is junk/navigation element"""
        if not text or len(text) < 5:
            return True
        
        text_lower = text.lower().strip()
        
        # Comprehensive junk patterns
        junk_patterns = [
            'cookie', 'consent', 'privacy', 'manage preferences', 'cookie list',
            'do not sell', 'help center', 'about us', 'newsroom', 'investors',
            'careers blog', 'start job search', 'deliver', 'uber for business',
            'uber freight', 'safety', 'sustainability', 'accessibility',
            'view role', 'read more', 'submit resume', 'connect with',
            'visit help center', 'google data policy', 'multiple locations',
            'engineering', 'facebook', 'instagram', 'ai infrastructure',
            'advertising technology', 'ai research', 'ar/vr', 'artificial intelligence',
            'data & analytics', 'facebook reality labs', 'generative ai',
            'infrastructure', 'global', 'meta$', 'uber$', 'careers$',
            'all departments', 'all locations', 'no positions available',
            'inside uber', 'view all', 'load more', 'show more'
        ]
        
        for pattern in junk_patterns:
            if pattern in text_lower:
                return True
        
        # Check if it's just a single generic word
        if ' ' not in text and text_lower in ['engineering', 'sales', 'marketing', 'design', 'global', 'meta', 'facebook', 'instagram']:
            return True
        
        # Check if it lacks job keywords when short
        if len(text) < 20:
            job_keywords = ['product', 'program', 'project', 'manager', 'engineer', 'developer', 'analyst', 'designer', 'scientist']
            if not any(kw in text_lower for kw in job_keywords):
                return True
        
        return False
    
    def is_truly_new_job(self, job_id: str, company: str) -> bool:
        """Check if this job is truly new (not sent before)"""
        # Check if we've already sent an email about this job
        if company in self.sent_jobs and job_id in self.sent_jobs.get(company, []):
            return False
        return True
    
    def scrape_job_board(self, company: str, config: Dict) -> List[Tuple[str, str]]:
        """Scrape job board using Playwright with pagination support"""
        jobs = []
        try:
            logger.info(f"Checking {company}...")
            
            with sync_playwright() as p:
                # Launch browser
                browser = p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
                )
                
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                
                page = context.new_page()
                
                # Navigate to the page
                logger.info(f"Loading {company} careers page...")
                try:
                    page.goto(config['url'], wait_until='domcontentloaded', timeout=30000)
                except:
                    # Try networkidle if domcontentloaded fails
                    page.goto(config['url'], wait_until='networkidle', timeout=30000)
                
                # Wait for content to load
                wait_time = config.get('wait_for', 5000)
                page.wait_for_timeout(wait_time)
                
                # Try to handle cookie banners or popups
                try:
                    popup_selectors = [
                        'button:has-text("Accept")',
                        'button:has-text("OK")',
                        'button:has-text("Got it")',
                        'button[aria-label*="close"]',
                        'button[aria-label*="dismiss"]'
                    ]
                    for selector in popup_selectors:
                        if page.locator(selector).count() > 0:
                            page.locator(selector).first.click()
                            page.wait_for_timeout(1000)
                            break
                except:
                    pass
                
                # Handle pagination - check up to 5 pages or until no more jobs found
                pages_checked = 0
                max_pages = 5
                
                while pages_checked < max_pages:
                    pages_checked += 1
                    logger.info(f"Checking page {pages_checked} for {company}")
                    
                    # Try to click "View More" or "Load More" buttons if configured
                    if config.get('scroll'):
                        try:
                            for _ in range(3):  # Try clicking multiple times
                                load_more_selectors = [
                                    'button:has-text("View More")',
                                    'button:has-text("Load More")',
                                    'button:has-text("Show More")',
                                    'button:has-text("Load more")',
                                    'a:has-text("View More")',
                                    'button[aria-label*="load more"]'
                                ]
                                clicked = False
                                for selector in load_more_selectors:
                                    if page.locator(selector).count() > 0 and page.locator(selector).first.is_visible():
                                        page.locator(selector).first.click()
                                        page.wait_for_timeout(2000)
                                        clicked = True
                                        break
                                if not clicked:
                                    break
                        except:
                            pass
                        
                        # Scroll to load more content
                        for _ in range(3):
                            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                            page.wait_for_timeout(1500)
                    
                    # Try multiple selectors
                    selectors = config.get('selectors', [])
                    page_jobs_found = False
                    
                    for selector in selectors:
                        try:
                            elements = page.locator(selector).all()
                            if elements:
                                logger.info(f"Found {len(elements)} job elements for {company} on page {pages_checked}")
                                page_jobs_found = True
                                
                                for idx, element in enumerate(elements):
                                    try:
                                        job_text = element.text_content()
                                        if job_text and len(job_text) > 5 and not self.is_junk_text(job_text):
                                            job_id = self.extract_job_id(job_text, company)
                                            
                                            # Check if we've already seen this job
                                            if job_id in [j[0] for j in jobs]:
                                                continue  # Skip duplicate
                                            
                                            job_title = job_text.strip()[:100]
                                            jobs.append((job_id, job_title))
                                            
                                            # Check if this is a new job
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
                                        logger.debug(f"Error processing element {idx}: {e}")
                                        continue
                                break  # Exit selector loop if we found elements
                        except Exception as e:
                            logger.debug(f"Selector {selector} failed: {e}")
                            continue
                    
                    # Try to find and click "Next" button for pagination
                    next_clicked = False
                    if pages_checked < max_pages:
                        try:
                            next_selectors = [
                                'a:has-text("Next")',
                                'button:has-text("Next")',
                                'a[aria-label*="Next"]',
                                'button[aria-label*="Next"]',
                                'a:has-text("→")',
                                'button:has-text("→")',
                                f'a:has-text("{pages_checked + 1}")',  # Page number
                                f'button:has-text("{pages_checked + 1}")'
                            ]
                            
                            for selector in next_selectors:
                                if page.locator(selector).count() > 0 and page.locator(selector).first.is_visible():
                                    page.locator(selector).first.click()
                                    page.wait_for_timeout(3000)
                                    next_clicked = True
                                    logger.info(f"Navigated to page {pages_checked + 1} for {company}")
                                    break
                        except:
                            pass
                    
                    # If no next button clicked and no jobs found on this page, stop pagination
                    if not next_clicked and not page_jobs_found:
                        logger.info(f"No more pages to check for {company}")
                        break
                
                if not jobs:
                    logger.warning(f"No job elements found for {company} after checking {pages_checked} pages")
                else:
                    logger.info(f"Total jobs found for {company}: {len(jobs)} across {pages_checked} pages")
                
                browser.close()
                
        except Exception as e:
            logger.error(f"Error scraping {company}: {e}")
        
        return jobs
    
    def scrape_greenhouse_api(self, company: str, board_token: str) -> List[Tuple[str, str]]:
        """Scrape Greenhouse boards using their public API - gets ALL jobs from ALL departments"""
        jobs = []
        try:
            # First get all departments
            departments_url = f'https://boards-api.greenhouse.io/v1/boards/{board_token}/departments'
            response = requests.get(departments_url, timeout=10)
            
            department_ids = []
            if response.status_code == 200:
                data = response.json()
                departments = data.get('departments', [])
                logger.info(f"Found {len(departments)} departments for {company}")
                for dept in departments:
                    department_ids.append(dept.get('id'))
            
            # Get jobs from main API
            api_url = f'https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs'
            response = requests.get(api_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                job_list = data.get('jobs', [])
                logger.info(f"Found {len(job_list)} total jobs for {company}")
                
                for job in job_list:
                    title = job.get('title', '')
                    job_id = str(job.get('id', ''))
                    location = job.get('location', {}).get('name', '')
                    
                    # Filter for US/relevant locations and keywords
                    if any(loc in str(location) for loc in ['United States', 'USA', 'US', 'New York', 'San Francisco', 'Remote', 'Seattle', 'Mountain View']):
                        if any(keyword in title.lower() for keyword in ['product', 'program', 'project', 'manager', 'technical']):
                            unique_id = f"{company}_gh_{job_id}"
                            jobs.append((unique_id, title))
                            
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
                                    'url': f'https://boards.greenhouse.io/{board_token}',
                                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                                })
                                logger.info(f"NEW JOB: {company} - {title}")
            
            # Also check each department specifically
            for dept_id in department_ids[:10]:  # Check up to 10 departments
                try:
                    dept_url = f'https://boards-api.greenhouse.io/v1/boards/{board_token}/departments/{dept_id}/jobs'
                    response = requests.get(dept_url, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        dept_jobs = data.get('jobs', [])
                        for job in dept_jobs:
                            title = job.get('title', '')
                            job_id = str(job.get('id', ''))
                            location = job.get('location', {}).get('name', '')
                            
                            unique_id = f"{company}_gh_{job_id}"
                            # Check if we've already seen this job
                            if unique_id in [j[0] for j in jobs]:
                                continue
                            
                            if any(loc in str(location) for loc in ['United States', 'USA', 'US', 'New York', 'San Francisco', 'Remote', 'Seattle']):
                                if any(keyword in title.lower() for keyword in ['product', 'program', 'project', 'manager', 'technical']):
                                    jobs.append((unique_id, title))
                                    
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
                                            'url': f'https://boards.greenhouse.io/{board_token}',
                                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                                        })
                                        logger.info(f"NEW JOB (from dept): {company} - {title}")
                except:
                    continue
            
            logger.info(f"Total unique jobs found for {company} via API: {len(jobs)}")
                                
        except Exception as e:
            logger.error(f"Error fetching {company} Greenhouse API: {e}")
            # Fallback to playwright scraping if API fails
            return []
        
        return jobs
    
    def check_all_boards(self):
        """Check all job boards for new postings"""
        # Special handling for Greenhouse boards
        greenhouse_boards = {
            'Anthropic': 'anthropic',
            'Intrinsic': 'intrinsic',
            'Netflix': 'netflix',
            'SpaceX': 'spacex',
            'OpenAI': 'openai'
        }
        
        for company, config in self.job_boards.items():
            try:
                # Try Greenhouse API first for supported companies
                if company in greenhouse_boards:
                    jobs = self.scrape_greenhouse_api(company, greenhouse_boards[company])
                    if not jobs:
                        # Fallback to playwright if API fails
                        jobs = self.scrape_job_board(company, config)
                else:
                    jobs = self.scrape_job_board(company, config)
                
                # Update sent jobs tracking
                if company not in self.sent_jobs:
                    self.sent_jobs[company] = []
                
                for job_id, _ in jobs:
                    if job_id not in self.sent_jobs[company]:
                        self.sent_jobs[company].append(job_id)
                
                # Keep only recent sent jobs (last 200)
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
        """Send email notification for truly new jobs only - NEVER existing jobs"""
        if not self.new_jobs:
            logger.info("No new jobs found")
            return
        
        try:
            # Remove duplicates - only truly NEW jobs posted since last check
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
                    <strong>Total NEW job postings: {len(unique_jobs)}</strong><br>
                    Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
                    <span class="new-badge">NEW</span> = Job posting created since last check<br>
                    <em>Note: Only showing jobs that were JUST posted, not existing jobs</em>
                </div>
            """
            
            # Group jobs by company
            jobs_by_company = {}
            for job in unique_jobs:
                if job['company'] not in jobs_by_company:
                    jobs_by_company[job['company']] = []
                jobs_by_company[job['company']].append(job)
            
            # Show ALL 18 companies, even those with no new jobs
            all_companies = sorted(self.job_boards.keys())
            
            for company in all_companies:
                jobs = jobs_by_company.get(company, [])
                company_url = self.job_boards[company]['url']
                
                if jobs:
                    # Company has new jobs
                    html_body += f"""
                    <div class="job">
                        <div class="company">🏢 {company} ({len(jobs)} NEW postings)</div>
                    """
                    for job in jobs[:10]:  # Show max 10 jobs per company
                        location = job.get('location', '')
                        location_text = f" - {location}" if location else ""
                        html_body += f"""
                        <div class="job-title">• {job['job_title']}{location_text} <span class="new-badge">NEW</span></div>
                        """
                    if len(jobs) > 10:
                        html_body += f"""
                        <div class="job-title">... and {len(jobs) - 10} more new positions</div>
                        """
                else:
                    # Company has no new jobs
                    html_body += f"""
                    <div class="job">
                        <div class="company">🏢 {company}</div>
                        <div class="no-jobs">No new job postings since last check</div>
                    """
                
                # Always include link to job board
                html_body += f"""
                    <div style="margin-top: 10px;"><a href="{company_url}">View {company} Job Board →</a></div>
                </div>
                """
            
            html_body += """
                <hr>
                <p style="color: #7f8c8d; font-size: 12px;">
                    <strong>Important:</strong> This notification ONLY includes brand new job postings that were created since the last check.<br>
                    Existing jobs on the boards are NOT shown, even if they were posted recently.<br>
                    Checking frequency: Every hour<br>
                    Companies monitored: 18<br>
                    <strong>Tip:</strong> Be among the first to apply to these brand new postings!
                </p>
            </body>
            </html>
            """
            
            part = MIMEText(html_body, 'html')
            msg.attach(part)
            
            # Send email via Gmail
            logger.info("Connecting to Gmail SMTP server...")
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(self.gmail_user, self.gmail_password)
                server.send_message(msg)
            
            logger.info(f"✅ Email sent successfully with {len(unique_jobs)} NEW jobs!")
            
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
