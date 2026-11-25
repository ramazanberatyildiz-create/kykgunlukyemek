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


def fetch_page_menus(session: requests.Session, url: str):
    for attempt in range(4):
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return extract_initial_menus(resp.text), 200
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("Retry-After")
                wait = int(retry_after) if (retry_after and retry_after.isdigit()) else 20 * (attempt + 1)
                print(f"  [BEKLE] HTTP {resp.status_code} ({url}) -> {wait} sn bekleniyor...", flush=True)
                time.sleep(wait)
                continue
            return [], resp.status_code
        except Exception as exc:
            wait = 10 * (attempt + 1)
            print(f"  [HATA] {url}: {exc} -> {wait} sn bekleniyor...", flush=True)
            time.sleep(wait)
    return [], 429


def merge_rows(menus: dict, rows: list, fallback_meal: str):
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


def main():
    os.makedirs("data", exist_ok=True)
    updated_at = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    confirmed_aksam_path = None
    available = []

    for slug, name in CITIES:
        candidate_slugs = SLUG_ALIASES.get(slug, [slug])
        menus = {}
        last_status = None

        for remote_slug in candidate_slugs:
            k_rows, k_status = fetch_page_menus(session, f"{BASE_URL}/{remote_slug}/kahvalti")
            last_status = k_status
            time.sleep(1.0)

            aksam_candidates = [confirmed_aksam_path] if confirmed_aksam_path else ["aksam", "aksam-yemegi"]
            a_rows = []
            for a_path in aksam_candidates:
                rows, a_status = fetch_page_menus(session, f"{BASE_URL}/{remote_slug}/{a_path}")
                last_status = a_status
                time.sleep(1.0)
                if rows:
                    a_rows = rows
                    if not confirmed_aksam_path:
                        confirmed_aksam_path = a_path
                    break

            merge_rows(menus, k_rows, "kahvalti")
            merge_rows(menus, a_rows, "aksam")
            if menus:
                break

        city_file = f"data/{slug}.json"
        if menus:
            available.append(slug)
            k_count = sum(1 for d in menus.values() if "kahvalti" in d)
            a_count = sum(1 for d in menus.values() if "aksam" in d)
            payload = {
                "city": name,
                "slug": slug,
                "updatedAt": updated_at,
                "menus": dict(sorted(menus.items())),
            }
            with open(city_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            print(f"[OK] {name}: {len(menus)} gün (K:{k_count}, A:{a_count})", flush=True)
        elif os.path.exists(city_file):
            available.append(slug)
            print(f"[KORUNDU] {name}: eski veri saklandı (HTTP {last_status})", flush=True)
        else:
            print(f"[BOS] {name} (HTTP {last_status})", flush=True)

    available = sorted(set(available))
    with open("data/index.json", "w", encoding="utf-8") as f:
        json.dump(
            {"updatedAt": updated_at, "count": len(available), "availableSlugs": available},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Tamamlandı: {len(available)} il hazır.", flush=True)


if __name__ == "__main__":
    main()
