from typing import Dict, Optional, Tuple
import logging
import aiohttp
from playwright.async_api import async_playwright
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class OutstandingShareValidator:
    """Validates outstanding shares information against commercial registers"""
    
    async def validate_outstanding_shares(self, 
                                   country_code: str, 
                                   company_name: str, 
                                   isin: str,
                                   shares_in_system: int) -> Tuple[bool, int, str]:
        """
        Validate the outstanding shares for a company
        
        Args:
            country_code: Two-letter country code
            company_name: Name of the company
            isin: ISIN of the security
            shares_in_system: Number of outstanding shares in the UBS system
            
        Returns:
            Tuple containing:
            - is_valid: True if the shares match (within tolerance)
            - actual_shares: The number of shares found in the commercial register
            - source_url: The URL that was used to get this information
        """
        if country_code == "DE":
            return await self._check_german_register(company_name, isin, shares_in_system)
        elif country_code == "FR":
            return await self._check_french_register(company_name, isin, shares_in_system)
        else:
            logger.warning(f"No specific share validation implemented for country {country_code}")
            return None, None, None
    
    async def _check_german_register(self, 
                              company_name: str, 
                              isin: str,
                              shares_in_system: int) -> Tuple[bool, int, str]:
        """Check the German commercial register for outstanding shares"""
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            try:
                # Navigate to Unternehmensregister
                await page.goto("https://www.unternehmensregister.de/")
                
                # Search by company name
                await page.fill('input[name="search"]', company_name)
                await page.click('button[type="submit"]')
                
                # Wait for results and navigate to company page
                await page.wait_for_selector(".search-results")
                await page.click(".company-link")
                
                # Look for outstanding shares information
                # This is a simplified example - actual implementation would need careful parsing
                content = await page.content()
                
                # Parse the content to find the outstanding shares information
                soup = BeautifulSoup(content, 'html.parser')
                
                # This is a simplified example - actual implementation would need careful parsing
                # based on the actual structure of the website
                shares_text = soup.find(string=re.compile("Anzahl der Aktien|Grundkapital|ausgegebenen Aktien"))
                
                if shares_text:
                    # Extract the number using regex
                    shares_match = re.search(r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?)', shares_text)
                    if shares_match:
                        shares_str = shares_match.group(1)
                        # Remove thousands separators and convert decimal separator
                        shares_str = shares_str.replace('.', '').replace(',', '.')
                        actual_shares = int(float(shares_str))
                        
                        # Compare with system value (with 5% tolerance)
                        tolerance = 0.05
                        min_valid = shares_in_system * (1 - tolerance)
                        max_valid = shares_in_system * (1 + tolerance)
                        
                        is_valid = min_valid <= actual_shares <= max_valid
                        
                        return is_valid, actual_shares, page.url
                
                return False, None, page.url
                
            except Exception as e:
                logger.error(f"Error checking German register for {company_name}: {e}")
                return None, None, None
            
            finally:
                await browser.close()
    
    async def _check_french_register(self, 
                              company_name: str, 
                              isin: str,
                              shares_in_system: int) -> Tuple[bool, int, str]:
        """Check the French commercial register for outstanding shares"""
        # Similar implementation for the French register
        # In a real implementation, we would use Playwright to navigate to the appropriate
        # French commercial register website
        
        # This is a simplified example
        return await self._generic_register_check(
            "https://www.infogreffe.fr/",
            company_name,
            isin,
            shares_in_system
        )
    
    async def _generic_register_check(self,
                               register_url: str,
                               company_name: str,
                               isin: str,
                               shares_in_system: int) -> Tuple[bool, int, str]:
        """Generic implementation for checking commercial registers"""
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            try:
                await page.goto(register_url)
                
                # Search for the company
                # This is a simplified implementation
                await page.fill('input[name="search"]', company_name)
                await page.click('button[type="submit"]')
                
                # Wait for results
                await page.wait_for_selector(".search-results", timeout=10000)
                
                # Extract and process information about outstanding shares
                # This is highly simplistic - real implementation would require specific
                # parsing logic for each register
                
                content = await page.content()
                # Use regex to find numbers that might represent shares
                shares_matches = re.findall(r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?)\s*(?:shares|actions|Aktien)', content)
                
                if shares_matches:
                    shares_str = shares_matches[0]
                    # Remove thousands separators and convert decimal separator
                    shares_str = shares_str.replace('.', '').replace(',', '.')
                    actual_shares = int(float(shares_str))
                    
                    # Compare with system value (with 5% tolerance)
                    tolerance = 0.05
                    min_valid = shares_in_system * (1 - tolerance)
                    max_valid = shares_in_system * (1 + tolerance)
                    
                    is_valid = min_valid <= actual_shares <= max_valid
                    
                    return is_valid, actual_shares, page.url
                
                return False, None, page.url
                
            except Exception as e:
                logger.error(f"Error checking register at {register_url} for {company_name}: {e}")
                return None, None, None
            
            finally:
                await browser.close()