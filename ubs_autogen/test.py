import time
import re
import sys
from playwright.sync_api import sync_playwright

def main():
    # Get company name from command line argument or prompt user
    if len(sys.argv) > 1:
        company_name = sys.argv[1]
    else:
        company_name = input("Enter company name to search: ")
    
    # Proxy configuration
    proxy_server = "pr.rampageproxies.com:8888"
    proxy_username = "xdsmbKbB-cc-ch-pool-rampagecore-sessionid-7555168738497399-sesstime-30"
    proxy_password = "FZeZSSFc"
    
    # Zefix search URL
    zefix_url = "https://www.zefix.ch/en/search/entity/list/firm/1184151"
    
    print("Starting Playwright script...")
    
    with sync_playwright() as p:
        # Configure browser without proxy for Zefix search
        browser = p.chromium.launch(headless=False)  # Set to True for headless operation
        
        try:
            # Create a new context and page
            context = browser.new_context()
            page = context.new_page()
            
            # First navigate to Zefix to search for the company
            print(f"Navigating to Zefix: {zefix_url}")
            page.goto(zefix_url)
            
            # Wait for page to load completely
            page.wait_for_load_state("networkidle")
            
            print("Zefix page loaded successfully")
            
            # Enter company name in the search field
            print(f"Searching for company: {company_name}")
            search_input = page.locator('input[formcontrolname="mainSearch"]')
            search_input.fill(company_name)
            
            # Click the search button
            search_button = page.locator('button span.mdc-button__label:has-text("search")').first
            search_button.click()
            
            # Wait for search results
            page.wait_for_load_state("networkidle")
            
            # Initialize variables for our target URL and clean UID
            target_url = None
            uid_clean = None
            
            # First try to find UID directly
            print("Checking for UID element...")
            uid_selector = 'table.company-info tr th:has-text("UID") + td a'
            
            # Try to locate the UID element with a shorter timeout first
            uid_found = False
            try:
                # Wait for the element to be visible with a reasonable timeout
                page.wait_for_selector(uid_selector, state='visible', timeout=10000)
                uid_found = True
            except Exception as e:
                print(f"UID element not found directly: {e}")
                # We'll try the alternative approach below
            
            if uid_found:
                # Extract UID from the company info table
                uid_element = page.locator(uid_selector).first
                
                if uid_element.count() > 0:
                    uid_text = uid_element.inner_text()
                    # Extract the UID (format: CHE-XXX.XXX.XXX) and clean it
                    uid_clean = re.search(r'(CHE-[0-9]{3}\.[0-9]{3}\.[0-9]{3})', uid_text)
                    if uid_clean:
                        uid_clean = uid_clean.group(1)
                        print(f"Found UID: {uid_text}")
                        print(f"Cleaned UID: {uid_clean}")
                        
                        # Generate target URL with the cleaned UID
                        target_url = f"https://zh.chregister.ch/cr-portal/auszug/auszug.xhtml?uid={uid_clean}"
                        print(f"Generated target URL: {target_url}")
            
            # If UID was not found or could not be extracted, try the alternative approach with the table
            if not target_url:
                print("UID not found directly. Looking for cantonal excerpt link in search results table...")
                
                # Look for the cantonal excerpt button in the search results table
                cantonal_excerpt_button = page.locator('a.ob-button:has-text("cantonal excerpt")').first
                
                if cantonal_excerpt_button.count() > 0:
                    print("Found cantonal excerpt button")
                    
                    # Get the href attribute which contains the target URL
                    target_url = cantonal_excerpt_button.get_attribute("href")
                    print(f"Found target URL from cantonal excerpt button: {target_url}")
                    
                    # Also extract UID from the same row for reference
                    # Navigate up to the row and then find the UID cell
                    row = cantonal_excerpt_button.locator("xpath=ancestor::tr")
                    uid_cell = row.locator('td.company-uid a').first
                    
                    if uid_cell.count() > 0:
                        uid_text = uid_cell.inner_text()
                        uid_clean = re.search(r'(CHE-[0-9]{3}\.[0-9]{3}\.[0-9]{3})', uid_text)
                        if uid_clean:
                            uid_clean = uid_clean.group(1)
                            print(f"Found UID from table: {uid_text}")
                            print(f"Cleaned UID: {uid_clean}")
            
            # If we still don't have a target URL, we can't proceed
            if not target_url:
                print("Could not find UID or cantonal excerpt link in search results")
                return
            
            # Close the current browser
            browser.close()
            
            # Now launch a new browser with proxy for accessing the target URL
            proxy_browser = p.chromium.launch(
                proxy={
                    "server": proxy_server,
                    "username": proxy_username,
                    "password": proxy_password
                },
                headless=False  # Set to True for headless operation
            )
            
            # Create a new page with proxy
            proxy_page = proxy_browser.new_page()
            
            print(f"Navigating to target URL with proxy: {target_url}")
            proxy_page.goto(target_url)
            
            # Wait for page to load completely
            proxy_page.wait_for_load_state("networkidle")
            
            print("Target page loaded successfully")
            
            # Check if the table with "Denomination of shares" exists
            has_denomination_column = proxy_page.locator('th:has-text("Denomination of shares")').count() > 0
            
            if has_denomination_column:
                print("Found table with 'Denomination of shares' column")
                
                # Get the first denomination number
                # Get all non-strikethrough denomination values from the last row
                denomination_elements = proxy_page.locator('tr.evenRowHideAndSeek td:nth-child(5) span span:not(.strike)').all()
                
                # If not found, try the alternative selector
                if not denomination_elements:
                    denomination_elements = proxy_page.locator('table tr:last-child td:nth-child(5) span span:not(.strike)').all()
                
                # If still not found, try a more general selector
                if not denomination_elements:
                    denomination_elements = proxy_page.locator('table td:has-text("\'") span:not(.strike)').all()
                
                # Get text from all elements
                denomination_texts = []
                for element in denomination_elements:
                    text = element.inner_text()
                    denomination_texts.append(text)
                    print(f"Found denomination text: {text}")
                
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
                            print(f"Extracted number: {number}")
                            total_denomination += number
                        except ValueError:
                            print(f"Could not convert {number_str} to integer")
                
                if total_denomination > 0:
                    denomination_number = total_denomination
                    print(f"Total denomination sum: {denomination_number}")
                else:
                    print("Could not extract any denomination numbers")
                    denomination_number = None
                
                # Store the result for further use
                if denomination_number is not None:
                    print(f"Successfully extracted denomination number: {denomination_number}")
                    # Here you can add code to use the denomination_number as needed
            else:
                print("Table with 'Denomination of shares' column not found")
            
            # Wait for a shorter time for demonstration purposes
            print("Waiting for 30 seconds...")
            time.sleep(5)
            
            print("Operation completed")
            
        except Exception as e:
            print(f"An error occurred: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            try:
                browser.close()
            except:
                pass
            try:
                if 'proxy_browser' in locals():
                    proxy_browser.close()
            except:
                pass
            print("Browsers closed")

if __name__ == "__main__":
    main()