import concurrent.futures
import json
import os
import re
import time
from datetime import datetime, timezone
import requests

BASE_URL = "https://kykyemekliste.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9",
}

CITIES = [
    ("adana", "Adana"), ("adiyaman", "Adıyaman"), ("afyonkarahisar", "Afyonkarahisar"), ("agri", "Ağrı"),
    ("aksaray", "Aksaray"), ("amasya", "Amasya"), ("ankara", "Ankara"), ("antalya", "Antalya"),
    ("ardahan", "Ardahan"), ("artvin", "Artvin"), ("aydin", "Aydın"), ("balikesir", "Balıkesir"),
    ("bartin", "Bartın"), ("batman", "Batman"), ("bayburt", "Bayburt"), ("bilecik", "Bilecik"),
    ("bingol", "Bingöl"), ("bitlis", "Bitlis"), ("bolu", "Bolu"), ("burdur", "Burdur"),
    ("bursa", "Bursa"), ("canakkale", "Çanakkale"), ("cankiri", "Çankırı"), ("corum", "Çorum"),
    ("denizli", "Denizli"), ("diyarbakir", "Diyarbakır"), ("duzce", "Düzce"), ("edirne", "Edirne"),
    ("elazig", "Elazığ"), ("erzincan", "Erzincan"), ("erzurum", "Erzurum"), ("eskisehir", "Eskişehir"),
    ("gaziantep", "Gaziantep"), ("giresun", "Giresun"), ("gumushane", "Gümüşhane"), ("hakkari", "Hakkari"),
    ("hatay", "Hatay"), ("igdir", "Iğdır"), ("isparta", "Isparta"), ("istanbul", "İstanbul"),
    ("izmir", "İzmir"), ("kahramanmaras", "Kahramanmaraş"), ("karabuk", "Karabük"), ("karaman", "Karaman"),
    ("kars", "Kars"), ("kastamonu", "Kastamonu"), ("kayseri", "Kayseri"), ("kilis", "Kilis"),
    ("kirikkale", "Kırıkkale"), ("kirklareli", "Kırklareli"), ("kirsehir", "Kırşehir"), ("kocaeli", "Kocaeli"),
    ("konya", "Konya"), ("kutahya", "Kütahya"), ("malatya", "Malatya"), ("manisa", "Manisa"),
    ("mardin", "Mardin"), ("mersin", "Mersin"), ("mugla", "Muğla"), ("mus", "Muş"),
    ("nevsehir", "Nevşehir"), ("nigde", "Niğde"), ("ordu", "Ordu"), ("osmaniye", "Osmaniye"),
    ("rize", "Rize"), ("sakarya", "Sakarya"), ("samsun", "Samsun"), ("sanliurfa", "Şanlıurfa"),
    ("siirt", "Siirt"), ("sinop", "Sinop"), ("sirnak", "Şırnak"), ("sivas", "Sivas"),
    ("tekirdag", "Tekirdağ"), ("tokat", "Tokat"), ("trabzon", "Trabzon"), ("tunceli", "Tunceli"),
    ("usak", "Uşak"), ("van", "Van"), ("yalova", "Yalova"), ("yozgat", "Yozgat"), ("zonguldak", "Zonguldak"),
]

SLUG_ALIASES = {
    "afyonkarahisar": ["afyonkarahisar", "afyon"],
    "kahramanmaras": ["kahramanmaras", "maras"],
    "sanliurfa": ["sanliurfa", "urfa"],
    "mersin": ["mersin", "icel"],
}


def extract_initial_menus(html: str) -> list:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*("(?:\\.|[^"\\])*")\]\)', html)
    decoded_parts = []
    for ch in chunks:
        try:
            decoded_parts.append(json.loads(ch))
        except Exception:
            pass
    combined = "".join(decoded_parts)

    decoder = json.JSONDecoder()
    results = []
    for source in (combined, html):
        pos = 0
        while True:
            idx = source.find('"initialMenus":', pos)
            if idx == -1:
                break
            arr_start = source.find("[", idx)
            if arr_start == -1:
                break
            try:
                arr, end_pos = decoder.raw_decode(source, arr_start)
                if isinstance(arr, list) and arr:
                    results.extend(arr)
                pos = end_pos
            except Exception:
                pos = idx + 15
        if results:
            break
    return results


def clean_item(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    s = re.sub(r"\s*/\s*", " / ", s)
    if s.lower() in ("", "-", "null", "none"):
        return ""
    return s


def parse_row_items(row: dict) -> list:
    if isinstance(row.get("items"), list):
        items = [clean_item(x) for x in row["items"]]
        return [x for x in items if x]
    items = []
    for key in ("first", "second", "third", "fourth", "fifth", "sixth", "extra"):
        val = clean_item(row.get(key))
        if val:
            items.append(val)
    return items


def fetch_page_menus(session: requests.Session, url: str) -> list:
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        return extract_initial_menus(resp.text)
    except Exception:
        return []


def scrape_city(slug: str, name: str):
    session = requests.Session()
    candidate_slugs = SLUG_ALIASES.get(slug, [slug])
    menus = {}

    def merge_rows(rows: list, fallback_meal: str):
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_date = str(row.get("date") or "")[:10]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date):
                continue

            mt = row.get("mealType")
            if mt == 0 or str(mt).lower() in ("0", "kahvalti", "sabah"):
                meal_key = "kahvalti"
            elif mt == 1 or str(mt).lower() in ("1", "aksam"):
                meal_key = "aksam"
            else:
                meal_key = fallback_meal

            items = parse_row_items(row)
            if not items:
                continue

            cal = row.get("totalCalories")
            cal_val = int(cal) if isinstance(cal, (int, float)) and cal > 0 else None

            day_entry = menus.setdefault(raw_date, {})
            existing = day_entry.get(meal_key)
            new_score = sum(len(x) for x in items)
            old_score = sum(len(x) for x in existing["items"]) if existing else -1

            if new_score > old_score:
                entry = {"items": items}
                if cal_val:
                    entry["calories"] = cal_val
                day_entry[meal_key] = entry

    for remote_slug in candidate_slugs:
        k_rows = fetch_page_menus(session, f"{BASE_URL}/{remote_slug}/kahvalti")
        time.sleep(0.1)
        a_rows = fetch_page_menus(session, f"{BASE_URL}/{remote_slug}/aksam")
        if not a_rows:
            time.sleep(0.1)
            a_rows = fetch_page_menus(session, f"{BASE_URL}/{remote_slug}/aksam-yemegi")
        if not k_rows and not a_rows:
            time.sleep(0.1)
            default_rows = fetch_page_menus(session, f"{BASE_URL}/{remote_slug}")
            merge_rows(default_rows, "aksam")
        else:
            merge_rows(k_rows, "kahvalti")
            merge_rows(a_rows, "aksam")
        if menus:
            break

    return slug, name, dict(sorted(menus.items()))


def main():
    os.makedirs("data", exist_ok=True)
    updated_at = datetime.now(timezone.utc).isoformat()
    available = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(scrape_city, slug, name) for slug, name in CITIES]
        for fut in concurrent.futures.as_completed(futures):
            slug, name, menus = fut.result()
            if menus:
                available.append(slug)
                payload = {
                    "city": name,
                    "slug": slug,
                    "updatedAt": updated_at,
                    "menus": menus,
                }
                with open(f"data/{slug}.json", "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
                print(f"[OK] {name}: {len(menus)} gün")
            else:
                print(f"[BOS] {name}")

    available.sort()
    with open("data/index.json", "w", encoding="utf-8") as f:
        json.dump(
            {"updatedAt": updated_at, "count": len(available), "availableSlugs": available},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Tamamlandı: {len(available)} il güncellendi.")


if __name__ == "__main__":
    main()
