import os
import asyncio
import datetime
import logging
from urllib.parse import urlparse
import aiohttp
import re
import base64
from PIL import Image

# Import AutoGen libraries
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.ui import Console

from dotenv import load_dotenv
load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Functions for AutoGen agents
async def load_csv_file(csv_url: str) -> str:
    """
    Load and validate a CSV file containing alert data.
    
    Args:
        csv_url: URL or path to the CSV file
        
    Returns:
        Status message
    """
    try:
        # Just check if we can load the file
        import requests
        if csv_url.startswith('http'):
            response = requests.head(csv_url)
            if response.status_code != 200:
                return f"Error: Could not access file at {csv_url}"
        else:
            if not os.path.exists(csv_url):
                return f"Error: File not found at {csv_url}"
        
        return f"CSV file validated and ready for processing: {csv_url}"
    except Exception as e:
        return f"Error validating CSV file: {str(e)}"

async def run_alert_processing(csv_url: str) -> str:
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
    import logging
    import pandas as pd
    from typing import Tuple, Dict, List
    from supabase import create_client, Client
    import json
    import os

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
                logger.info(f"Creating bucket {self.bucket_name}: {str(e)}")
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
                logger.warning(f"No specific market validation implemented for country {country_code}")
                return None, f"Unknown market for country {country_code}", None, None
        
        async def _check_german_market(self, isin: str) -> Tuple[bool, str, str, str]:
            """
            Check if a German security is on a regulated market using boerse-frankfurt.de
            """
            url = f"https://www.boerse-frankfurt.de/aktie/{isin}"
            temp_screenshot_path = f"temp/evidence_{isin}_german_market_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            async with async_playwright() as p:
                browser = await p.chromium.launch()
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
                    logger.error(f"Error checking German market for {isin}: {e}")
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
                    logger.error(f"Error checking French market for {isin}: {e}")
                    # Clean up the temp file if it exists
                    if os.path.exists(temp_screenshot_path):
                        os.remove(temp_screenshot_path)
                    return None, f"Error checking market: {str(e)}", url, evidence_url
                    
                finally:
                    await browser.close()

    class AlertProcessingSystem:
        def __init__(self):
            self.results = []
            self.storage_manager = SupabaseStorage()
            
        def load_csv_data(self, csv_url):
            """Load CSV data from URL"""
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
                            return pd.read_csv(BytesIO(response.content))
                    else:
                        raise Exception(f"Failed to download file: {response.status_code}")
                else:
                    # Check if Excel or CSV
                    if csv_url.endswith('.xlsx') or csv_url.endswith('.xls'):
                        return pd.read_excel(csv_url)
                    else:
                        return pd.read_csv(csv_url)
            except Exception as e:
                logger.error(f"Error loading CSV data: {e}")
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
        
        def dummy_verify_outstanding_shares(self, isin, company_name):
            """Dummy function for outstanding shares verification"""
            return {
                "isin": isin,
                "company_name": company_name,
                "shares_verified": True,
                "verification_timestamp": datetime.datetime.now().isoformat(),
                "notes": "Dummy verification - this step was skipped as requested"
            }
        
        def make_final_decision(self, market_verification_result):
            """Make final decision based on verification results"""
            is_regulated = market_verification_result.get("is_regulated")
            
            if is_regulated is None:
                decision = "Inconclusive"
                justification = "Could not determine market type"
            elif is_regulated:
                decision = "True Positive"
                justification = f"Security is traded on a regulated market: {market_verification_result.get('market_type')}"
            else:
                decision = "False Positive"
                justification = f"Security is traded on an unregulated market: {market_verification_result.get('market_type')}"
            
            return {
                "decision": decision,
                "justification": justification,
                "timestamp": datetime.datetime.now().isoformat()
            }
        
        def document_alert_processing(self, alert_id, isin, company_name, market_verification, decision):
            """Document alert processing results"""
            documentation = {
                "alert_id": alert_id,
                "isin": isin,
                "company_name": company_name,
                "market_verification": market_verification,
                "decision": decision,
                "documentation_timestamp": datetime.datetime.now().isoformat()
            }
            
            self.results.append(documentation)
            
            # Create a text report and save to Supabase
            report_filename = f"report_{alert_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            report_url = self.storage_manager.save_json_data(documentation, report_filename)
            
            logger.info(f"Report saved to Supabase: {report_url}")
            
            return documentation, report_url
        
        def export_results(self):
            """Export processing results to Supabase in a human-readable format"""
            if self.results:
                # Create a more human-readable format with the most relevant fields
                readable_results = []
                for result in self.results:
                    market_verification = result.get("market_verification", {})
                    decision = result.get("decision", {})
                    
                    readable_result = {
                        "Alert ID": result.get("alert_id"),
                        "ISIN": result.get("isin"),
                        "Company Name": result.get("company_name"),
                        "Market Type": market_verification.get("market_type", "Unknown"),
                        "Is Regulated Market": "Yes" if market_verification.get("is_regulated") else "No" if market_verification.get("is_regulated") is not None else "Unknown",
                        "Decision": decision.get("decision", "Unknown"),
                        "Justification": decision.get("justification", ""),
                        "Evidence URL": market_verification.get("evidence_url", ""),
                        "Source URL": market_verification.get("source_url", ""),
                        "Timestamp": decision.get("timestamp", datetime.datetime.now().isoformat())
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
                
                
                logger.info(f"Human-readable results exported to Supabase: CSV={results_url}")
                return {
                    "csv_url": results_url,
                    "record_count": len(readable_results)
                }
            else:
                logger.warning("No results to export")
                return None

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
            
            logger.info(f"Processing alert {alert_id} for {company_name} (ISIN: {isin})")
            
            # Market type verification
            market_verification = await aps.verify_market_type(isin, alert_id)
            
            # Dummy shares verification (skipped as requested)
            # shares_verification = aps.dummy_verify_outstanding_shares(isin, company_name)
            
            # Decision making
            decision = aps.make_final_decision(market_verification)
            
            # Documentation
            documentation, report_url = aps.document_alert_processing(alert_id, isin, company_name, market_verification, decision)
            
            # Add to results
            result = {
                "alert_id": alert_id,
                "isin": isin,
                "company_name": company_name,
                "market_type": market_verification.get("market_type"),
                "is_regulated": market_verification.get("is_regulated"),
                "decision": decision.get("decision"),
                "justification": decision.get("justification"),
                "evidence_url": market_verification.get("evidence_url"),
                "report_url": report_url
            }
            results.append(result)
            
            # Final processing
            if decision["decision"] == "True Positive":
                logger.info(f"Alert {alert_id}: TRUE POSITIVE - Initiating regulatory reporting process")
                # This would trigger the regulatory reporting process
                # Implement actual reporting process code here
            else:
                logger.info(f"Alert {alert_id}: FALSE POSITIVE or INCONCLUSIVE - Closing alert with documentation")
        
        # Export results
        output_info = aps.export_results()
        
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
        logger.error(f"Error processing alerts: {e}", exc_info=True)
        return f"Error processing alerts: {str(e)}"

async def main():
    # Set up the OpenAI model
    model_client = OpenAIChatCompletionClient(
        model="gpt-4o",
        api_key=os.environ.get("OPENAI_API_KEY")
    )
    
    # Set up the tools
    tools = [load_csv_file, run_alert_processing]
    
    # Create the agents
    analyst_assistant = AssistantAgent(
        name="AnalystAssistant",
        system_message="""You are an expert financial analyst assistant helping with alert processing.
        You will help validate market types for securities and document the verification process.
        You need to analyze alerts, verify market types, create evidence, and make decisions.
        Process and document each step carefully. All data and evidence will be stored in Supabase.
        Your workflow is:
        1. Load the CSV file with alert data containing Alert ID, ISIN (security identifier), and company name
        2. For each alert:
           - Verify the market type by checking stock exchange websites (Euronext or Deutsche Börse)
           - If "regulated market" → true positive
           - If "growth market" (France) or similar non-regulated market (Germany) → false positive
           - Create evidence (screenshots) and save to Supabase
           - Make a decision (true/false positive)
           - Document everything in Supabase
        3. Export the results to Supabase storage""",
        model_client=model_client,
        model_client_stream=True,
        tools=tools
    )
    
    # Start the conversation
    await Console(
        analyst_assistant.run_stream(
            task="""
    Please help me process the alerts in the CSV file at https://qxspwowpaeydjclbylns.supabase.co/storage/v1/object/public/ubs//company_isn2.csv.
    """,
        )
    )
    # team_config = analyst_assistant.dump_component()  # dump component
    # team_config_json = team_config.model_dump_json()
    # with open("team_config.json", "w") as file:
    #     file.write(team_config_json)

if __name__ == "__main__":
    asyncio.run(main())