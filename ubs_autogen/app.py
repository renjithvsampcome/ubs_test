import os
import asyncio
import datetime
import logging
from urllib.parse import urlparse
import aiohttp
import re
import base64
from PIL import Image
import sys
import time

# Import AutoGen libraries
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.ui import Console
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat

from dotenv import load_dotenv
load_dotenv(override=True)

# Configure logging
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

async def process_individual_alert(isin: str, company_name: str, outstanding_shares: int = None) -> str:
    """
    Process a single alert for a company.
    
    Args:
        isin: International Securities Identification Number for the security
        company_name: Name of the company
        outstanding_shares: Number of outstanding shares (required for Swiss companies)
        
    Returns:
        Processing results summary
    """
    from playwright.async_api import async_playwright
    import datetime
    from typing import Tuple
    from supabase import create_client
    import json
    import os
    import re

    proxy_server = "pr.rampageproxies.com:8888"
    proxy_username = "xdsmbKbB-cc-ch-pool-rampagecore"
    proxy_password = "FZeZSSFc"

    class SupabaseStorage:
        def __init__(self):
            self.supabase_url = os.environ.get("SUPABASE_URL")
            self.supabase_key = os.environ.get("SUPABASE_KEY")
            self.client = create_client(self.supabase_url, self.supabase_key)
            self.bucket_name = "ubs"
            
            # Create bucket if it doesn't exist
            try:
                self.client.storage.get_bucket(self.bucket_name)
            except Exception as e:
                self.client.storage.create_bucket(self.bucket_name)
        
        def upload_file(self, file_path, file_name=None):
            """Upload a file to Supabase Storage"""
            if file_name is None:
                file_name = os.path.basename(file_path)
            
            with open(file_path, "rb") as f:
                file_data = f.read()
                
            return self.upload_binary(file_data, file_name)
        
        def upload_binary(self, binary_data, file_name):
            """Upload binary data to Supabase Storage"""
            # Generate a unique filename to avoid collisions
            unique_filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_name}"
            
            # Upload to Supabase Storage
            self.client.storage.from_(self.bucket_name).upload(
                path=unique_filename,
                file=binary_data,
                file_options={"content-type": "application/octet-stream"}
            )
            
            # Get public URL
            file_url = self.client.storage.from_(self.bucket_name).get_public_url(unique_filename)
            return file_url
        
        def save_json_data(self, data, file_name):
            """Save JSON data to Supabase Storage"""
            json_str = json.dumps(data, indent=2)
            return self.upload_binary(json_str.encode('utf-8'), file_name)

    class MarketTypeValidator:
        """Validates if a security is traded on a regulated market or growth market"""
        
        def __init__(self, storage_manager):
            self.storage_manager = storage_manager
            # Create temp directory for screenshots if it doesn't exist
            os.makedirs("temp", exist_ok=True)
        
        async def check_market_type(self, isin: str) -> Tuple[bool, str, str, str]:
            """
            Check the market type for a given ISIN
            
            Args:
                isin: The ISIN to check
                
            Returns:
                Tuple containing:
                - is_regulated: True if traded on a regulated market
                - market_type: The identified market type
                - source_url: The URL that was used to get this information
                - evidence_url: URL to the screenshot evidence in Supabase
            """
            # First, determine the country from the ISIN
            country_code = isin[:2]
            
            if country_code == "DE":
                return await self._check_german_market(isin)
            elif country_code == "FR":
                return await self._check_french_market(isin)
            else:
                # For other countries, we'd add similar methods
                return None, f"Unknown market for country {country_code}", None, None
        
        async def _check_german_market(self, isin: str) -> Tuple[bool, str, str, str]:
            """
            Check if a German security is on a regulated market using boerse-frankfurt.de
            """
            url = f"https://www.boerse-frankfurt.de/aktie/{isin}"
            temp_screenshot_path = f"temp/evidence_{isin}_german_market_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(proxy={
                            "server": proxy_server,
                            "username": proxy_username,
                            "password": proxy_password
                        },
                        headless=True  # Set to True for headless operation
                    )
                page = await browser.new_page()
                evidence_url = None

                try:
                    await page.goto(url)
                    await page.wait_for_selector(".widget-table", timeout=10000)
                    
                    # Scroll to the bottom of the page to ensure all content is loaded
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    
                    # Allow some time for any lazy-loaded content to appear
                    await asyncio.sleep(1)
                    
                    # Capture screenshot for evidence
                    await page.screenshot(path=temp_screenshot_path, full_page=True)
                    
                    # Upload screenshot to Supabase
                    evidence_url = self.storage_manager.upload_file(temp_screenshot_path)
                    
                    # Extract all table rows
                    rows = await page.query_selector_all("table.widget-table tr")

                    market_type = "Unknown"
                    for row in rows:
                        cells = await row.query_selector_all("td")
                        if len(cells) == 2:
                            key = (await cells[0].inner_text()).strip().lower()
                            value = (await cells[1].inner_text()).strip().lower()

                            if key == "markt":
                                market_type = value
                                break

                    is_regulated = "regulierter markt" in market_type
                    pretty_market = "Regulated Market" if is_regulated else "Unregulated Market" if market_type else "Unknown Market"
                    page_url = page.url

                    # Clean up the temp file
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)

                    return is_regulated, pretty_market, page_url, evidence_url

                except Exception as e:
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                    return None, f"Error checking market: {str(e)}", url, evidence_url

                finally:
                    await browser.close()
        
        async def _check_french_market(self, isin: str) -> Tuple[bool, str, str, str]:
            """Check if a French security is on a regulated market (via Euronext Paris)."""
            url = f"https://live.euronext.com/en/product/equities/{isin}-XPAR/market-information"
            temp_screenshot_path = f"temp/evidence_{isin}_french_market_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                evidence_url = None
                
                try:
                    await page.goto(url)
                    await page.wait_for_selector("div#fs_info_block table", timeout=15000)
                    
                    # Scroll to the bottom of the page to ensure all content is loaded
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    
                    # Allow some time for any lazy-loaded content to appear
                    await asyncio.sleep(1)
                    
                    # Capture screenshot for evidence
                    await page.screenshot(path=temp_screenshot_path, full_page=True)
                    
                    # Upload screenshot to Supabase
                    evidence_url = self.storage_manager.upload_file(temp_screenshot_path)

                    # Get all rows in the General Information table
                    rows = await page.query_selector_all("div#fs_info_block table tr")
                    for row in rows:
                        cells = await row.query_selector_all("td")
                        if len(cells) >= 2:
                            key = (await cells[0].inner_text()).strip()
                            value = (await cells[1].inner_text()).strip()
                            if key == "Market":
                                is_regulated = value.strip().lower() == "euronext paris"
                                market_type = "Regulated Market" if is_regulated else "Unregulated Market"
                                
                                # Clean up the temp file
                                if os.path.exists(temp_screenshot_path):
                                    os.remove(temp_screenshot_path)
                                    
                                return is_regulated, market_type, url, evidence_url
                                
                    # Clean up the temp file
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                        
                    return None, "Market info not found", url, evidence_url
                    
                except Exception as e:
                    # Clean up the temp file if it exists
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                    return None, f"Error checking market: {str(e)}", url, evidence_url
                    
                finally:
                    await browser.close()

    class OutstandingSharesValidator:
        """Validates the outstanding shares for Swiss companies"""
        
        def __init__(self, storage_manager):
            self.storage_manager = storage_manager
            # Create temp directory for screenshots if it doesn't exist
            os.makedirs("temp", exist_ok=True)
            
        async def verify_outstanding_shares(self, company_name: str, expected_shares: int) -> Tuple[bool, int, str, str]:
            """
            Verify the outstanding shares for a Swiss company
            
            Args:
                company_name: The name of the company to check
                expected_shares: The expected number of outstanding shares
                
            Returns:
                Tuple containing:
                - is_matched: True if the outstanding shares match the expected value
                - actual_shares: The actual outstanding shares found
                - source_url: The URL used to obtain this information
                - evidence_url: URL to the screenshot evidence in Supabase
            """
            proxy_server = "pr.rampageproxies.com:8888"
            proxy_username = "xdsmbKbB-cc-ch-pool-rampagecore"
            proxy_password = "FZeZSSFc"
            # Zefix search URL
            zefix_url = "https://www.zefix.ch/en/search/entity/list/firm/1184151"
            temp_screenshot_path = f"temp/evidence_{company_name.replace(' ', '_')}_shares_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--window-size=1920,1080', '--disable-dev-shm-usage']
                )
                
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                )
                
                page = await context.new_page()
                evidence_url = None
                actual_shares = None
                
                try:
                    await page.goto(zefix_url)
                    
                    # Wait for page to load completely
                    await page.wait_for_load_state("networkidle")
                    
                    # Enter company name in the search field
                    search_input = page.locator('input[formcontrolname="mainSearch"]').first
                    await search_input.fill(company_name)
                    
                    # Click the search button
                    search_button = page.locator('button span.mdc-button__label:has-text("search")').first
                    await search_button.click()
                    
                    # Wait for search results
                    await page.wait_for_load_state("networkidle")
                    
                    # Initialize variables for our target URL and clean UID
                    target_url = None
                    uid_clean = None
                    
                    # First try to find UID directly
                    uid_selector = 'table.company-info tr th:has-text("UID") + td a'
                    
                    # Try to locate the UID element
                    uid_found = False
                    try:
                        await page.wait_for_selector(uid_selector, state='visible', timeout=30000)
                        uid_found = True
                    except Exception as e:
                        print(f"UID element not found directly: {e}")
                    
                    if uid_found:
                        # Extract UID from the company info table
                        uid_element = page.locator(uid_selector).first
                        
                        if uid_element:
                            uid_text = await uid_element.inner_text()
                            # Extract the UID (format: CHE-XXX.XXX.XXX) and clean it
                            uid_match = re.search(r'(CHE-[0-9]{3}\.[0-9]{3}\.[0-9]{3})', uid_text)
                            if uid_match:
                                uid_clean = uid_match.group(1)
                                
                                # Generate target URL with the cleaned UID
                                target_url = f"https://zh.chregister.ch/cr-portal/auszug/auszug.xhtml?uid={uid_clean}"
                    
                    # If UID was not found or could not be extracted, try the alternative approach with the table
                    if not target_url:
                        # Look for the cantonal excerpt button in the search results table
                        cantonal_excerpt_button = page.locator('a.ob-button:has-text("cantonal excerpt")').first
                        
                        if cantonal_excerpt_button:
                            # Get the href attribute which contains the target URL
                            target_url = await cantonal_excerpt_button.get_attribute("href")
                            
                    
                    # If we still don't have a target URL, we can't proceed
                    if not target_url:
                        print("Could not find UID or cantonal excerpt link in search results")
                        return False, None, zefix_url, None

                    await browser.close()
            
                    # Now launch a new browser with proxy for accessing the target URL
                    # browser = await p.chromium.launch(
                    #     proxy={
                    #         "server": proxy_server,
                    #         "username": proxy_username,
                    #         "password": proxy_password
                    #     },
                    #     headless=False  # Set to True for headless operation
                    # )
                    browserless_api_key = "2SImgKoOPRBT1h75fe37ca22e1308e6ec2325597c700924cf"
                    browserless_url = f"wss://chrome.browserless.io?token={browserless_api_key}"
                    browser = await p.chromium.connect_over_cdp(browserless_url)
                    page = await browser.new_page()

                    # Navigate to the target URL
                    await page.goto(target_url)
                    
                    # Wait for page to load completely
                    await page.wait_for_load_state("networkidle")
                    
                    # Take a screenshot for evidence
                    await page.screenshot(path=temp_screenshot_path, full_page=True)
                    
                    # Upload screenshot to Supabase
                    evidence_url = self.storage_manager.upload_file(temp_screenshot_path)
                    
                    # Check if the table with "Denomination of shares" exists
                    has_denomination_column = await page.locator('th:has-text("Denomination of shares")').count() > 0
                    
                    if has_denomination_column:
                        # Get all non-strikethrough denomination values
                        denomination_elements = await page.locator('tr.evenRowHideAndSeek td:nth-child(5) span span:not(.strike)').all()
                        
                        # If not found, try the alternative selector
                        if not denomination_elements:
                            denomination_elements = await page.locator('table tr:last-child td:nth-child(5) span span:not(.strike)').all()
                        
                        # If still not found, try a more general selector
                        if not denomination_elements:
                            denomination_elements = await page.locator('table td:has-text("\'") span:not(.strike)').all()
                        
                        # Get text from all elements
                        denomination_texts = []
                        for element in denomination_elements:
                            text = await element.inner_text()
                            denomination_texts.append(text)
                        
                        # Extract numbers from all texts and sum them up
                        total_denomination = 0
                        for text in denomination_texts:
                            # Extract numbers using regex - looking for patterns like 1'240'835 or 1'655'000
                            match = re.search(r"(\d[\d']*)", text)
                            if match:
                                # Get the number and remove apostrophes
                                number_str = match.group(1).replace("'", "")
                                try:
                                    number = int(number_str)
                                    total_denomination += number
                                except ValueError:
                                    print(f"Could not convert {number_str} to integer")
                        
                        if total_denomination > 0:
                            actual_shares = total_denomination
                    
                    # Clean up the temp file
                    # if os.path.exists(temp_screenshot_path):
                    #     os.remove(temp_screenshot_path)
                    
                    # Compare with expected shares
                    is_matched = False
                    if actual_shares is not None:
                        is_matched = (actual_shares == expected_shares)
                    
                    return is_matched, actual_shares, target_url, evidence_url
                    
                except Exception as e:
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                    return False, None, zefix_url, evidence_url
                    
                finally:
                    await browser.close()

    # Process the alert
    try:
        # Initialize storage manager
        storage_manager = SupabaseStorage()
        
        # Generate a unique alert ID
        alert_id = f"MANUAL_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Check if it's a Swiss company by the ISIN code (starts with 'CH')
        is_swiss = isin.startswith('CH')
        
        # Verification result object
        verification = None
        verification_type = None
        
        if is_swiss:
            # For Swiss companies, verify outstanding shares
            if outstanding_shares is not None:
                validator = OutstandingSharesValidator(storage_manager)
                is_matched, actual_shares, source_url, evidence_url = await validator.verify_outstanding_shares(company_name, outstanding_shares)
                
                verification = {
                    "alert_id": alert_id,
                    "isin": isin,
                    "company_name": company_name,
                    "is_matched": is_matched,
                    "expected_shares": outstanding_shares,
                    "actual_shares": actual_shares,
                    "source_url": source_url,
                    "evidence_url": evidence_url,
                    "verification_timestamp": datetime.datetime.now().isoformat()
                }
                verification_type = "outstanding_shares"
            else:
                return f"Error: Outstanding shares must be provided for Swiss companies (ISIN: {isin})"
        else:
            # For non-Swiss companies, verify market type
            validator = MarketTypeValidator(storage_manager)
            is_regulated, market_type, source_url, evidence_url = await validator.check_market_type(isin)
            
            verification = {
                "alert_id": alert_id,
                "isin": isin,
                "company_name": company_name,
                "is_regulated": is_regulated,
                "market_type": market_type,
                "source_url": source_url,
                "evidence_url": evidence_url,
                "verification_timestamp": datetime.datetime.now().isoformat()
            }
            verification_type = "market_type"
        
        # Decision making
        if is_swiss:
            # For Swiss companies, use shares matching
            is_matched = verification.get("is_matched")
            expected_shares = verification.get("expected_shares")
            actual_shares = verification.get("actual_shares")
            
            if is_matched is None or actual_shares is None:
                decision = "Inconclusive"
                justification = "Could not determine outstanding shares"
            elif is_matched:
                decision = "True Positive"
                justification = f"Outstanding shares match: Expected={expected_shares}, Actual={actual_shares}"
            else:
                decision = "False Positive"
                justification = f"Outstanding shares mismatch: Expected={expected_shares}, Actual={actual_shares}"
        else:
            # For non-Swiss companies, use market type
            is_regulated = verification.get("is_regulated")
            
            if is_regulated is None:
                decision = "Inconclusive"
                justification = "Could not determine market type"
            elif is_regulated:
                decision = "True Positive"
                justification = f"Security is traded on a regulated market: {verification.get('market_type')}"
            else:
                decision = "False Positive"
                justification = f"Security is traded on an unregulated market: {verification.get('market_type')}"
        
        # Final processing
        result = {
            "alert_id": alert_id,
            "isin": isin,
            "company_name": company_name,
            "verification_type": verification_type,
            "decision": decision,
            "justification": justification,
            "evidence_url": verification.get("evidence_url"),
            "source_url": verification.get("source_url"),
        }
        
        
        # Return a human-readable summary
        return f"""
Individual alert processing completed successfully:

Alert Details:
- ISIN: {isin}
- Company: {company_name}

Verification Results:
- Decision: {decision}
- Justification: {justification}
{"- Expected Shares: " + str(outstanding_shares) if is_swiss else ""}
{"- Actual Shares: " + str(actual_shares) if is_swiss and actual_shares is not None else ""}
{"- Market Type: " + verification.get("market_type") if not is_swiss else ""}

Evidence:
- Source URL: {verification.get("source_url")}
- Evidence Screenshot: {verification.get("evidence_url")}
"""
    except Exception as e:
        return f"Error processing individual alert: {str(e)}"

async def process_group_alert(csv_url: str) -> str:
    """
    Process alerts from the CSV file.
    
    Args:
        csv_url: URL or path to the CSV file
        
    Returns:
        Processing results summary
    """
    from playwright.async_api import async_playwright
    from io import BytesIO
    import requests
    import datetime
    import pandas as pd
    from typing import Tuple
    from supabase import create_client
    import json
    import os
    import re

    proxy_server = "pr.rampageproxies.com:8888"
    proxy_username = "xdsmbKbB-cc-ch-pool-rampagecore"
    proxy_password = "FZeZSSFc"

    class SupabaseStorage:
        def __init__(self):
            self.supabase_url = os.environ.get("SUPABASE_URL")
            self.supabase_key = os.environ.get("SUPABASE_KEY")
            self.client = create_client(self.supabase_url, self.supabase_key)
            self.bucket_name = "ubs"
            
            # Create bucket if it doesn't exist
            try:
                self.client.storage.get_bucket(self.bucket_name)
            except Exception as e:
                self.client.storage.create_bucket(self.bucket_name)
        
        def upload_file(self, file_path, file_name=None):
            """Upload a file to Supabase Storage"""
            if file_name is None:
                file_name = os.path.basename(file_path)
            
            with open(file_path, "rb") as f:
                file_data = f.read()
                
            return self.upload_binary(file_data, file_name)
        
        def upload_binary(self, binary_data, file_name):
            """Upload binary data to Supabase Storage"""
            # Generate a unique filename to avoid collisions
            unique_filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_name}"
            
            # Upload to Supabase Storage
            self.client.storage.from_(self.bucket_name).upload(
                path=unique_filename,
                file=binary_data,
                file_options={"content-type": "application/octet-stream"}
            )
            
            # Get public URL
            file_url = self.client.storage.from_(self.bucket_name).get_public_url(unique_filename)
            return file_url
        
        def save_json_data(self, data, file_name):
            """Save JSON data to Supabase Storage"""
            json_str = json.dumps(data, indent=2)
            return self.upload_binary(json_str.encode('utf-8'), file_name)

    class MarketTypeValidator:
        """Validates if a security is traded on a regulated market or growth market"""
        
        def __init__(self, storage_manager):
            self.storage_manager = storage_manager
            # Create temp directory for screenshots if it doesn't exist
            os.makedirs("temp", exist_ok=True)
        
        async def check_market_type(self, isin: str) -> Tuple[bool, str, str, str]:
            """
            Check the market type for a given ISIN
            
            Args:
                isin: The ISIN to check
                
            Returns:
                Tuple containing:
                - is_regulated: True if traded on a regulated market
                - market_type: The identified market type
                - source_url: The URL that was used to get this information
                - evidence_url: URL to the screenshot evidence in Supabase
            """
            # First, determine the country from the ISIN
            country_code = isin[:2]
            
            if country_code == "DE":
                return await self._check_german_market(isin)
            elif country_code == "FR":
                return await self._check_french_market(isin)
            else:
                # For other countries, we'd add similar methods
                return None, f"Unknown market for country {country_code}", None, None
        
        async def _check_german_market(self, isin: str) -> Tuple[bool, str, str, str]:
            """
            Check if a German security is on a regulated market using boerse-frankfurt.de
            """
            url = f"https://www.boerse-frankfurt.de/aktie/{isin}"
            temp_screenshot_path = f"temp/evidence_{isin}_german_market_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(proxy={
                            "server": proxy_server,
                            "username": proxy_username,
                            "password": proxy_password
                        },
                        headless=True  # Set to True for headless operation
                    )
                page = await browser.new_page()
                evidence_url = None

                try:
                    await page.goto(url)
                    await page.wait_for_selector(".widget-table", timeout=10000)
                    
                    # Scroll to the bottom of the page to ensure all content is loaded
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    
                    # Allow some time for any lazy-loaded content to appear
                    await asyncio.sleep(1)
                    
                    # Capture screenshot for evidence
                    await page.screenshot(path=temp_screenshot_path, full_page=True)
                    
                    # Upload screenshot to Supabase
                    evidence_url = self.storage_manager.upload_file(temp_screenshot_path)
                    
                    # Extract all table rows
                    rows = await page.query_selector_all("table.widget-table tr")

                    market_type = "Unknown"
                    for row in rows:
                        cells = await row.query_selector_all("td")
                        if len(cells) == 2:
                            key = (await cells[0].inner_text()).strip().lower()
                            value = (await cells[1].inner_text()).strip().lower()

                            if key == "markt":
                                market_type = value
                                break

                    is_regulated = "regulierter markt" in market_type
                    pretty_market = "Regulated Market" if is_regulated else "Unregulated Market" if market_type else "Unknown Market"
                    page_url = page.url

                    # Clean up the temp file
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)

                    return is_regulated, pretty_market, page_url, evidence_url

                except Exception as e:
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                    return None, f"Error checking market: {str(e)}", url, evidence_url

                finally:
                    await browser.close()
        
        async def _check_french_market(self, isin: str) -> Tuple[bool, str, str, str]:
            """Check if a French security is on a regulated market (via Euronext Paris)."""
            url = f"https://live.euronext.com/en/product/equities/{isin}-XPAR/market-information"
            temp_screenshot_path = f"temp/evidence_{isin}_french_market_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                evidence_url = None
                
                try:
                    await page.goto(url)
                    await page.wait_for_selector("div#fs_info_block table", timeout=15000)
                    
                    # Scroll to the bottom of the page to ensure all content is loaded
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    
                    # Allow some time for any lazy-loaded content to appear
                    await asyncio.sleep(1)
                    
                    # Capture screenshot for evidence
                    await page.screenshot(path=temp_screenshot_path, full_page=True)
                    
                    # Upload screenshot to Supabase
                    evidence_url = self.storage_manager.upload_file(temp_screenshot_path)

                    # Get all rows in the General Information table
                    rows = await page.query_selector_all("div#fs_info_block table tr")
                    for row in rows:
                        cells = await row.query_selector_all("td")
                        if len(cells) >= 2:
                            key = (await cells[0].inner_text()).strip()
                            value = (await cells[1].inner_text()).strip()
                            if key == "Market":
                                is_regulated = value.strip().lower() == "euronext paris"
                                market_type = "Regulated Market" if is_regulated else "Unregulated Market"
                                
                                # Clean up the temp file
                                if os.path.exists(temp_screenshot_path):
                                    os.remove(temp_screenshot_path)
                                    
                                return is_regulated, market_type, url, evidence_url
                                
                    # Clean up the temp file
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                        
                    return None, "Market info not found", url, evidence_url
                    
                except Exception as e:
                    # Clean up the temp file if it exists
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                    return None, f"Error checking market: {str(e)}", url, evidence_url
                    
                finally:
                    await browser.close()

    class OutstandingSharesValidator:
        """Validates the outstanding shares for Swiss companies"""
        
        def __init__(self, storage_manager):
            self.storage_manager = storage_manager
            # Create temp directory for screenshots if it doesn't exist
            os.makedirs("temp", exist_ok=True)
            
        async def verify_outstanding_shares(self, company_name: str, expected_shares: int) -> Tuple[bool, int, str, str]:
            """
            Verify the outstanding shares for a Swiss company
            
            Args:
                company_name: The name of the company to check
                expected_shares: The expected number of outstanding shares
                
            Returns:
                Tuple containing:
                - is_matched: True if the outstanding shares match the expected value
                - actual_shares: The actual outstanding shares found
                - source_url: The URL used to obtain this information
                - evidence_url: URL to the screenshot evidence in Supabase
            """
            proxy_server = "pr.rampageproxies.com:8888"
            proxy_username = "xdsmbKbB-cc-ch-pool-rampagecore"
            proxy_password = "FZeZSSFc"
            # Zefix search URL
            zefix_url = "https://www.zefix.ch/en/search/entity/list/firm/1184151"
            temp_screenshot_path = f"temp/evidence_{company_name.replace(' ', '_')}_shares_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--window-size=1920,1080', '--disable-dev-shm-usage']
                )
                
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                )
                
                page = await context.new_page()
                evidence_url = None
                actual_shares = None
                
                try:
                    await page.goto(zefix_url)
                    
                    # Wait for page to load completely
                    await page.wait_for_load_state("networkidle")
                    
                    # Enter company name in the search field
                    search_input = page.locator('input[formcontrolname="mainSearch"]').first
                    await search_input.fill(company_name)
                    
                    # Click the search button
                    search_button = page.locator('button span.mdc-button__label:has-text("search")').first
                    await search_button.click()
                    
                    # Wait for search results
                    await page.wait_for_load_state("networkidle")
                    
                    # Initialize variables for our target URL and clean UID
                    target_url = None
                    uid_clean = None
                    
                    # First try to find UID directly
                    uid_selector = 'table.company-info tr th:has-text("UID") + td a'
                    
                    # Try to locate the UID element
                    uid_found = False
                    try:
                        await page.wait_for_selector(uid_selector, state='visible', timeout=10000)
                        uid_found = True
                    except Exception as e:
                        print(f"UID element not found directly: {e}")
                    
                    if uid_found:
                        # Extract UID from the company info table
                        uid_element = page.locator(uid_selector).first
                        
                        if uid_element:
                            uid_text = await uid_element.inner_text()
                            # Extract the UID (format: CHE-XXX.XXX.XXX) and clean it
                            uid_match = re.search(r'(CHE-[0-9]{3}\.[0-9]{3}\.[0-9]{3})', uid_text)
                            if uid_match:
                                uid_clean = uid_match.group(1)
                                
                                # Generate target URL with the cleaned UID
                                target_url = f"https://zh.chregister.ch/cr-portal/auszug/auszug.xhtml?uid={uid_clean}"
                    
                    # If UID was not found or could not be extracted, try the alternative approach with the table
                    if not target_url:
                        # Look for the cantonal excerpt button in the search results table
                        cantonal_excerpt_button = page.locator('a.ob-button:has-text("cantonal excerpt")').first
                        
                        if cantonal_excerpt_button:
                            # Get the href attribute which contains the target URL
                            target_url = await cantonal_excerpt_button.get_attribute("href")
                            
                    
                    # If we still don't have a target URL, we can't proceed
                    if not target_url:
                        print("Could not find UID or cantonal excerpt link in search results")
                        return False, None, zefix_url, None

                    await browser.close()
            
                    # Now launch a new browser with proxy for accessing the target URL
                    # browser = await p.chromium.launch(
                    #     proxy={
                    #         "server": proxy_server,
                    #         "username": proxy_username,
                    #         "password": proxy_password
                    #     },
                    #     headless=False  # Set to True for headless operation
                    # )
                    browserless_api_key = "2SImgKoOPRBT1h75fe37ca22e1308e6ec2325597c700924cf"
                    browserless_url = f"wss://chrome.browserless.io?token={browserless_api_key}"
                    browser = await p.chromium.connect_over_cdp(browserless_url)
                    page = await browser.new_page()

                    # Navigate to the target URL
                    await page.goto(target_url)
                    
                    # Wait for page to load completely
                    await page.wait_for_load_state("networkidle")
                    
                    # Take a screenshot for evidence
                    await page.screenshot(path=temp_screenshot_path, full_page=True)
                    
                    # Upload screenshot to Supabase
                    evidence_url = self.storage_manager.upload_file(temp_screenshot_path)
                    
                    # Check if the table with "Denomination of shares" exists
                    has_denomination_column = await page.locator('th:has-text("Denomination of shares")').count() > 0
                    
                    if has_denomination_column:
                        # Get all non-strikethrough denomination values
                        denomination_elements = await page.locator('tr.evenRowHideAndSeek td:nth-child(5) span span:not(.strike)').all()
                        
                        # If not found, try the alternative selector
                        if not denomination_elements:
                            denomination_elements = await page.locator('table tr:last-child td:nth-child(5) span span:not(.strike)').all()
                        
                        # If still not found, try a more general selector
                        if not denomination_elements:
                            denomination_elements = await page.locator('table td:has-text("\'") span:not(.strike)').all()
                        
                        # Get text from all elements
                        denomination_texts = []
                        for element in denomination_elements:
                            text = await element.inner_text()
                            denomination_texts.append(text)
                        
                        # Extract numbers from all texts and sum them up
                        total_denomination = 0
                        for text in denomination_texts:
                            # Extract numbers using regex - looking for patterns like 1'240'835 or 1'655'000
                            match = re.search(r"(\d[\d']*)", text)
                            if match:
                                # Get the number and remove apostrophes
                                number_str = match.group(1).replace("'", "")
                                try:
                                    number = int(number_str)
                                    total_denomination += number
                                except ValueError:
                                    print(f"Could not convert {number_str} to integer")
                        
                        if total_denomination > 0:
                            actual_shares = total_denomination
                    
                    # Clean up the temp file
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                    
                    # Compare with expected shares
                    is_matched = False
                    if actual_shares is not None:
                        is_matched = (actual_shares == expected_shares)
                    
                    return is_matched, actual_shares, target_url, evidence_url
                    
                except Exception as e:
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                    return False, None, zefix_url, evidence_url
                    
                finally:
                    await browser.close()

    class AlertProcessingSystem:
        def __init__(self):
            self.results = []
            self.storage_manager = SupabaseStorage()
            
        def load_csv_data(self, csv_url):
            """Load CSV data from URL with robust encoding handling"""
            try:
                # Check if it's a URL or local file
                if csv_url.startswith('http'):
                    # Download the file from URL
                    response = requests.get(csv_url)
                    if response.status_code == 200:
                        # Check if Excel or CSV
                        if csv_url.endswith('.xlsx') or csv_url.endswith('.xls'):
                            return pd.read_excel(BytesIO(response.content))
                        else:
                            # Try different encodings
                            encodings = ['utf-8', 'latin1', 'iso-8859-1', 'cp1252']
                            
                            for encoding in encodings:
                                try:
                                    return pd.read_csv(BytesIO(response.content), encoding=encoding, engine='python')
                                except UnicodeDecodeError:
                                    continue
                            
                            return pd.read_csv(BytesIO(response.content), encoding='latin1', errors='replace', engine='python')
                    else:
                        raise Exception(f"Failed to download file: {response.status_code}")
                else:
                    # Check if Excel or CSV
                    if csv_url.endswith('.xlsx') or csv_url.endswith('.xls'):
                        return pd.read_excel(csv_url)
                    else:
                        # Try different encodings
                        encodings = ['utf-8', 'latin1', 'iso-8859-1', 'cp1252']
                        
                        for encoding in encodings:
                            try:
                                return pd.read_csv(csv_url, encoding=encoding, engine='python')
                            except UnicodeDecodeError:
                                continue
                        
                        return pd.read_csv(csv_url, encoding='latin1', errors='replace', engine='python')
            except Exception as e:
                raise
        
        async def verify_market_type(self, isin, alert_id):
            """Verify market type for a security"""
            validator = MarketTypeValidator(self.storage_manager)
            is_regulated, market_type, source_url, evidence_url = await validator.check_market_type(isin)
            
            # Return verification results
            return {
                "alert_id": alert_id,
                "isin": isin,
                "is_regulated": is_regulated,
                "market_type": market_type,
                "source_url": source_url,
                "evidence_url": evidence_url,
                "verification_timestamp": datetime.datetime.now().isoformat()
            }
            
        async def verify_swiss_shares(self, company_name, expected_shares, alert_id, isin):
            """Verify outstanding shares for a Swiss company"""
            validator = OutstandingSharesValidator(self.storage_manager)
            is_matched, actual_shares, source_url, evidence_url = await validator.verify_outstanding_shares(company_name, expected_shares)
            
            # Return verification results
            return {
                "alert_id": alert_id,
                "isin": isin,
                "company_name": company_name,
                "is_matched": is_matched,
                "expected_shares": expected_shares,
                "actual_shares": actual_shares,
                "source_url": source_url,
                "evidence_url": evidence_url,
                "verification_timestamp": datetime.datetime.now().isoformat()
            }
        
        def make_final_decision(self, verification_result, is_swiss=False):
            """Make final decision based on verification results"""
            if is_swiss:
                # For Swiss companies, use shares matching
                is_matched = verification_result.get("is_matched")
                expected_shares = verification_result.get("expected_shares")
                actual_shares = verification_result.get("actual_shares")
                
                if is_matched is None or actual_shares is None:
                    decision = "Inconclusive"
                    justification = "Could not determine outstanding shares"
                elif is_matched:
                    decision = "True Positive"
                    justification = f"Outstanding shares match: Expected={expected_shares}, Actual={actual_shares}"
                else:
                    decision = "False Positive"
                    justification = f"Outstanding shares mismatch: Expected={expected_shares}, Actual={actual_shares}"
            else:
                # For non-Swiss companies, use market type
                is_regulated = verification_result.get("is_regulated")
                
                if is_regulated is None:
                    decision = "Inconclusive"
                    justification = "Could not determine market type"
                elif is_regulated:
                    decision = "True Positive"
                    justification = f"Security is traded on a regulated market: {verification_result.get('market_type')}"
                else:
                    decision = "False Positive"
                    justification = f"Security is traded on an unregulated market: {verification_result.get('market_type')}"
            
            return {
                "decision": decision,
                "justification": justification,
                "timestamp": datetime.datetime.now().isoformat()
            }
        
        def export_results(self, results):
            """Export processing results to Supabase in a human-readable format"""
            # Create a more human-readable format with the most relevant fields
            readable_results = []
            for result in results:
                readable_result = {
                    "alert_id": result.get("alert_id"),
                    "isin": result.get("isin"),
                    "company_name": result.get("company_name"),
                    "source_url": result.get("source_url", ""),
                    "evidence_url": result.get("evidence_url", ""),
                    "decision": result.get("decision", ""),
                    "justification": result.get("justification", ""),
                    "verification_timestamp": result.get("verification_timestamp", "")
                }
                readable_results.append(readable_result)
            
            # Convert to DataFrame
            df = pd.DataFrame(readable_results)
            
            # Save to CSV in memory
            csv_buffer = BytesIO()
            df.to_csv(csv_buffer, index=False)
            csv_buffer.seek(0)
            
            # Save CSV to Supabase
            results_filename = f"alert_processing_results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            results_url = self.storage_manager.upload_binary(csv_buffer.getvalue(), results_filename)
            
            return {
                "csv_url": results_url,
                "record_count": len(readable_results)
            }

    # Process the alerts
    async def process_alerts(csv_url):
        # Initialize the alert processing system
        aps = AlertProcessingSystem()
        
        # Load data
        data = aps.load_csv_data(csv_url)
        
        # Process each alert
        results = []
        for _, row in data.iterrows():
            alert_id = row['Alert ID']
            isin = row['ISIN']
            company_name = row['Company Name']
            
            # Check if it's a Swiss company by the ISIN code (starts with 'CH')
            is_swiss = isin.startswith('CH')
            
            if is_swiss:
                # For Swiss companies, verify outstanding shares
                if 'Outstanding Shares' in row and pd.notna(row['Outstanding Shares']):
                    expected_shares = int(row['Outstanding Shares'])
                    verification = await aps.verify_swiss_shares(company_name, expected_shares, alert_id, isin)
                else:
                    verification = {
                        "alert_id": alert_id,
                        "isin": isin,
                        "company_name": company_name,
                        "is_matched": None,
                        "expected_shares": None,
                        "actual_shares": None,
                        "source_url": None,
                        "evidence_url": None,
                    }
            else:
                # For non-Swiss companies, verify market type
                verification = await aps.verify_market_type(isin, alert_id)
            
            # Decision making
            decision = aps.make_final_decision(verification, is_swiss=is_swiss)
            
            # Add to results
            if is_swiss:
                result = {
                    "alert_id": alert_id,
                    "isin": isin,
                    "company_name": company_name,
                    "is_matched": verification.get("is_matched"),
                    "expected_shares": verification.get("expected_shares"),
                    "actual_shares": verification.get("actual_shares"),
                    "decision": decision.get("decision"),
                    "justification": decision.get("justification"),
                    "evidence_url": verification.get("evidence_url"),
                    "source_url": verification.get("source_url"),
                    "verification_timestamp": datetime.datetime.now().isoformat()
                }
            else:
                result = {
                    "alert_id": alert_id,
                    "isin": isin,
                    "company_name": company_name,
                    "market_type": verification.get("market_type"),
                    "is_regulated": verification.get("is_regulated"),
                    "decision": decision.get("decision"),
                    "justification": decision.get("justification"),
                    "evidence_url": verification.get("evidence_url"),
                    "source_url": verification.get("source_url"),
                    "verification_timestamp": datetime.datetime.now().isoformat()
                }
            results.append(result)
        
        # Export results
        output_info = aps.export_results(results)
        
        return {
            "completed": True,
            "alerts_processed": len(results),
            "results": results,
            "output_files": output_info
        }

    try:
        processing_results = await process_alerts(csv_url)
        return f"""
    Alert processing completed successfully.
    - Processed {processing_results['alerts_processed']} alerts
    - Results exported to:
    - CSV: {processing_results['output_files']['csv_url']}
    - Detailed evidence and reports saved in Supabase
    """
    except Exception as e:
        return f"Error processing alerts: {str(e)}"

async def main():
    # Set up the OpenAI model
    model_client = OpenAIChatCompletionClient(
        model="gpt-4o-mini",
        api_key=os.environ.get("OPENAI_API_KEY")
    )
    
    # Set up the tools
    tools = [process_group_alert, process_individual_alert]
    
    # Create the agents
    analyst_assistant = AssistantAgent(
        name="AnalystAssistant",
        system_message="""You are a Financial Securities Validation Assistant that helps compliance teams verify market alerts.Always try to introduce yourself.

## Your Expertise
You determine if securities alerts are true positives or false positives by:

1. For non-Swiss securities:
   - Checking if they trade on regulated markets (true positive) vs. unregulated/growth markets (false positive)
   - Using official stock exchange websites to validate market status

2. For Swiss securities: 
   - Verifying if the outstanding shares match expected values
   - Using Swiss company registries to validate share counts

## Your Capabilities
You can process securities in two ways:

1. Individual Verification:
   - Requires: ISIN, company name, and for Swiss companies (ISIN starts with 'CH') only need outstanding shares
   - Use the process_individual_alert tool with these parameters

2. Batch Processing:
   - Process multiple securities from a CSV file
   - Requires a URL or path to a CSV containing Alert ID, ISIN, Company Name, and Outstanding Shares (for Swiss companies)
   - Use the process_group_alert tool with the CSV URL/path

## How You Work
For each verification, you:
1. Capture evidence (screenshots)
2. Document source URLs
3. Make a decision (True Positive, False Positive, or Inconclusive)
4. Provide clear justification for the decision
5. Store all evidence and reports in Supabase

## Interaction Guidelines
- Always get complete information before processing
- For Swiss companies (ISIN starts with 'CH'), verify outstanding shares were provided
- For batch processing, ensure the CSV file is accessible
- Present results clearly showing the decision and evidence
- If you need additional information, ask specific questions

Always confirm you have all required information before processing a request. If any required data is missing, politely ask for it.""",
        model_client=model_client,
        model_client_stream=False,
        tools=tools
    )
    user_proxy = UserProxyAgent("user", input_func=input)
    termination = TextMentionTermination("APPROVE")

    team = RoundRobinGroupChat([analyst_assistant, user_proxy], termination_condition=termination)


    task1= """
    Please help me process the alerts in the CSV file at https://qxspwowpaeydjclbylns.supabase.co/storage/v1/object/public/ubs/inputs/company_isn2_latest_mini.csv.
    """

    stream = team.run_stream(task="hi")

    # Start the conversation
    await Console(
        stream
        )
    await model_client.close()
    # team_config = team.dump_component()  # dump component
    # team_config_json = team_config.model_dump_json()
    # with open("json/team_config.json", "w") as file:
    #     file.write(team_config_json)

if __name__ == "__main__":
    asyncio.run(main())
    # asyncio.run(process_group_alert('https://qxspwowpaeydjclbylns.supabase.co/storage/v1/object/public/ubs/inputs/company_isn2_latest_mini.csv'))