# 🏠 StreetEasy Apartment Finder

Automatically searches StreetEasy for apartments matching your criteria and emails you when new listings appear.

## Your Search Criteria

- **Neighborhoods:** Crown Heights, Prospect Heights
- **Price:** Under $4,500/month (net effective)
- **Bedrooms:** 2+
- **Bathrooms:** 1+
- **Bonus:** Highlights listings with in-unit laundry! 🧺

## Features

- ✅ Checks 3x daily (7 AM, 12 PM, 6 PM EST)
- ✅ Only alerts you about NEW listings
- ✅ Highlights apartments with in-unit laundry
- ✅ Shows net effective rent when available
- ✅ Flags no-fee apartments
- ✅ Tracks all listings in a database
- ✅ 100% free (uses GitHub Actions)

## Quick Setup

### 1. Create a new GitHub repository

Go to github.com → New Repository → Name it something like `apartment-finder`

### 2. Upload these files

Upload all files including the `.github` folder. Make sure the folder structure is:
```
apartment-finder/
├── .github/
│   └── workflows/
│       └── find-apartments.yml
├── scraper.py
├── requirements.txt
└── README.md
```

### 3. Add your email secrets

Go to your repo → Settings → Secrets and variables → Actions → New repository secret

Add these 3 secrets:
| Name | Value |
|------|-------|
| `EMAIL_SENDER` | Your Gmail address |
| `EMAIL_PASSWORD` | Your 16-character Gmail App Password |
| `EMAIL_RECIPIENT` | Where to send alerts |

### 4. Run it!

Go to Actions → Apartment Finder → Run workflow

## Customizing Your Search

Edit `scraper.py` to change your criteria:

```python
SEARCH_CONFIG = {
    "name": "Crown Heights 2BR+ near Franklin Ave",
    "neighborhoods": ["crown-heights"],
    "min_beds": 2,
    "max_beds": 4,
    "min_baths": 1,
    "max_price": 4500,  # Change this!
}

BASE_URLS = [
    # Add or modify search URLs here
    "https://streeteasy.com/for-rent/crown-heights/price:-4500%7Cbeds:2",
]
```

## Check Frequency

The workflow runs 3x daily by default. To change this, edit `.github/workflows/find-apartments.yml`:

```yaml
schedule:
  - cron: '0 12 * * *'  # 7 AM EST
  - cron: '0 17 * * *'  # 12 PM EST  
  - cron: '0 23 * * *'  # 6 PM EST
```

For more frequent checks (e.g., every 4 hours):
```yaml
schedule:
  - cron: '0 */4 * * *'
```

## How It Works

```
┌─────────────────┐
│ GitHub Actions  │ (Scheduled 3x daily)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    Selenium     │ (Headless Chrome)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   StreetEasy    │ (Crown Heights listings)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  SQLite DB      │ (Track seen listings)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  New listings?  │────No────▶ Done
└────────┬────────┘
         │Yes
         ▼
┌─────────────────┐
│  📧 Email You   │
└─────────────────┘
```

## Sample Email

When new apartments are found, you'll get an email like:

> **🏠 3 New Apartments in Crown Heights! (1 with laundry!)**
>
> 🧺 **With In-Unit Laundry:**
> - $4,200 · 2 bed · 1 bath · 123 Eastern Pkwy
>
> 📍 **Other New Listings:**
> - $3,800 · 2 bed · 1 bath · 456 Lincoln Pl
> - $4,100 · 2 bed · 2 bath · 789 Washington Ave

## Troubleshooting

**No emails received:**
- Check Actions tab for errors
- Verify Gmail secrets are correct
- Make sure 2FA is enabled on Gmail

**No listings found:**
- Check debug screenshots in Actions artifacts
- StreetEasy may have changed their site structure
- Try adjusting search URLs

**Want to reset and see all current listings:**
- Delete the `apartment-database` artifact in Actions
- Run the workflow again

## Cost

**$0** - This is completely free using GitHub Actions and Gmail.

---

Good luck finding your new place! 🏠🔑
