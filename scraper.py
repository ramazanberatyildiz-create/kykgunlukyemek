import argparse
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

PRIORITY_SLUGS = [
    "istanbul", "ankara", "izmir", "bursa", "antalya", "konya", "adana",
    "eskisehir", "kocaeli", "samsun", "trabzon", "kayseri", "gaziantep",
    "diyarbakir", "erzurum", "mersin", "sakarya", "manisa", "denizli", "balikesir",
]

SLUG_ALIASES = {
    "afyonkarahisar": ["afyonkarahisar", "afyon"],
    "kahramanmaras": ["kahramanmaras", "maras"],
    "sanliurfa": ["sanliurfa", "urfa"],
    "mersin": ["mersin", "icel"],
}


def is_recent(iso_str: str, hours: float = 18.0) -> bool:
    if not iso_str:
        return False
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
        return 0 <= age < hours
    except Exception:
        return False


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
    for attempt in range(2):
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return extract_initial_menus(resp.text), 200
            if resp.status_code in (403, 429):
                return [], resp.status_code
            if resp.status_code >= 500 and attempt == 0:
                time.sleep(5)
                continue
            return [], resp.status_code
        except Exception:
            if attempt == 0:
                time.sleep(5)
                continue
            return [], 0
    return [], 0


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cities", type=int, default=9)
    args = parser.parse_args()

    os.makedirs("data", exist_ok=True)
    updated_at = datetime.now(timezone.utc).isoformat()
    state_file = "data/state.json"

    state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}

    city_map = dict(CITIES)
    ordered_slugs = [s for s in PRIORITY_SLUGS if s in city_map] + [
        s for s, _ in CITIES if s not in PRIORITY_SLUGS
    ]

    pending = []
    for slug in ordered_slugs:
        st = state.get(slug, {})
        city_file = f"data/{slug}.json"
        if is_recent(st.get("checkedAt"), 18.0):
            if st.get("status") == "empty" or os.path.exists(city_file):
                continue
        elif os.path.exists(city_file):
            try:
                with open(city_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("menus") and is_recent(existing.get("updatedAt"), 18.0):
                    state[slug] = {"checkedAt": existing["updatedAt"], "status": "ok"}
                    continue
            except Exception:
                pass
        pending.append((slug, city_map[slug]))

    print(f"Kalan şehir: {len(pending)} | Bu tur hedefi: {min(len(pending), args.max_cities)}", flush=True)

    session = requests.Session()
    processed = 0

    for slug, name in pending[: args.max_cities]:
        candidate_slugs = SLUG_ALIASES.get(slug, [slug])
        menus = {}
        blocked = False

        for remote_slug in candidate_slugs:
            k_rows, k_status = fetch_page_menus(session, f"{BASE_URL}/{remote_slug}/kahvalti")
            if k_status in (403, 429):
                blocked = True
                print(f"[DURDU] {name}: HTTP {k_status} engeli geldi, sonraki tura bırakıldı.", flush=True)
                break
            time.sleep(1.2)

            a_rows, a_status = fetch_page_menus(session, f"{BASE_URL}/{remote_slug}/aksam")
            if a_status in (403, 429):
                blocked = True
                print(f"[DURDU] {name}: HTTP {a_status} engeli geldi, sonraki tura bırakıldı.", flush=True)
                break
            time.sleep(1.2)

            merge_rows(menus, k_rows, "kahvalti")
            merge_rows(menus, a_rows, "aksam")
            if menus:
                break

        if blocked:
            break

        processed += 1
        city_file = f"data/{slug}.json"
        if menus:
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
            state[slug] = {"checkedAt": updated_at, "status": "ok"}
            print(f"[OK] {name}: {len(menus)} gün (K:{k_count}, A:{a_count})", flush=True)
        else:
            state[slug] = {"checkedAt": updated_at, "status": "empty"}
            print(f"[BOS] {name}: kaynak sitede menü yok", flush=True)

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    available = sorted(slug for slug, _ in CITIES if os.path.exists(f"data/{slug}.json"))
    with open("data/index.json", "w", encoding="utf-8") as f:
        json.dump(
            {"updatedAt": updated_at, "count": len(available), "availableSlugs": available},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Tur bitti ({processed} şehir işlendi). Toplam hazır il: {len(available)}", flush=True)


if __name__ == "__main__":
    main()
