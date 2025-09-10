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
        
        # Updated configurations with better selectors and API endpoints
        self.job_boards = {
            'Google': {
                'url': 'https://www.google.com/about/careers/applications/jobs/results/?location=United%20States&sort_by=date&q=product%2C%20program%2C%20project',
                'method': 'playwright',
                'selectors': ['h2.gc-card__title', 'a.gc-card__title-link'],
                'wait_for': 7000
            },
            'Intrinsic': {
                'url': 'https://boards.greenhouse.io/intrinsic',
                'method': 'api',
                'api_url': 'https://boards-api.greenhouse.io/v1/boards/intrinsic/jobs'
            },
            'Waymo': {
                'url': 'https://careers.withwaymo.com/jobs/search?page=1&query=project%2C+program%2C+product',
                'method': 'playwright',
                'selectors': ['h3', 'a[href*="/jobs/"]'],
                'filter_out': ['Read more', 'Open roles', 'View all'],
                'wait_for': 5000
            },
            'Wing': {
                'url': 'https://wing.com/careers',
                'method': 'playwright',
                'selectors': ['h3', '.job-title', 'a[href*="careers"]'],
                'wait_for': 5000
            },
            'X Moonshot': {
                'url': 'https://x.company/careers/',
                'method': 'playwright',
                'selectors': ['.job-title', 'h3', 'a[href*="careers"]'],
                'wait_for': 5000
            },
            'Apple': {
                'url': 'https://jobs.apple.com/en-us/search?sort=newest&key=Product%25252C%252520Program%25252C%252520Project&location=united-states-USA',
                'method': 'playwright',
                'selectors': ['td.table-col-1', 'span.table-col-1-link'],
                'filter_out': ['Submit Resume'],
                'wait_for': 7000
            },
            'NVIDIA': {
                'url': 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?q=product,%20program,%20project',
                'method': 'playwright',
                'selectors': ['a[data-automation-id="jobTitle"]'],
                'wait_for': 7000
            },
            'Netflix': {
                'url': 'https://api.greenhouse.io/v1/boards/netflix/jobs',
                'method': 'api'
            },
            'Anthropic': {
                'url': 'https://boards-api.greenhouse.io/v1/boards/anthropic/jobs',
                'method': 'api'
            },
            'Tesla': {
                'url': 'https://www.tesla.com/cua-api/apps/careers/state',
                'method': 'json_api'
            },
            'Amazon': {
                'url': 'https://www.amazon.jobs/en/search?offset=0&result_limit=20&sort=recent&job_type%5B%5D=Full-Time&country%5B%5D=USA&state%5B%5D=New%20York&state%5B%5D=New%20Jersey',
                'method': 'playwright',
                'selectors': ['h3.job-title'],
                'wait_for': 5000
            },
            'Meta': {
                'url': 'https://www.metacareers.com/jobs',
                'method': 'playwright',
                'selectors': ['div[class*="job-title"]', 'a[href*="/jobs/"] div'],
                'wait_for': 5000
            },
            'SpaceX': {
                'url': 'https://boards-api.greenhouse.io/v1/boards/spacex/jobs',
                'method': 'api'
            },
            'Stripe': {
                'url': 'https://stripe.com/jobs/search?office_locations=North+America--New+York',
                'method': 'playwright',
                'selectors': ['h3', 'a.JobsListings__link h3'],
                'wait_for': 3000
            },
            'Uber': {
                'url': 'https://www.uber.com/api/loadSearchJobsResults',
                'method': 'json_api',
                'params': {'locname': 'USA-New York', 'limit': 50}
            },
            'Two Sigma': {
                'url': 'https://careers.twosigma.com/careers/OpenRoles',
                'method': 'playwright',
                'selectors': ['span.job-title', 'a[href*="JobDetail"] span'],
                'filter_out': ['View role'],
                'wait_for': 5000
            },
            'Microsoft': {
                'url': 'https://jobs.careers.microsoft.com/global/en/search?q=%22product%22%20OR%20%22project%22%20OR%20%22program%22&lc=United%20States&et=Full-Time&l=en_us&pg=1&pgSz=20&o=Recent&flt=true',
                'method': 'playwright',
                'selectors': ['span[data-automation-id="jobTitle"]', 'h2'],
                'wait_for': 5000
            },
            'OpenAI': {
                'url': 'https://api.greenhouse.io/v1/boards/openai/jobs',
                'method': 'api'
            }
        }
    
    def load_job_history(self) -> Dict:
        """Load job history from GitHub Gist"""
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
                        history_response = requests.get(file_url)
                        data = history_response.json()
                        # Clean old entries (older than 7 days)
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
                        first_seen = datetime.fromisoformat(job_info['first_seen'])
                        if first_seen > week_ago:
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
    
    def is_truly_new_job(self, job_id: str, company: str) -> bool:
        """Check if this job is truly new (not sent before)"""
        # Check if we've already sent an email about this job
        if company in self.sent_jobs and job_id in self.sent_jobs.get(company, []):
            return False
        return True
    
    def scrape_with_api(self, company: str, config: Dict) -> List[Tuple[str, str]]:
        """Fetch jobs using Greenhouse API"""
        jobs = []
        try:
            api_url = config.get('api_url', config['url'])
            response = requests.get(api_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                job_list = data.get('jobs', [])
                
                for job in job_list[:30]:
                    title = job.get('title', '')
                    job_id = str(job.get('id', ''))
                    location = job.get('location', {}).get('name', '')
                    
                    # Filter for US/relevant locations
                    if any(loc in str(location) for loc in ['United States', 'USA', 'US', 'New York', 'San Francisco', 'Remote']):
                        # Check if job title contains our keywords
                        if any(keyword in title.lower() for keyword in ['product', 'program', 'project']):
                            jobs.append((f"{company}_api_{job_id}", title))
                            
                            if self.is_truly_new_job(f"{company}_api_{job_id}", company):
                                self.new_jobs.append({
                                    'company': company,
                                    'job_title': title,
                                    'location': location,
                                    'url': config.get('url', ''),
                                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                                })
                                logger.info(f"NEW JOB: {company} - {title}")
                                
        except Exception as e:
            logger.error(f"Error fetching {company} API: {e}")
        
        return jobs
    
    def scrape_json_api(self, company: str, config: Dict) -> List[Tuple[str, str]]:
        """Fetch jobs from JSON APIs (Tesla, Uber)"""
        jobs = []
        try:
            if company == 'Tesla':
                response = requests.get(config['url'], timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    listings = data.get('listings', [])
                    
                    for job in listings[:30]:
                        if job.get('country') == 'US':
                            title = job.get('title', '')
                            job_id = job.get('id', '')
                            if any(keyword in title.lower() for keyword in ['product', 'program', 'project']):
                                jobs.append((f"tesla_{job_id}", title))
                                
                                if self.is_truly_new_job(f"tesla_{job_id}", company):
                                    self.new_jobs.append({
                                        'company': company,
                                        'job_title': title,
                                        'url': f"https://www.tesla.com/careers/{job_id}",
                                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                                    })
                                    
            elif company == 'Uber':
                params = config.get('params', {})
                response = requests.post(config['url'], json=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    for job in data.get('data', {}).get('results', [])[:30]:
                        title = job.get('title', '')
                        job_id = job.get('id', '')
                        if any(keyword in title.lower() for keyword in ['product', 'program', 'project']):
                            jobs.append((f"uber_{job_id}", title))
                            
                            if self.is_truly_new_job(f"uber_{job_id}", company):
                                self.new_jobs.append({
                                    'company': company,
                                    'job_title': title,
                                    'url': f"https://www.uber.com/careers/{job_id}",
                                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
                                })
                                
        except Exception as e:
            logger.error(f"Error fetching {company} JSON API: {e}")
        
        return jobs
    
    def scrape_with_playwright(self, company: str, config: Dict) -> List[Tuple[str, str]]:
        """Scrape job board using Playwright"""
        jobs = []
        try:
            logger.info(f"Checking {company}...")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
                )
                
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                
                page = context.new_page()
                
                logger.info(f"Loading {company} careers page...")
                page.goto(config['url'], wait_until='domcontentloaded', timeout=30000)
                
                wait_time = config.get('wait_for', 5000)
                page.wait_for_timeout(wait_time)
                
                # Handle popups
                try:
                    for selector in ['button:has-text("Accept")', 'button:has-text("OK")', 'button[aria-label*="close"]']:
                        if page.locator(selector).count() > 0:
                            page.locator(selector).first.click()
                            page.wait_for_timeout(1000)
                            break
                except:
                    pass
                
                # Scroll to load content
                for _ in range(3):
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    page.wait_for_timeout(1500)
                
                # Try multiple selectors
                selectors = config.get('selectors', [])
                filter_out = config.get('filter_out', [])
                
                for selector in selectors:
                    try:
                        elements = page.locator(selector).all()
                        if elements:
                            logger.info(f"Found {len(elements)} elements for {company}")
                            
                            for element in elements[:30]:
                                try:
                                    job_text = element.text_content()
                                    if not job_text or len(job_text) < 5:
                                        continue
                                    
                                    # Filter out non-job content
                                    if any(filter_text in job_text for filter_text in filter_out):
                                        continue
                                    
                                    # Skip navigation/UI elements
                                    if any(skip in job_text.lower() for skip in ['privacy', 'careers', 'help center', 'do not sell']):
                                        continue
                                    
                                    job_id = self.extract_job_id(job_text, company)
                                    job_title = job_text.strip()[:100]
                                    
                                    jobs.append((job_id, job_title))
                                    
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
                
                browser.close()
                
        except Exception as e:
            logger.error(f"Error scraping {company}: {e}")
        
        return jobs
    
    def check_all_boards(self):
        """Check all job boards for new postings"""
        for company, config in self.job_boards.items():
            try:
                method = config.get('method', 'playwright')
                
                if method == 'api':
                    jobs = self.scrape_with_api(company, config)
                elif method == 'json_api':
                    jobs = self.scrape_json_api(company, config)
                else:
                    jobs = self.scrape_with_playwright(company, config)
                
                # Update history with new format
                if company not in self.job_history:
                    self.job_history[company] = {}
                
                for job_id, job_title in jobs:
                    if job_id not in self.job_history[company]:
                        self.job_history[company][job_id] = {
                            'title': job_title,
                            'first_seen': datetime.now().isoformat()
                        }
                
                # Update sent jobs tracking
                if company not in self.sent_jobs:
                    self.sent_jobs[company] = []
                
                for job in self.new_jobs:
                    if job['company'] == company:
                        job_id = self.extract_job_id(job['job_title'], company)
                        if job_id not in self.sent_jobs[company]:
                            self.sent_jobs[company].append(job_id)
                
                # Keep only recent sent jobs (last 200)
                self.sent_jobs[company] = self.sent_jobs[company][-200:]
                
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error checking {company}: {e}")
                continue
    
    def save_job_history(self):
        """Save both job history and sent jobs"""
        try:
            if not self.gist_token:
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
            logger.info("No new jobs found")
            return
        
        try:
            # Filter to only jobs posted today or yesterday
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            recent_jobs = []
            for job in self.new_jobs:
                # Since we're checking hourly, all new jobs should be recent
                recent_jobs.append(job)
            
            if not recent_jobs:
                logger.info("No recent jobs to report")
                return
            
            logger.info(f"Preparing to send email with {len(recent_jobs)} new jobs...")
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'🎯 {len(recent_jobs)} New Job Postings Found!'
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
                    .timestamp {{ color: #7f8c8d; font-size: 12px; }}
                    a {{ color: #3498db; text-decoration: none; }}
                    a:hover {{ text-decoration: underline; }}
                    .new-badge {{ background: #27ae60; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px; }}
                </style>
            </head>
            <body>
                <h2>🚀 New Job Postings Alert</h2>
                <div class="summary">
                    <strong>Total new jobs: {len(recent_jobs)}</strong><br>
                    Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
                    <span class="new-badge">NEW</span> = Posted within last 24 hours
                </div>
            """
            
            # Group jobs by company
            jobs_by_company = {}
            for job in recent_jobs:
                if job['company'] not in jobs_by_company:
                    jobs_by_company[job['company']] = []
                jobs_by_company[job['company']].append(job)
            
            for company, jobs in sorted(jobs_by_company.items()):
                html_body += f"""
                <div class="job">
                    <div class="company">🏢 {company} ({len(jobs)} new positions)</div>
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
                html_body += f"""
                    <div style="margin-top: 10px;"><a href="{jobs[0]['url']}">View All {company} Jobs →</a></div>
                </div>
                """
            
            html_body += """
                <hr>
                <p style="color: #7f8c8d; font-size: 12px;">
                    This notification contains only NEW job postings that haven't been sent before.<br>
                    Checking frequency: Every hour<br>
                    Companies monitored: 19<br>
                    <strong>Tip:</strong> Apply within the first 24 hours for best chances!
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
            
            logger.info(f"✅ Email sent successfully with {len(recent_jobs)} new jobs!")
            
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
