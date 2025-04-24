import logging
from datetime import datetime
import os
from pathlib import Path
from playwright.async_api import async_playwright
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
import base64

logger = logging.getLogger(__name__)

async def create_webpage_snapshot(url: str, output_path: str):
    """
    Creates a PDF snapshot of a webpage for evidence purposes
    
    Args:
        url: The URL of the webpage to snapshot
        output_path: Path where to save the PDF
    
    Returns:
        Path to the saved PDF
    """
    logger.info(f"Creating webpage snapshot for {url}")
    
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Take a screenshot of the webpage using Playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Navigate to the URL
            await page.goto(url, wait_until="networkidle")
            
            # Take a screenshot
            screenshot_path = f"{output_path}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            
            # Get page title and content for additional context
            title = await page.title()
            
            await browser.close()
        
        # Create a PDF with the screenshot and metadata
        create_pdf_with_evidence(
            title=title,
            url=url,
            screenshot_path=screenshot_path,
            output_path=output_path
        )
        
        # Remove the temporary screenshot
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)
        
        logger.info(f"Successfully created webpage snapshot at {output_path}")
        return output_path
    
    except Exception as e:
        logger.error(f"Error creating webpage snapshot: {e}", exc_info=True)
        raise

def create_pdf_with_evidence(title: str, url: str, screenshot_path: str, output_path: str):
    """
    Creates a PDF with the screenshot and metadata
    
    Args:
        title: The title of the webpage
        url: The URL of the webpage
        screenshot_path: Path to the screenshot
        output_path: Path where to save the PDF
    """
    doc = SimpleDocTemplate(output_path, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Create the content for the PDF
    content = []
    
    # Add title
    content.append(Paragraph(f"Evidence: {title}", styles['Title']))
    content.append(Spacer(1, 12))
    
    # Add metadata
    content.append(Paragraph(f"URL: {url}", styles['Normal']))
    content.append(Paragraph(f"Snapshot taken: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    content.append(Spacer(1, 12))
    
    # Add the screenshot
    if os.path.exists(screenshot_path):
        img = Image(screenshot_path)
        img.drawHeight = 450
        img.drawWidth = 500
        content.append(img)
    
    # Add footer with validation information
    content.append(Spacer(1, 20))
    content.append(Paragraph("This document serves as evidence for UBS Compliance purposes.", styles['Normal']))
    content.append(Paragraph(f"Document ID: {os.path.basename(output_path)}", styles['Normal']))
    
    # Build the PDF
    doc.build(content)
