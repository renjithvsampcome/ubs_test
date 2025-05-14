from playwright.async_api import async_playwright
from io import BytesIO
import requests
import datetime
import logging
import pandas as pd
from typing import Tuple, Dict, List
from supabase import create_client, Client
import json
import os
import asyncio
import re



async def verify_outstanding_shares(company_name: str, expected_shares: int) -> Tuple[bool, int, str, str]:
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
                # browserless_api_key = "2SImgKoOPRBT1h75fe37ca22e1308e6ec2325597c700924cf"
                # browserless_url = f"wss://chrome.browserless.io?token={browserless_api_key}"
                # browser = await p.chromium.connect_over_cdp(browserless_url)
                # page = await browser.new_page()
                evidence_url = None
                actual_shares = None
                
                # try:
                # First navigate to Zefix to search for the company
                await page.goto(zefix_url)
                
                # Wait for page to load completely
                await page.wait_for_load_state("networkidle")
                
                # Enter company name in the search field
                await page.wait_for_selector('input[formcontrolname="mainSearch"]', state='visible', timeout=35000)
                await page.fill('input[formcontrolname="mainSearch"]', company_name)
                
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
                browser = await p.chromium.launch(
                    proxy={
                        "server": proxy_server,
                        "username": proxy_username,
                        "password": proxy_password
                    },
                    headless=False  # Set to True for headless operation
                )
                
                page = await browser.new_page()

                # Navigate to the target URL
                await page.goto(target_url)
                
                # Wait for page to load completely
                await page.wait_for_load_state("networkidle")
                
                # Take a screenshot for evidence
                # await page.screenshot(path=temp_screenshot_path, full_page=True)
                
                # Upload screenshot to Supabase
                # evidence_url = self.storage_manager.upload_file(temp_screenshot_path)
                
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
                    
                # except Exception as e:
                #     if os.path.exists(temp_screenshot_path):
                #         os.remove(temp_screenshot_path)
                #     return False, None, zefix_url, evidence_url
                    
                # finally:
                #     await browser.close()

print(asyncio.run(verify_outstanding_shares("Nestlé AG", 1000000000)))