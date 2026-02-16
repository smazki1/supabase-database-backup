import re
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

import requests
import streamlit as st
from bs4 import BeautifulSoup

DB_PATH = "rentals.db"


@dataclass
class Listing:
    url: str
    title: Optional[str]
    price: Optional[str]
    location: Optional[str]
    rooms: Optional[str]
    area_sqm: Optional[str]
    description: Optional[str]
    image_urls: List[str]


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT,
            price TEXT,
            location TEXT,
            rooms TEXT,
            area_sqm TEXT,
            description TEXT,
            image_urls TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_listing(listing: Listing) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO listings (
            url, title, price, location, rooms, area_sqm,
            description, image_urls, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title=excluded.title,
            price=excluded.price,
            location=excluded.location,
            rooms=excluded.rooms,
            area_sqm=excluded.area_sqm,
            description=excluded.description,
            image_urls=excluded.image_urls,
            created_at=excluded.created_at
        """,
        (
            listing.url,
            listing.title,
            listing.price,
            listing.location,
            listing.rooms,
            listing.area_sqm,
            listing.description,
            "\n".join(listing.image_urls),
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_saved_listings() -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM listings ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _pick_first(patterns: List[str], text: str) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def extract_listing(url: str) -> Listing:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    title = (
        soup.find("meta", property="og:title") and soup.find("meta", property="og:title").get("content")
    ) or (soup.title.string.strip() if soup.title and soup.title.string else None)

    description = (
        soup.find("meta", attrs={"name": "description"})
        and soup.find("meta", attrs={"name": "description"}).get("content")
    )

    full_text = soup.get_text(" ", strip=True)
    price = _pick_first([
        r"(?:₪|שח|ש\"ח|ILS)\s*([\d,]+)",
        r"([\d,]+)\s*(?:₪|שח|ש\"ח|ILS)",
        r"price\s*[:\-]?\s*([\d,]+)",
    ], full_text)

    rooms = _pick_first([
        r"(\d+(?:\.\d+)?)\s*חדר(?:ים)?",
        r"(\d+(?:\.\d+)?)\s*rooms?",
    ], full_text)

    area_sqm = _pick_first([
        r"(\d+(?:\.\d+)?)\s*מ\"ר",
        r"(\d+(?:\.\d+)?)\s*sqm",
        r"(\d+(?:\.\d+)?)\s*m2",
    ], full_text)

    location = _pick_first([
        r"(?:כתובת|אזור|עיר)\s*[:\-]?\s*([^\n\r|]+)",
        r"(?:location|address)\s*[:\-]?\s*([^\n\r|]+)",
    ], full_text)

    image_urls = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        absolute = urljoin(url, src)
        if absolute not in image_urls and absolute.startswith("http"):
            image_urls.append(absolute)

    image_urls = image_urls[:12]

    return Listing(
        url=url,
        title=title,
        price=price,
        location=location,
        rooms=rooms,
        area_sqm=area_sqm,
        description=description,
        image_urls=image_urls,
    )


def render_listing(listing: Listing) -> None:
    st.subheader(listing.title or "ללא כותרת")
    data = asdict(listing)
    st.json({k: v for k, v in data.items() if k != "image_urls"}, expanded=False)

    if listing.image_urls:
        st.write("### תמונות שזוהו")
        cols = st.columns(3)
        for idx, image_url in enumerate(listing.image_urls):
            with cols[idx % 3]:
                st.image(image_url, use_container_width=True)
    else:
        st.info("לא נמצאו תמונות בדף הזה.")


def main() -> None:
    st.set_page_config(page_title="מעקב דירות להשכרה", layout="wide")
    init_db()

    st.title("📌 מערכת מעקב דירות להשכרה")
    st.write("הדבק קישור למודעת דירה והמערכת תנסה לחלץ נתונים מרכזיים ותמונות.")

    with st.form("url_form"):
        url = st.text_input("קישור למודעה", placeholder="https://...")
        submitted = st.form_submit_button("חלץ נתונים")

    if submitted and url:
        try:
            with st.spinner("מחלץ נתונים..."):
                listing = extract_listing(url)
                save_listing(listing)
            st.success("המודעה נשמרה בהצלחה")
            render_listing(listing)
        except requests.RequestException as exc:
            st.error(f"נכשלה הגישה לקישור: {exc}")
        except Exception as exc:
            st.error(f"שגיאה לא צפויה: {exc}")

    st.divider()
    st.header("מודעות שנשמרו")

    listings = get_saved_listings()
    if not listings:
        st.caption("עדיין אין מודעות.")
        return

    for item in listings:
        with st.expander(f"{item.get('title') or 'ללא כותרת'} · {item['url']}"):
            st.write(f"מחיר: {item.get('price') or 'לא זוהה'}")
            st.write(f"חדרים: {item.get('rooms') or 'לא זוהה'}")
            st.write(f"שטח: {item.get('area_sqm') or 'לא זוהה'}")
            st.write(f"מיקום: {item.get('location') or 'לא זוהה'}")
            st.write(item.get("description") or "")

            images = (item.get("image_urls") or "").splitlines()
            if images:
                cols = st.columns(4)
                for idx, img in enumerate(images[:8]):
                    with cols[idx % 4]:
                        st.image(img, use_container_width=True)


if __name__ == "__main__":
    main()
