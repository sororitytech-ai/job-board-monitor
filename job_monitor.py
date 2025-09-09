import os
import json
import time
import hashlib
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List
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
        self.new_jobs = []
        
        # Updated job board configurations with better selectors
        self.job_boards = {
            'Google': {
                'url': 'https://www.google.com/about/careers/applications/jobs/results/?location=United%20States&sort_by=date&q=product%2C%20program%2C%20project',
                'selectors': [
                    'li[class*="job"]',
                    'div[class*="job-item"]',
                    'div[class*="gc-card"]',
                    'a[href*="/jobs/results/"]',
                    'div[role="listitem"]'
                ],
                'wait_for': 5000
            },
            'Apple': {
                'url': 'https://jobs.apple.com/en-us/search?sort=newest&key=Product%25252C%252520Program%25252C%252520Project&location=united-states-USA',
                'selectors': [
                    'tbody.table-tbody tr[role="row"]',
                    'tr.table-row',
                    'a[id*="job-"]',
                    'div[class*="job-"]'
                ],
                'wait_for': 5000
            },
            'Netflix': {
                'url': 'https://explore.jobs.netflix.net/careers?pid=790301701184&Region=ucan&domain=netflix.com&sort_by=new',
                'selectors': [
                    'a[data-card-type="job"]',
                    'div[class*="job-card"]',
                    'article[class*="job"]',
                    'div.position',
                    'li[class*="position"]'
                ],
                'wait_for': 5000
            },
            'Tesla': {
                'url': 'https://www.tesla.com/careers/search/?region=5&site=US&type=1',
                'selectors': [
                    'tr.tds-table-row',
                    'tr[class*="table-row"]',
                    'a[href*="/careers/"]',
                    'tbody tr'
                ],
                'wait_for': 5000
            },
            'Amazon': {
                'url': 'https://www.amazon.jobs/en/search?offset=0&result_limit=10&sort=recent&job_type%5B%5D=Full-Time&country%5B%5D=USA&state%5B%5D=New%20York&state%5B%5D=New%20Jersey',
                'selectors': [
                    'div.job-tile',
                    'div[class*="job-tile"]'
                ],
                'wait_for': 3000
            },
            'Meta': {
                'url': 'https://www.metacareers.com/jobs',
                'selectors': [
                    'a[href*="/jobs/"]',
                    'div[class*="job-card"]'
                ],
                'wait_for': 3000
            },
            'Microsoft': {
                'url': 'https://jobs.careers.microsoft.com/global/en/search?q=%22product%22%20OR%20%22project%22%20OR%20%22program%22&lc=United%20States&et=Full-Time&l=en_us&pg=1&pgSz=20&o=Recent&flt=true',
                'selectors': [
                    'div.ms-List-cell',
                    'div[data-automation-id="job"]'
                ],
                'wait_for': 3000
            },
            'NVIDIA': {
                'url': 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?q=product,%20program,%20project',
                'selectors': [
                    'li[data-automation-id="jobItem"]',
                    'div[data-automation-id="jobItem"]',
                    'a[data-automation-id="jobTitle"]',
                    'div[role="listitem"]'
                ],
                'wait_for': 7000
            },
            'Stripe': {
                'url': 'https://stripe.com/jobs/search?office_locations=North+America--New+York',
                'selectors': [
                    'a.JobsListings__link',
                    'a[class*="JobsListings"]'
                ],
                'wait_for': 3000
            },
            'OpenAI': {
                'url': 'https://openai.com/careers/search/',
                'selectors': [
                    'a[href*="/careers/"]',
                    'div[class*="job"]',
                    'li[class*="career"]',
                    'div.opening',
                    'article'
                ],
                'wait_for': 5000
            },
            'Anthropic': {
                'url': 'https://boards.greenhouse.io/anthropic',
                'selectors': [
                    'div.opening',
                    'div[class*="opening"]',
                    'a[href*="/anthropic/jobs/"]'
                ],
                'wait_for': 3000
            },
            'SpaceX': {
                'url': 'https://www.spacex.com/careers/jobs/',
                'selectors': [
                    'div[id*="job"]',
                    'tr[class*="job"]',
                    'div.opening',
                    'a[href*="/careers/"]',
                    'li[class*="job"]'
                ],
                'wait_for': 5000
            },
            # Additional companies from your list
            'Waymo': {
                'url': 'https://careers.withwaymo.com/jobs/search?page=1&query=project%2C+program%2C+product',
                'selectors': [
                    'div[data-testid="job-card"]',
                    'a[href*="/jobs/"]',
                    'div[class*="job-card"]'
                ],
                'wait_for': 5000
            },
            'Uber': {
                'url': 'https://www.uber.com/us/en/careers/list/?location=USA-New%20York',
                'selectors': [
                    'a[data-baseweb="link"]',
                    'div[class*="job"]',
                    'a[href*="/careers/"]'
                ],
                'wait_for': 5000
            },
            'Two Sigma': {
                'url': 'https://careers.twosigma.com/careers/OpenRoles',
                'selectors': [
                    'div.job-result',
                    'tr[class*="job"]',
                    'a[href*="JobDetail"]'
                ],
                'wait_for': 5000
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
                        return history_response.json()
            
            # Create new gist if not found
            return self.create_history_gist()
        except Exception as e:
            logger.error(f"Error loading job history: {e}")
            return {}
    
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
                    'job_history.json': {
                        'content': json.dumps({})
                    }
                }
            }
            response = requests.post('https://api.github.com/gists', headers=headers, json=data)
            return {}
        except Exception as e:
            logger.error(f"Error creating history gist: {e}")
            return {}
    
    def save_job_history(self):
        """Save job history to GitHub Gist"""
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
                # Update existing gist
                data = {
                    'files': {
                        'job_history.json': {
                            'content': json.dumps(self.job_history, indent=2)
                        }
                    }
                }
                requests.patch(f'https://api.github.com/gists/{gist_id}', headers=headers, json=data)
                logger.info("Job history saved successfully")
        except Exception as e:
            logger.error(f"Error saving job history: {e}")
    
    def scrape_job_board(self, company: str, config: Dict) -> List[str]:
        """Scrape job board using Playwright with multiple selector fallbacks"""
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
                page.goto(config['url'], wait_until='domcontentloaded', timeout=30000)
                
                # Wait for content to load
                wait_time = config.get('wait_for', 5000)
                page.wait_for_timeout(wait_time)
                
                # Try to handle cookie banners or popups
                try:
                    # Common cookie/popup selectors
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
                
                # Try to click "View More" or "Load More" buttons
                try:
                    for _ in range(2):
                        load_more_selectors = [
                            'button:has-text("View More")',
                            'button:has-text("Load More")',
                            'button:has-text("Show More")',
                            'a:has-text("View More")',
                            'button[aria-label*="load more"]'
                        ]
                        for selector in load_more_selectors:
                            if page.locator(selector).count() > 0:
                                page.locator(selector).first.click()
                                page.wait_for_timeout(2000)
                                break
                except:
                    pass
                
                # Scroll to load more content
                for _ in range(3):
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    page.wait_for_timeout(1500)
                
                # Try multiple selectors
                selectors = config.get('selectors', [config.get('selector', '')])
                elements_found = False
                
                for selector in selectors:
                    try:
                        elements = page.locator(selector).all()
                        if elements:
                            logger.info(f"Found {len(elements)} job elements for {company} using selector: {selector}")
                            elements_found = True
                            
                            for idx, element in enumerate(elements[:30]):
                                try:
                                    job_text = element.text_content()
                                    if job_text and len(job_text) > 5:
                                        job_id = hashlib.md5(f"{company}_{job_text}".encode()).hexdigest()
                                        jobs.append(job_id)
                                        
                                        # Check if this is a new job
                                        if company not in self.job_history:
                                            self.job_history[company] = []
                                        
                                        if job_id not in self.job_history[company]:
                                            job_title = job_text.strip()[:100]
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
                
                if not elements_found:
                    logger.warning(f"No job elements found for {company} with any selector")
                    # Log page title to verify we're on the right page
                    page_title = page.title()
                    logger.info(f"Page title for {company}: {page_title}")
                
                browser.close()
                
        except Exception as e:
            logger.error(f"Error scraping {company}: {e}")
        
        return jobs
    
    def check_all_boards(self):
        """Check all job boards for new postings"""
        for company, config in self.job_boards.items():
            try:
                jobs = self.scrape_job_board(company, config)
                
                # Update history
                if company not in self.job_history:
                    self.job_history[company] = []
                
                # Find new jobs
                new_job_ids = set(jobs) - set(self.job_history[company])
                
                if new_job_ids:
                    logger.info(f"Found {len(new_job_ids)} new jobs at {company}")
                    self.job_history[company].extend(list(new_job_ids))
                    # Keep only last 200 job IDs per company
                    self.job_history[company] = self.job_history[company][-200:]
                else:
                    logger.info(f"No new jobs found at {company}")
                
                # Rate limiting
                time.sleep(3)
                
            except Exception as e:
                logger.error(f"Error checking {company}: {e}")
                continue
    
    def send_email_notification(self):
        """Send email notification for new jobs"""
        if not self.new_jobs:
            logger.info("No new jobs found")
            return
        
        try:
            logger.info(f"Preparing to send email with {len(self.new_jobs)} new jobs...")
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'🎯 {len(self.new_jobs)} New Job Postings Found!'
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
                    .company {{ font-weight: bold; color: #2c3e50; font-size: 16px; }}
                    .job-title {{ color: #34495e; margin: 8px 0; }}
                    .timestamp {{ color: #7f8c8d; font-size: 12px; }}
                    a {{ color: #3498db; text-decoration: none; }}
                    a:hover {{ text-decoration: underline; }}
                </style>
            </head>
            <body>
                <h2>🚀 New Job Postings Alert</h2>
                <div class="summary">
                    <strong>Total new jobs found: {len(self.new_jobs)}</strong><br>
                    Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
            """
            
            # Group jobs by company
            jobs_by_company = {}
            for job in self.new_jobs:
                if job['company'] not in jobs_by_company:
                    jobs_by_company[job['company']] = []
                jobs_by_company[job['company']].append(job)
            
            for company, jobs in sorted(jobs_by_company.items()):
                html_body += f"""
                <div class="job">
                    <div class="company">🏢 {company} ({len(jobs)} new jobs)</div>
                """
                for job in jobs[:5]:  # Show max 5 jobs per company
                    html_body += f"""
                    <div class="job-title">• {job['job_title']}</div>
                    """
                if len(jobs) > 5:
                    html_body += f"""
                    <div class="job-title">... and {len(jobs) - 5} more</div>
                    """
                html_body += f"""
                    <div><a href="{jobs[0]['url']}">View All {company} Jobs →</a></div>
                    <div class="timestamp">Found at: {jobs[0]['timestamp']}</div>
                </div>
                """
            
            html_body += """
                <hr>
                <p style="color: #7f8c8d; font-size: 12px;">
                    This is an automated notification from your Job Board Monitor.<br>
                    Checking frequency: Every hour<br>
                    Companies monitored: 15
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
            
            logger.info(f"✅ Email sent successfully with {len(self.new_jobs)} new jobs!")
            
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
