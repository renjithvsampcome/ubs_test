from typing import Dict, Optional, Tuple
import logging
import aiohttp
from playwright.async_api import async_playwright
import re
import asyncio

logger = logging.getLogger(__name__)

class MarketTypeValidator:
    """Validates if a security is traded on a regulated market or growth market"""
    
    async def check_market_type(self, isin: str) -> Tuple[bool, str, str]:
        """
        Check the market type for a given ISIN
        
        Args:
            isin: The ISIN to check
            
        Returns:
            Tuple containing:
            - is_regulated: True if traded on a regulated market
            - market_type: The identified market type
            - source_url: The URL that was used to get this information
        """
        # First, determine the country from the ISIN
        country_code = isin[:2]
        
        if country_code == "DE":
            return await self._check_german_market(isin)
        elif country_code == "FR":
            return await self._check_french_market(isin)
        else:
            # For other countries, we'd add similar methods
            logger.warning(f"No specific market validation implemented for country {country_code}")
            return None, f"Unknown market for country {country_code}", None
    
    async def _check_german_market(self, isin: str) -> Tuple[bool, str, str]:
        """
        Check if a German security is on a regulated market using boerse-frankfurt.de
        """
        url = f"https://www.boerse-frankfurt.de/aktie/{isin}"

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()

            try:
                await page.goto(url)
                await page.wait_for_selector(".widget-table", timeout=10000)

                # Extract all table rows
                rows = await page.query_selector_all("table.widget-table tr")

                market_type = "Unknown"
                for row in rows:
                    cells = await row.query_selector_all("td")
                    if len(cells) == 2:
                        key = (await cells[0].inner_text()).strip().lower()
                        value = (await cells[1].inner_text()).strip().lower()
                        print(key, value)

                        if key == "markt" :
                            market_type = value
                            break

                is_regulated = "regulierter markt" in market_type
                pretty_market = "Regulated Market" if is_regulated else "Unregulated Market" if market_type else "Unknown Market"
                url = page.url

                return is_regulated, pretty_market, url

            except Exception as e:
                logger.error(f"Error checking German market for {isin}: {e}")
                return None, f"Error checking market: {str(e)}", url

            finally:
                await browser.close()
    
    async def _check_french_market(self, isin: str) -> Tuple[bool, str, str]:
        """Check if a French security is on a regulated market (via Euronext Paris)."""
        url = f"https://live.euronext.com/en/product/equities/{isin}-XPAR/market-information"
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            try:
                await page.goto(url)
                await page.wait_for_selector("div#fs_info_block table", timeout=15000)

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
                            return is_regulated, market_type, url
                return None, "Market info not found", url
            except Exception as e:
                logger.error(f"Error checking French market for {isin}: {e}")
                return None, f"Error checking market: {str(e)}", url
            finally:
                await browser.close()

if __name__ == "__main__":
    val = MarketTypeValidator()
    print(asyncio.run(val.check_market_type("FR0014003I41")))