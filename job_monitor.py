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
from typing import Dict, List, Tuple
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
        
        # Junk filter patterns
        self.junk_patterns = [
            'cookie', 'consent', 'privacy', 'manage preferences', 
            'do not sell', 'help center', 'view role', 'read more', 
            'submit resume', 'careers blog', 'google data policy'
        ]
        
        self.job_boards = self.get_job_board_config()
    
    def get_job_board_config(self):
        """Return job board configurations"""
        return {
            'Google': {
                'url': 'https://www.google.com/about/careers/applications/jobs/results/?location=United%20States&sort_by=date&q=product%2C%20program%2C%20project',
                'method': 'playwright',
                'selectors': ['h2.gc-card__title', 'a.gc-card__title-link'],
                'wait_for': 8000
            },
            'Intrinsic': {
                'url': 'https://boards.greenhouse.io/intrinsic',
                'method': 'api',
                'api_endpoint': 'https://boards-api.greenhouse.io/v1/boards/intrinsic/jobs'
            },
            'Waymo': {
                'url': 'https://careers.withwaymo.com/jobs/search?page=1&query=project%2C+program%2C+product',
                'method': 'playwright',
                'selectors': ['h3', 'div[data-testid="job-card"] h3'],
                'wait_for': 5000
            },
            'Wing': {
                'url': 'https://wing.com/careers',
                'method': 'requests',
                'parse_method': 'wing_custom'
            },
            'X Moonshot': {
                'url': 'https://x.company/careers/',
                'method': 'playwright',
                'selectors': ['h3.job-title', 'a[href*="careers"] h3'],
                'wait_for': 5000
            },
            'Apple': {
                'url': 'https://jobs.apple.com/en-us/search?sort=newest&key=Product%25252C%252520Program%25252C%252520Project&location=united-states-USA',
                'method': 'playwright',
                'selectors': ['td.table-col-1 a'],
                'wait_for': 7000
            },
            'NVIDIA': {
                'url': 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?q=product%20program%20project',
                'method': 'playwright',
                'selectors': ['a[data-automation-id="jobTitle"]'],
                'wait_for': 7000
            },
            'Netflix': {
                'url': 'https://api.greenhouse.io/v1/boards/netflix/jobs',
                'method': 'api'
            },
            'Anthropic': {
                'url': 'https://api.greenhouse.io/v1/boards/anthropic/jobs',
                'method': 'api'
            },
            'Tesla': {
                'url': 'https://www.tesla.com/careers/search/?region=5&site=US&type=1',
                'method': 'playwright',
                'selectors': ['tr.tds-table-row td:first-child a'],
                'wait_for': 8000,
                'cloudflare': True
            },
            'Amazon': {
                'url': 'https://www.amazon.jobs/en/search?offset=0&result_limit=20&sort=recent&country%5B%5D=USA&state%5B%5D=New%20York',
                'method': 'playwright',
                'selectors': ['h3.job-title'],
                'wait_for': 5000
            },
            'Meta': {
                'url': 'https://www.metacareers.com/jobs',
                'method': 'playwright',
                'selectors': ['div._8sef', 'a[href*="/jobs/"] div._8sel'],
                'wait_for': 6000
            },
            'SpaceX': {
                'url': 'https://api.greenhouse.io/v1/boards/spacex/jobs',
                'method': 'api'
            },
            'Stripe': {
                'url': 'https://stripe.com/jobs/search?office_locations=North+America--New+York',
                'method': 'playwright',
                'selectors': ['a.JobsListings__link h3'],
                'wait_for': 4000
            },
            'Uber': {
                'url': 'https://www.uber.com/us/en/careers/list/?location=USA-New%20York',
                'method': 'playwright',
                'selectors': ['h3', 'a[href*="/careers/list/"] h3'],
                'wait_for': 6000
            },
            'Two Sigma': {
                'url': 'https://careers.twosigma.com/careers/OpenRoles',
                'method': 'playwright',
                'selectors': ['span.job-title'],
                'wait_for': 5000
            },
            'Microsoft': {
                'url': 'https://jobs.careers.microsoft.com/global/en/search?q=product%20program%20project&lc=United%20States&l=en_us&o=Recent',
                'method': 'playwright',
                'selectors': ['span[data-automation-id="jobTitle"]'],
                'wait_for': 5000
            },
            'OpenAI': {
                'url': 'https://api.greenhouse.io/v1/boards/openai/jobs',
                'method': 'api'
            }
        }
    
    def load_job_history(self) -> Dict:
        """Load job history"""
        try:
            if not self.gist_token:
                return {}
            headers = {'Authorization': f'token {self.gist_token}'}
            response = requests.get('https://api.github.com/gists', headers=headers)
            if response.status_code == 200:
                gists = response.json()
                for gist in gists:
                    if 'job_history.json' in gist.get('files', {}):
                        file_url = gist['files']['job_history.json']['raw_url']
                        return requests.get(file_url).json()
            return {}
        except:
            return {}
    
    def load_sent_jobs(self) -> Dict:
        """Load sent jobs history"""
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
                        return requests.get(file_url).json()
            return {}
        except:
            return {}
    
    def is_junk(self, text: str) -> bool:
        """Check if text is junk"""
        if not text or len(text) < 5:
            return True
        text_lower = text.lower().strip()
        
        # Check junk patterns
        for pattern in self.junk_patterns:
            if pattern in text_lower:
                return True
        
        # Filter out single words that aren't job titles
        if ' ' not in text and text_lower in ['engineering', 'sales', 'global', 'meta', 'facebook']:
            return True
            
        return False
    
    def clean_job_title(self, text: str) -> str:
        """Clean job title"""
        # Remove location/date info
        text = re.sub(r'•.*', '', text)
        text = re.sub(r'\|.*', '', text)
        text = re.sub(r'Locations?.*', '', text)
        text = re.sub(r'(Today|Yesterday|\d+ days ago).*', '', text)
        return text.strip()[:150]
    
    def scrape_api(self, company: str, config: Dict) -> List[Tuple[str, str]]:
        """Scrape using API"""
        jobs = []
        try:
            endpoint = config.get('api_endpoint', config['url'])
            response = requests.get(endpoint, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for job in data.get('jobs', [])[:30]:
                    title = job.get('title', '')
                    job_id = str(job.get('id', ''))
                    location = job.get('location', {}).get('name', '') if isinstance(job.get('location'), dict) else ''
                    
                    # Filter for relevant jobs
                    if any(kw in title.lower() for kw in ['product', 'program', 'project', 'manager']):
                        if any(loc in str(location) for loc in ['United States', 'USA', 'US', 'New York', 'Remote', 'San Francisco']):
                            clean_title = self.clean_job_title(title)
                            if not self.is_junk(clean_title):
                                unique_id = f"{company}_api_{job_id}"
                                jobs.append((unique_id, clean_title))
                                
                                if self.is_new_job(unique_id, company):
                                    self.new_jobs.append({
                                        'company': company,
                                        'title': clean_title,
                                        'location': location,
                                        'url': config.get('url', ''),
                                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                                    })
                                    logger.info(f"NEW JOB: {company} - {clean_title}")
        except Exception as e:
            logger.error(f"API error for {company}: {e}")
        return jobs
    
    def scrape_playwright(self, company: str, config: Dict) -> List[Tuple[str, str]]:
        """Scrape using Playwright"""
        jobs = []
        try:
            logger.info(f"Checking {company}...")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                
                page = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
                ).new_page()
                
                logger.info(f"Loading {company} page...")
                page.goto(config['url'], wait_until='domcontentloaded', timeout=30000)
                
                # Wait and handle cloudflare
                if config.get('cloudflare'):
                    page.wait_for_timeout(10000)
                else:
                    page.wait_for_timeout(config.get('wait_for', 5000))
                
                # Handle cookies
                try:
                    for btn in ['Accept', 'OK', 'Got it']:
                        if page.locator(f'button:has-text("{btn}")').count() > 0:
                            page.locator(f'button:has-text("{btn}")').first.click()
                            break
                except:
                    pass
                
                # Scroll for dynamic content
                for _ in range(3):
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    page.wait_for_timeout(1500)
                
                # Get jobs
                for selector in config.get('selectors', []):
                    elements = page.locator(selector).all()
                    if elements:
                        logger.info(f"Found {len(elements)} elements for {company}")
                        for element in elements[:30]:
                            try:
                                text = element.text_content()
                                if text and not self.is_junk(text):
                                    clean_title = self.clean_job_title(text)
                                    if clean_title and len(clean_title) > 10:
                                        job_id = hashlib.md5(f"{company}_{clean_title}".encode()).hexdigest()
                                        jobs.append((job_id, clean_title))
                                        
                                        if self.is_new_job(job_id, company):
                                            self.new_jobs.append({
                                                'company': company,
                                                'title': clean_title,
                                                'url': config['url'],
                                                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                                            })
                                            logger.info(f"NEW JOB: {company} - {clean_title}")
                            except:
                                continue
                        break
                
                browser.close()
                
        except Exception as e:
            logger.error(f"Playwright error for {company}: {e}")
        return jobs
    
    def scrape_requests(self, company: str, config: Dict) -> List[Tuple[str, str]]:
        """Scrape using requests for simple sites"""
        jobs = []
        try:
            response = requests.get(config['url'], timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Custom parsing for Wing
            if config.get('parse_method') == 'wing_custom':
                job_elements = soup.find_all(['h3', 'div'], class_=re.compile('job|career|position'))
                for element in job_elements[:20]:
                    text = element.get_text(strip=True)
                    if text and not self.is_junk(text) and len(text) > 10:
                        clean_title = self.clean_job_title(text)
                        job_id = hashlib.md5(f"{company}_{clean_title}".encode()).hexdigest()
                        jobs.append((job_id, clean_title))
                        
                        if self.is_new_job(job_id, company):
                            self.new_jobs.append({
                                'company': company,
                                'title': clean_title,
                                'url': config['url'],
                                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                            })
                            logger.info(f"NEW JOB: {company} - {clean_title}")
        except Exception as e:
            logger.error(f"Requests error for {company}: {e}")
        return jobs
    
    def is_new_job(self, job_id: str, company: str) -> bool:
        """Check if job is new"""
        if company not in self.sent_jobs:
            self.sent_jobs[company] = []
        return job_id not in self.sent_jobs[company]
    
    def check_all_boards(self):
        """Check all job boards"""
        for company, config in self.job_boards.items():
            try:
                method = config.get('method', 'playwright')
                
                if method == 'api':
                    jobs = self.scrape_api(company, config)
                elif method == 'requests':
                    jobs = self.scrape_requests(company, config)
                else:
                    jobs = self.scrape_playwright(company, config)
                
                # Update history
                if company not in self.job_history:
                    self.job_history[company] = {}
                
                for job_id, title in jobs:
                    if job_id not in self.job_history[company]:
                        self.job_history[company][job_id] = {
                            'title': title,
                            'first_seen': datetime.now().isoformat()
                        }
                    if job_id not in self.sent_jobs.get(company, []):
                        self.sent_jobs.setdefault(company, []).append(job_id)
                
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error checking {company}: {e}")
    
    def save_history(self):
        """Save job history and sent jobs"""
        try:
            if not self.gist_token:
                return
            
            headers = {'Authorization': f'token {self.gist_token}'}
            
            # Find or create gist
            response = requests.get('https://api.github.com/gists', headers=headers)
            gist_id = None
            
            if response.status_code == 200:
                for gist in response.json():
                    if 'job_history.json' in gist.get('files', {}):
                        gist_id = gist['id']
                        break
            
            if not gist_id:
                # Create new gist
                data = {
                    'description': 'Job Board Monitor History',
                    'public': False,
                    'files': {
                        'job_history.json': {'content': json.dumps({})},
                        'sent_jobs.json': {'content': json.dumps({})}
                    }
                }
                response = requests.post('https://api.github.com/gists', headers=headers, json=data)
                gist_id = response.json().get('id')
            
            if gist_id:
                # Update gist
                data = {
                    'files': {
                        'job_history.json': {'content': json.dumps(self.job_history, indent=2)},
                        'sent_jobs.json': {'content': json.dumps(self.sent_jobs, indent=2)}
                    }
                }
                requests.patch(f'https://api.github.com/gists/{gist_id}', headers=headers, json=data)
                logger.info("History saved successfully")
        except Exception as e:
            logger.error(f"Error saving history: {e}")
    
    def send_email(self):
        """Send email notification"""
        if not self.new_jobs:
            logger.info("No new jobs found")
            return
        
        try:
            # Filter to unique jobs only
            seen = set()
            unique_jobs = []
            for job in self.new_jobs:
                key = f"{job['company']}_{job['title']}"
                if key not in seen:
                    seen.add(key)
                    unique_jobs.append(job)
            
            logger.info(f"Sending email with {len(unique_jobs)} new jobs...")
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'🎯 {len(unique_jobs)} New Job Postings Found!'
            msg['From'] = self.gmail_user
            msg['To'] = 'sororitytech@gmail.com'
            
            # Create HTML
            html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2>🚀 New Job Postings Alert</h2>
                <div style="background: #e8f4f8; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <strong>Total new jobs: {len(unique_jobs)}</strong><br>
                    Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
            """
            
            # Group by company
            by_company = {}
            for job in unique_jobs:
                by_company.setdefault(job['company'], []).append(job)
            
            for company, jobs in sorted(by_company.items()):
                html += f"""
                <div style="margin: 15px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px;">
                    <div style="font-weight: bold; color: #2c3e50; font-size: 16px;">
                        🏢 {company} ({len(jobs)} new positions)
                    </div>
                """
                for job in jobs[:10]:
                    location = f" - {job.get('location', '')}" if job.get('location') else ""
                    html += f"""
                    <div style="margin: 5px 0; padding-left: 20px;">
                        • {job['title']}{location} <span style="background: #27ae60; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">NEW</span>
                    </div>
                    """
                if len(jobs) > 10:
                    html += f"""<div style="margin: 5px 0; padding-left: 20px;">... and {len(jobs)-10} more</div>"""
                html += f"""
                    <div style="margin-top: 10px;">
                        <a href="{jobs[0]['url']}" style="color: #3498db;">View All {company} Jobs →</a>
                    </div>
                </div>
                """
            
            html += """
                <hr>
                <p style="color: #7f8c8d; font-size: 12px;">
                    Automated Job Board Monitor<br>
                    Checking: Every hour | Companies: 18<br>
                    Apply within 24 hours for best results!
                </p>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            # Send
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(self.gmail_user, self.gmail_password)
                server.send_message(msg)
            
            logger.info(f"✅ Email sent with {len(unique_jobs)} jobs!")
            
        except Exception as e:
            logger.error(f"Email error: {e}")
    
    def run(self):
        """Main execution"""
        logger.info("="*50)
        logger.info("Starting Job Board Monitor")
        logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Monitoring {len(self.job_boards)} companies")
        logger.info("="*50)
        
        self.check_all_boards()
        
        if self.new_jobs:
            logger.info(f"Total new jobs found: {len(self.new_jobs)}")
            self.send_email()
        else:
            logger.info("No new jobs found")
        
        self.save_history()
        
        logger.info("Job Board Monitor completed!")
        logger.info("="*50)

if __name__ == "__main__":
    monitor = JobBoardMonitor()
    monitor.run()
