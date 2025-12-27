#!/usr/bin/env python3
"""
StreetEasy Apartment Finder for Crown Heights
Scrapes listings matching your criteria and sends email alerts for new apartments.
"""

import os
import json
import sqlite3
import smtplib
import re
import time
import random
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# =============================================================================
# CONFIGURATION - Customize your search here!
# =============================================================================

SEARCH_CONFIG = {
    "name": "Crown Heights 2BR+ near Franklin Ave",
    "neighborhoods": ["crown-heights"],
    "min_beds": 2,
    "max_beds": 4,  # Include 2, 3, 4 BR
    "min_baths": 1,
    "max_price": 4500,  # Net effective rent
    "preferred_features": ["laundry", "washer", "dryer", "w/d", "in-unit"],  # Nice to have
}

# Target location for distance calculation (Franklin Ave 2/3/4/5 station)
TARGET_LOCATION = {
    "name": "Franklin Ave Station (2/3/4/5)",
    "lat": 40.6709,
    "lon": -73.9583,
    "max_distance_blocks": 10,  # Roughly 10 blocks = 0.5 miles
}

# Build search URLs
BASE_URLS = [
    # 2 bedrooms under $4500
    "https://streeteasy.com/for-rent/crown-heights/price:-4500%7Cbeds:2",
    # 3 bedrooms under $4500 (might find deals!)
    "https://streeteasy.com/for-rent/crown-heights/price:-4500%7Cbeds:3",
    # Also check Prospect Heights (nearby, same subway)
    "https://streeteasy.com/for-rent/prospect-heights/price:-4500%7Cbeds:2",
]

DB_PATH = os.environ.get("DB_PATH", "apartments.db")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")


def init_db():
    """Initialize SQLite database for tracking seen listings."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            address TEXT,
            unit TEXT,
            neighborhood TEXT,
            price INTEGER,
            net_price INTEGER,
            beds INTEGER,
            baths REAL,
            sqft INTEGER,
            url TEXT,
            has_laundry INTEGER DEFAULT 0,
            is_no_fee INTEGER DEFAULT 0,
            building_name TEXT,
            raw_data TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            listing_id TEXT,
            alert_type TEXT,
            message TEXT
        )
    """)
    conn.commit()
    return conn


def get_driver():
    """Set up headless Chrome driver."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    user_agents = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    options.add_argument(f"--user-agent={random.choice(user_agents)}")
    
    if os.environ.get("GITHUB_ACTIONS"):
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=options)
    else:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    })
    
    return driver


def parse_price(price_str):
    """Extract numeric price from string like '$4,500' or '$4500'."""
    if not price_str:
        return None
    match = re.search(r'[\$]?([\d,]+)', price_str.replace(',', ''))
    if match:
        return int(match.group(1).replace(',', ''))
    return None


def parse_beds_baths(text):
    """Extract beds and baths from text like '2 beds · 1 bath'."""
    beds = None
    baths = None
    
    bed_match = re.search(r'(\d+)\s*bed', text.lower())
    if bed_match:
        beds = int(bed_match.group(1))
    elif 'studio' in text.lower():
        beds = 0
    
    bath_match = re.search(r'([\d.]+)\s*bath', text.lower())
    if bath_match:
        baths = float(bath_match.group(1))
    
    return beds, baths


def check_has_laundry(text):
    """Check if listing mentions in-unit laundry."""
    laundry_keywords = ['washer', 'dryer', 'w/d', 'laundry in unit', 'in-unit laundry', 
                        'washing machine', 'laundry in-unit']
    text_lower = text.lower()
    return any(kw in text_lower for kw in laundry_keywords)


def generate_listing_id(url):
    """Generate unique ID for a listing based on URL."""
    # Extract the listing ID from URL if possible
    match = re.search(r'/(\d+)(?:\?|$)', url)
    if match:
        return f"se_{match.group(1)}"
    # Fallback to hash
    return f"se_{hashlib.md5(url.encode()).hexdigest()[:12]}"


def scrape_listings(driver, url):
    """Scrape apartment listings from a StreetEasy search page."""
    listings = []
    
    try:
        print(f"  Fetching: {url}")
        driver.get(url)
        time.sleep(random.uniform(3, 5))  # Random delay to seem human
        
        # Wait for listings to load
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='listing-card'], .listingCard, .searchCardList--listItem, article"))
            )
        except TimeoutException:
            print("  Timeout waiting for listings, checking page anyway...")
        
        # Try multiple selectors for listing cards
        listing_selectors = [
            "[data-testid='listing-card']",
            ".listingCard",
            ".searchCardList--listItem", 
            "article[class*='listing']",
            "div[class*='ListingCard']",
            ".srp-cards article",
        ]
        
        listing_elements = []
        for selector in listing_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                print(f"  Found {len(elements)} listings with selector: {selector}")
                listing_elements = elements
                break
        
        if not listing_elements:
            # Try to find any links that look like listings
            all_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/rental/'], a[href*='/building/']")
            print(f"  Found {len(all_links)} potential listing links")
        
        for elem in listing_elements:
            try:
                listing = {}
                elem_text = elem.text
                elem_html = elem.get_attribute('innerHTML')
                
                # Get URL
                try:
                    link = elem.find_element(By.CSS_SELECTOR, "a[href*='/rental/'], a[href*='streeteasy.com']")
                    listing['url'] = link.get_attribute('href')
                except NoSuchElementException:
                    links = elem.find_elements(By.TAG_NAME, 'a')
                    for link in links:
                        href = link.get_attribute('href')
                        if href and 'streeteasy.com' in href:
                            listing['url'] = href
                            break
                
                if not listing.get('url'):
                    continue
                
                listing['id'] = generate_listing_id(listing['url'])
                
                # Get address
                address_selectors = [
                    "[data-testid='listing-card-address']",
                    ".listingCard-addressLabel",
                    ".address",
                    "address",
                ]
                for sel in address_selectors:
                    try:
                        addr_elem = elem.find_element(By.CSS_SELECTOR, sel)
                        listing['address'] = addr_elem.text.strip()
                        break
                    except NoSuchElementException:
                        continue
                
                # Get price
                price_selectors = [
                    "[data-testid='listing-card-price']",
                    ".listingCard-price",
                    ".price",
                    "span[class*='price']",
                ]
                for sel in price_selectors:
                    try:
                        price_elem = elem.find_element(By.CSS_SELECTOR, sel)
                        listing['price'] = parse_price(price_elem.text)
                        break
                    except NoSuchElementException:
                        continue
                
                # Fallback: extract price from text
                if not listing.get('price'):
                    price_match = re.search(r'\$[\d,]+', elem_text)
                    if price_match:
                        listing['price'] = parse_price(price_match.group())
                
                # Get beds/baths
                beds, baths = parse_beds_baths(elem_text)
                listing['beds'] = beds
                listing['baths'] = baths
                
                # Check for net effective rent
                net_match = re.search(r'\$([\d,]+)\s*net\s*effective', elem_text.lower())
                if net_match:
                    listing['net_price'] = parse_price(net_match.group(1))
                else:
                    listing['net_price'] = listing.get('price')
                
                # Check for no-fee
                listing['is_no_fee'] = 'no fee' in elem_text.lower()
                
                # Check for laundry
                listing['has_laundry'] = check_has_laundry(elem_text) or check_has_laundry(elem_html)
                
                # Get sqft if available
                sqft_match = re.search(r'([\d,]+)\s*(?:ft²|sq\.?\s*ft|square feet)', elem_text.lower())
                if sqft_match:
                    listing['sqft'] = int(sqft_match.group(1).replace(',', ''))
                
                # Neighborhood from URL or text
                if 'crown-heights' in listing['url'].lower():
                    listing['neighborhood'] = 'Crown Heights'
                elif 'prospect-heights' in listing['url'].lower():
                    listing['neighborhood'] = 'Prospect Heights'
                else:
                    listing['neighborhood'] = 'Brooklyn'
                
                listing['raw_text'] = elem_text[:500]
                
                listings.append(listing)
                
            except Exception as e:
                print(f"  Error parsing listing: {e}")
                continue
        
        # Save debug info
        screenshot_path = f"debug_screenshot_{int(time.time())}.png"
        driver.save_screenshot(screenshot_path)
        print(f"  Screenshot saved: {screenshot_path}")
        
    except Exception as e:
        print(f"  Error scraping {url}: {e}")
    
    return listings


def filter_listings(listings, config):
    """Filter listings based on search criteria."""
    filtered = []
    
    for listing in listings:
        # Check price (use net price if available)
        price = listing.get('net_price') or listing.get('price')
        if price and price > config['max_price']:
            continue
        
        # Check beds
        beds = listing.get('beds')
        if beds is not None:
            if beds < config['min_beds']:
                continue
            if beds > config['max_beds']:
                continue
        
        # Check baths
        baths = listing.get('baths')
        if baths is not None and baths < config['min_baths']:
            continue
        
        filtered.append(listing)
    
    return filtered


def get_new_listings(conn, listings):
    """Find listings we haven't seen before."""
    cursor = conn.cursor()
    new_listings = []
    
    for listing in listings:
        cursor.execute("SELECT id FROM listings WHERE id = ?", (listing['id'],))
        if not cursor.fetchone():
            new_listings.append(listing)
    
    return new_listings


def save_listings(conn, listings):
    """Save listings to database."""
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    
    for listing in listings:
        cursor.execute("""
            INSERT INTO listings (id, first_seen, last_seen, address, neighborhood, 
                                  price, net_price, beds, baths, sqft, url, 
                                  has_laundry, is_no_fee, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET last_seen = ?, price = ?, net_price = ?
        """, (
            listing['id'], now, now,
            listing.get('address'), listing.get('neighborhood'),
            listing.get('price'), listing.get('net_price'),
            listing.get('beds'), listing.get('baths'), listing.get('sqft'),
            listing.get('url'), listing.get('has_laundry', False),
            listing.get('is_no_fee', False), listing.get('raw_text', ''),
            now, listing.get('price'), listing.get('net_price')
        ))
    
    conn.commit()


def format_listing_html(listing):
    """Format a single listing as HTML for email."""
    price_display = f"${listing.get('price', 'N/A'):,}" if listing.get('price') else "Price N/A"
    net_display = ""
    if listing.get('net_price') and listing.get('net_price') != listing.get('price'):
        net_display = f" <span style='color: #2e7d32;'>(${listing['net_price']:,} net)</span>"
    
    beds = listing.get('beds', '?')
    baths = listing.get('baths', '?')
    
    badges = []
    if listing.get('has_laundry'):
        badges.append("🧺 Laundry")
    if listing.get('is_no_fee'):
        badges.append("✨ No Fee")
    
    badge_html = " ".join([f"<span style='background:#e3f2fd;padding:2px 8px;border-radius:4px;font-size:12px;margin-right:5px;'>{b}</span>" for b in badges])
    
    return f"""
    <div style="border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin: 10px 0; background: #fafafa;">
        <div style="font-size: 18px; font-weight: bold; color: #1a237e;">
            {price_display}{net_display}
        </div>
        <div style="font-size: 14px; color: #666; margin: 5px 0;">
            {beds} bed · {baths} bath · {listing.get('neighborhood', 'Brooklyn')}
        </div>
        <div style="font-size: 14px; margin: 5px 0;">
            📍 {listing.get('address', 'Address not available')}
        </div>
        <div style="margin: 10px 0;">{badge_html}</div>
        <a href="{listing.get('url', '#')}" style="display: inline-block; background: #1a237e; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; font-size: 14px;">
            View Listing →
        </a>
    </div>
    """


def send_email_alert(new_listings, all_count):
    """Send email alert for new listings."""
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT]):
        print("Email credentials not configured, skipping email alert")
        return False
    
    if not new_listings:
        print("No new listings to send")
        return False
    
    # Sort by price
    new_listings.sort(key=lambda x: x.get('net_price') or x.get('price') or 999999)
    
    # Highlight listings with laundry
    with_laundry = [l for l in new_listings if l.get('has_laundry')]
    without_laundry = [l for l in new_listings if not l.get('has_laundry')]
    
    subject = f"🏠 {len(new_listings)} New Apartments in Crown Heights!"
    if with_laundry:
        subject += f" ({len(with_laundry)} with laundry!)"
    
    listings_html = ""
    
    if with_laundry:
        listings_html += "<h3 style='color: #2e7d32;'>🧺 With In-Unit Laundry:</h3>"
        for listing in with_laundry:
            listings_html += format_listing_html(listing)
    
    if without_laundry:
        listings_html += "<h3 style='color: #1a237e;'>📍 Other New Listings:</h3>"
        for listing in without_laundry[:10]:  # Limit to prevent huge emails
            listings_html += format_listing_html(listing)
        if len(without_laundry) > 10:
            listings_html += f"<p><em>...and {len(without_laundry) - 10} more</em></p>"
    
    body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px; max-width: 600px;">
        <h2 style="color: #1a237e;">🏠 New Apartments Found!</h2>
        
        <p style="color: #666;">
            Found <strong>{len(new_listings)} new listing(s)</strong> matching your criteria:<br>
            Crown Heights/Prospect Heights · 2+ beds · Under $4,500
        </p>
        
        {listings_html}
        
        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
        
        <p style="color: #999; font-size: 12px;">
            Searched at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}<br>
            Total listings scanned: {all_count}
        </p>
    </body>
    </html>
    """
    
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECIPIENT
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
        
        print(f"✅ Email sent: {subject}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False


def main():
    """Main function to run the apartment search."""
    print("=" * 60)
    print(f"🏠 StreetEasy Apartment Finder")
    print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    print(f"\nSearch: {SEARCH_CONFIG['name']}")
    print(f"Max Price: ${SEARCH_CONFIG['max_price']:,}")
    print(f"Beds: {SEARCH_CONFIG['min_beds']}+")
    print()
    
    conn = init_db()
    driver = get_driver()
    
    all_listings = []
    
    try:
        for url in BASE_URLS:
            listings = scrape_listings(driver, url)
            all_listings.extend(listings)
            time.sleep(random.uniform(2, 4))  # Be nice to the server
        
        print(f"\n📊 Total listings scraped: {len(all_listings)}")
        
        # Remove duplicates by ID
        seen_ids = set()
        unique_listings = []
        for listing in all_listings:
            if listing['id'] not in seen_ids:
                seen_ids.add(listing['id'])
                unique_listings.append(listing)
        
        print(f"📊 Unique listings: {len(unique_listings)}")
        
        # Filter by criteria
        filtered = filter_listings(unique_listings, SEARCH_CONFIG)
        print(f"📊 After filtering: {len(filtered)}")
        
        # Find new ones
        new_listings = get_new_listings(conn, filtered)
        print(f"🆕 New listings: {len(new_listings)}")
        
        # Report on laundry
        with_laundry = [l for l in new_listings if l.get('has_laundry')]
        if with_laundry:
            print(f"🧺 With in-unit laundry: {len(with_laundry)}")
        
        # Save all filtered listings
        save_listings(conn, filtered)
        
        # Send alert for new listings
        if new_listings:
            send_email_alert(new_listings, len(all_listings))
        else:
            print("\n✨ No new listings since last check")
            # Optionally send a "still searching" email once a week
        
    finally:
        driver.quit()
        conn.close()
    
    print("\n" + "=" * 60)
    print("✅ Search complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
