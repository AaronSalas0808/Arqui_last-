import os
import time
import re
import json
import urllib.parse
import requests
from bs4 import BeautifulSoup
import concurrent.futures

# Encabezados globales para todas las peticiones HTTP
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Referer": "https://www.google.com/",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1"
}

METACRITIC_SCORES_FILE = "metacritic_scores.txt"
HLTB_TIMES_FILE = "hltb_times.txt" 
DEBUG_PLAYSTATION_HTML = False 

def read_games(file_path: str) -> list:
    games = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            games.append(line)
    return games

def get_steam_price(name: str) -> str:
    params = {"term": name, "l": "english", "cc": "US"}
    r = requests.get(
        "https://store.steampowered.com/api/storesearch/",
        params=params,
        headers=HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])
    if not items:
        return "N/A"
    appid = items[0]["id"]
    r2 = requests.get(
        "https://store.steampowered.com/api/appdetails/",
        params={"appids": appid, "cc": "US", "l": "english"},
        headers=HEADERS,
        timeout=10,
    )
    r2.raise_for_status()
    info = r2.json().get(str(appid), {})
    data_info = info.get("data", {})
    if not data_info:
        return "N/A"
    if data_info.get("is_free", False):
        return "Free"
    po = data_info.get("price_overview")
    if not po:
        return "N/A"
    price = po["final"] / 100
    return f"{price:.2f} {po['currency']}"

def get_playstation_price(name: str) -> str:
    search_term_encoded = urllib.parse.quote(name)
    url = f"https://store.playstation.com/en-us/search/{search_term_encoded}"
    session = requests.Session()
    session.headers.update(HEADERS)
    html_content_for_debug = ""
    actual_url = url
    try:
        r = session.get(url, timeout=20, allow_redirects=True)
        actual_url = r.url
        if r.status_code == 404: return "N/A"
        r.raise_for_status()
        html_content_for_debug = r.text
        soup = BeautifulSoup(r.text, "html.parser")
        price_selectors = [
            'span[data-qa$="display-price"]', 'span[data-qa$="finalPrice"]',
            'div[data-qa*="price"] > span', 'span[class*="price"][class*="sales"]',
            'span[class*="price"][class*="original"]', 'span[class*="psw-t-title-m"][class*="psw-m-r-3"]',
            'span.psw-l-line-left', 'div.psw-l-line-left > span.psw-t-title-m',
            'span.price', 'div[class*="ProductPrice"]',
        ]
        price_text_found = None
        for selector in price_selectors:
            price_element = soup.select_one(selector)
            if price_element:
                price_text = price_element.get_text(strip=True)
                if "free" in price_text.lower(): return "Free"
                price_match = re.search(r"\$\s*\d{1,3}(?:,\d{3})*\.\d{2}", price_text)
                if price_match:
                    price_text_found = price_match.group(0).replace(" ", "")
                    return price_text_found
        if not price_text_found:
            body_text = soup.body.get_text(separator=" ", strip=True) if soup.body else ""
            general_price_match = re.search(r"(?<!PS\sPlus\s)(?<!Save\s)\$\s*\d{1,3}(?:,\d{3})*\.\d{2}", body_text)
            if general_price_match:
                price_text_found = general_price_match.group(0).replace(" ", "")
                return price_text_found
            if "free" in body_text.lower() and "add to cart" in body_text.lower(): return "Free"
        if DEBUG_PLAYSTATION_HTML:
            debug_filename = f"playstation_debug_no_price_{name.replace(' ', '_')[:30]}.html"
            with open(debug_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- URL: {url} -->\n<!-- URL Final: {actual_url} -->\n<!-- Juego: {name} -->\n<!-- Precio NO encontrado -->\n")
                df.write(html_content_for_debug)
        return "N/A"
    except requests.exceptions.HTTPError as e:
        if e.response.status_code != 404 and DEBUG_PLAYSTATION_HTML and e.response:
            debug_filename = f"playstation_error_{name.replace(' ', '_')[:30]}_{e.response.status_code}.html"
            with open(debug_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- URL: {url} -->\n<!-- URL Final: {actual_url} -->\n<!-- STATUS: {e.response.status_code} -->\n<!-- Juego: {name} -->\n")
                df.write(e.response.text)
        return "N/A"
    except Exception:
        if DEBUG_PLAYSTATION_HTML and html_content_for_debug:
            debug_filename = f"playstation_exception_{name.replace(' ', '_')[:30]}.html"
            with open(debug_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- URL: {url} -->\n<!-- URL Final: {actual_url} -->\n<!-- EXCEPCIÓN: {type(e).__name__} - {e} -->\n<!-- Juego: {name} -->\n") # type: ignore
                df.write(html_content_for_debug)
        return "N/A"

def get_amazon_price(name: str) -> str:
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set("i18n-prefs", "USD", domain="www.amazon.com")
    search_term = f"{name} PC game"
    url = f"https://www.amazon.com/s?k={urllib.parse.quote(search_term)}"
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
    except requests.exceptions.RequestException: return "N/A"
    soup = BeautifulSoup(r.text, "html.parser")
    results = soup.select('div[data-component-type="s-search-result"]')
    if not results:
        m = re.search(r"\$\s*([0-9,]+(?:\.[0-9]{1,2})?)", soup.get_text())
        if m: return f"${m.group(1).replace(',', '')}"
        return "N/A"
    for item in results:
        title_tag = item.select_one('h2 a.a-link-normal span.a-text-normal')
        if title_tag and name.lower() in title_tag.get_text(strip=True).lower():
            price_tag = item.select_one("span.a-price span.a-offscreen")
            if price_tag:
                price_text = price_tag.get_text(strip=True)
                if price_text.startswith("$"): return price_text.replace(",", "")
            whole = item.select_one("span.a-price-whole")
            frac = item.select_one("span.a-price-fraction")
            if whole:
                text = whole.get_text(strip=True).replace(",", "")
                if frac: text += "." + frac.get_text(strip=True)
                return f"${text}"
            free_download_text = item.find(string=re.compile(r"Free Download|Free", re.I))
            if free_download_text:
                parent_text = free_download_text.parent.get_text(strip=True, separator=" ").lower()
                if "free download" in parent_text or parent_text == "free": return "Free"
    m = re.search(r"\$\s*([0-9,]+(?:\.[0-9]{1,2})?)", soup.get_text())
    if m: return f"${m.group(1).replace(',', '')}"
    return "N/A"

def load_metacritic_scores(input_filename: str) -> dict:
    scores = {}
    if not os.path.exists(input_filename):
        print(f"⚠️ Archivo '{input_filename}' no encontrado. Puntuaciones Metacritic serán 'N/A'.")
        return scores
    with open(input_filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                try: name, score = line.split(":", 1); scores[name.strip()] = score.strip()
                except ValueError: pass
    if scores: print(f"✔ Puntuaciones Metacritic cargadas desde '{input_filename}'")
    return scores

def load_hltb_times(input_filename: str) -> dict:
    hltb_data = {}
    if not os.path.exists(input_filename):
        print(f"⚠️ Archivo de tiempos HLTB '{input_filename}' no encontrado. Tiempos HLTB serán 'No disponible'.")
        return hltb_data
    
    with open(input_filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "—" in line:
                parts = line.split("—", 1)
                if len(parts) == 2:
                    game_name = parts[0].strip()
                    time_str = parts[1].strip()
                    hltb_data[game_name] = time_str
            
    if hltb_data: print(f"✔ Tiempos de HowLongToBeat cargados desde '{input_filename}'")
    return hltb_data

def scrape_game(name: str, all_metacritic_scores: dict, all_hltb_times: dict) -> dict:
    s, ps, a = "N/A", "N/A", "N/A"
    try: s = get_steam_price(name)
    except Exception as e: print(f"⚠️ Error Steam «{name}»: {e}")
    try: ps = get_playstation_price(name)
    except Exception as e: print(f"⚠️ Error PlayStation «{name}»: {e}")
    try: a = get_amazon_price(name)
    except Exception as e: print(f"⚠️ Error Amazon «{name}»: {e}")
    
    m_score = all_metacritic_scores.get(name, "N/A")
    hltb_time = all_hltb_times.get(name, "No disponible")
    
    return {
        "name": name, "steam": s, "playstation": ps, "amazon": a,
        "metacritic": m_score, "hltb": hltb_time
    }

def scrape_all_prices(games: list, all_metacritic_scores: dict, all_hltb_times: dict, max_workers: int = 7) -> list:
    results = []
    if not games: return results
    print(f"ℹ️ Iniciando scraping de precios para {len(games)} juegos (max_workers={max_workers})...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scrape_game, name, all_metacritic_scores, all_hltb_times): name for name in games}
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            name = futures[future]
            try:
                res = future.result()
                print(
                    f"  Precios ({i+1}/{len(games)}): «{name}» → Steam: {res['steam']} | PS: {res['playstation']} | Amazon: {res['amazon']}"
                )
            except Exception as e:
                print(f"⚠️ Excepción mayor en precios «{name}»: {e}")
                res = {
                    "name": name, "steam": "N/A", "playstation": "N/A", "amazon": "N/A",
                    "metacritic": all_metacritic_scores.get(name, "N/A"),
                    "hltb": all_hltb_times.get(name, "No disponible")
                }
            results.append(res)
    return results

def generate_html(results: list, images_path="images.json"):
    try:
        with open(images_path, encoding="utf-8") as f: images = json.load(f)
    except Exception: images = {}
    html = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Game Data Comparator</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-color: #1a1a1a;
      --surface-color: #2c2c2c;
      --primary-text: #e0e0e0;
      --secondary-text: #a0a0a0;
      --border-color: #444;
      --accent-color: #3d8dff;
      --shadow-color: rgba(0, 0, 0, 0.5);
    }
    * { box-sizing: border-box; }
    body {
      font-family: 'Inter', sans-serif;
      margin: 0;
      padding: 20px;
      background-color: var(--bg-color);
      color: var(--primary-text);
    }
    .container { max-width: 1400px; margin: 0 auto; padding: 0 20px; }
    h1 {
      text-align: center;
      font-size: 2.5rem;
      font-weight: 700;
      color: #fff;
      margin-bottom: 30px;
      text-shadow: 0 2px 10px var(--shadow-color);
    }
    .search-container {
      margin-bottom: 30px;
      display: flex;
      justify-content: center;
    }
    #search-input {
      width: 100%;
      max-width: 500px;
      padding: 12px 20px;
      font-size: 1rem;
      border-radius: 50px;
      border: 1px solid var(--border-color);
      background-color: var(--surface-color);
      color: var(--primary-text);
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    #search-input:focus {
      border-color: var(--accent-color);
      box-shadow: 0 0 0 3px rgba(61, 141, 255, 0.3);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 25px;
    }
    .card {
      background: var(--surface-color);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 4px 15px var(--shadow-color);
      cursor: pointer;
      transition: transform 0.2s ease-out, box-shadow 0.2s ease-out;
      display: flex;
      flex-direction: column;
    }
    .card:hover {
      transform: translateY(-8px);
      box-shadow: 0 8px 25px var(--shadow-color), 0 0 15px var(--accent-color);
    }
    .card .img-container {
      width: 100%;
      height: 150px;
      background: #333;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .card .img-container img { width: 100%; height: 100%; object-fit: cover; }
    .card .img-container .placeholder-text { color: var(--secondary-text); font-style: italic; }
    .card .title {
      padding: 15px;
      font-size: 1rem;
      font-weight: 600;
      text-align: center;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      border-top: 1px solid var(--border-color);
    }
    #no-results-message {
        display: none;
        text-align: center;
        font-size: 1.2rem;
        color: var(--secondary-text);
        margin-top: 40px;
    }
    .modal {
      display: none; position: fixed; z-index: 1000; top: 0; left: 0;
      width: 100%; height: 100%;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(5px);
      align-items: center; justify-content: center;
      padding: 20px;
    }
    .modal.open { display: flex; }
    .modal-content {
      background: var(--surface-color);
      border-radius: 12px;
      padding: 30px;
      max-width: 500px;
      width: 100%;
      position: relative;
      box-shadow: 0 10px 30px var(--shadow-color);
      animation: fadeInModal 0.3s ease-out;
      border: 1px solid var(--border-color);
    }
    .modal-content .img-modal-container {
      width: 100%; max-height: 200px;
      display: flex; align-items: center; justify-content: center;
      margin: 0 auto 20px; border-radius: 8px;
      overflow: hidden; background-color: #1a1a1a;
    }
    .modal-content .img-modal-container img { max-width: 100%; max-height: 100%; object-fit: contain; }
    .modal-content h2 { margin: 0 0 20px; font-size: 1.75rem; text-align: center; color: #fff; }
    .modal-content .details p {
      margin: 12px 0; font-size: 1rem; color: var(--secondary-text);
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 12px;
      display: flex; justify-content: space-between; align-items: center;
    }
    .modal-content .details p:last-child { border-bottom: none; }
    .modal-content .details strong { color: var(--primary-text); font-weight: 600; }
    .modal-content .details span { text-align: right; font-weight: 600; }
    .modal-content .details hr { border: none; height: 1px; background-color: var(--border-color); margin: 15px 0; }
    .close {
      position: absolute; top: 15px; right: 20px;
      font-size: 2rem; line-height: 1;
      cursor: pointer; color: var(--secondary-text);
      transition: color 0.2s, transform 0.2s;
    }
    .close:hover { color: #fff; transform: scale(1.1); }
    @keyframes fadeInModal {
      from { opacity: 0; transform: translateY(-30px) scale(0.95); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Game Data Comparator</h1>
    <div class="search-container">
      <input type="search" id="search-input" placeholder="Buscar juego...">
    </div>
    <div class="grid" id="game-grid">
"""
    for r in results:
        img_url = images.get(r["name"], "")
        img_tag_html = f'<img src="{img_url}" alt="{r["name"]}">' if img_url else '<span class="placeholder-text">No Image</span>'
        html += f'''      <div class="card"
           data-title="{r["name"]}"
           data-img="{img_url}"
           data-steam="{r.get("steam", "N/A")}"
           data-playstation="{r.get("playstation", "N/A")}"
           data-amazon="{r.get("amazon", "N/A")}"
           data-metacritic="{r.get("metacritic", "N/A")}"
           data-hltb="{r.get("hltb", "No disponible")}">
        <div class="img-container">{img_tag_html}</div>
        <div class="title" title="{r["name"]}">{r["name"]}</div>
      </div>
'''
    html += """    </div>
    <div id="no-results-message">No se encontraron resultados para tu búsqueda.</div>
  </div>

  <div id="modal" class="modal">
    <div class="modal-content">
      <span id="modal-close" class="close">&times;</span>
      <h2 id="modal-title"></h2>
      <div class="img-modal-container"><img id="modal-img" src="" alt="Game Image"></div>
      <div class="details">
        <p><strong>Steam:</strong> <span id="modal-steam"></span></p>
        <p><strong>PlayStation:</strong> <span id="modal-playstation"></span></p>
        <p><strong>Amazon:</strong> <span id="modal-amazon"></span></p>
        <p><strong>Metacritic:</strong> <span id="modal-metacritic"></span></p>
        <hr>
        <p><strong>Tiempo de Juego (HLTB):</strong> <span id="modal-hltb"></span></p>
      </div>
    </div>
  </div>

  <script>
    // --- Modal Logic ---
    const modal = document.getElementById('modal');
    const modalTitle = document.getElementById('modal-title');
    const modalImgContainer = document.querySelector('.modal-content .img-modal-container');
    const modalImg   = document.getElementById('modal-img');
    const modalSteam = document.getElementById('modal-steam');
    const modalPlaystation = document.getElementById('modal-playstation');
    const modalAmz   = document.getElementById('modal-amazon');
    const modalMetacritic = document.getElementById('modal-metacritic');
    const modalHltb = document.getElementById('modal-hltb');
    const modalClose = document.getElementById('modal-close');

    document.querySelectorAll('.card').forEach(card => {
      card.addEventListener('click', () => {
        modalTitle.textContent = card.dataset.title;
        modalImg.alt = card.dataset.title;
        if (card.dataset.img) {
            modalImg.src = card.dataset.img;
            modalImgContainer.style.display = 'flex';
            modalImg.style.display = 'block';
        } else {
            modalImg.src = '';
            modalImg.style.display = 'none';
        }
        modalSteam.textContent = card.dataset.steam;
        modalPlaystation.textContent = card.dataset.playstation;
        modalAmz.textContent   = card.dataset.amazon;
        modalMetacritic.textContent = card.dataset.metacritic;
        modalHltb.textContent = card.dataset.hltb;
        modal.classList.add('open');
      });
    });

    function closeModal() { modal.classList.remove('open'); }
    modalClose.addEventListener('click', closeModal);
    modal.addEventListener('click', e => { if (e.target === modal) { closeModal(); } });
    document.addEventListener('keydown', e => { if (e.key === "Escape" && modal.classList.contains('open')) { closeModal(); } });

    // --- Search Logic ---
    const searchInput = document.getElementById('search-input');
    const gameCards = document.querySelectorAll('.card');
    const noResultsMessage = document.getElementById('no-results-message');

    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase().trim();
        let visibleCards = 0;

        gameCards.forEach(card => {
            const gameTitle = card.dataset.title.toLowerCase();
            if (gameTitle.includes(searchTerm)) {
                card.style.display = 'flex';
                visibleCards++;
            } else {
                card.style.display = 'none';
            }
        });

        if (visibleCards === 0) {
            noResultsMessage.style.display = 'block';
        } else {
            noResultsMessage.style.display = 'none';
        }
    });
  </script>
</body>
</html>"""
    with open("report.html", "w", encoding="utf-8") as f: f.write(html)
    if results: print("✔ report.html generado")

def main():
    games_file_path = os.path.join(os.path.dirname(__file__), "games.txt")
    if not os.path.exists(games_file_path):
        try:
            with open(games_file_path, "w", encoding="utf-8") as f:
                f.write("# Ejemplo: Cyberpunk 2077\nElden Ring\nGod of War\nSpider-Man Remastered\n")
        except IOError: 
            print(f"❌ No se pudo crear el archivo '{games_file_path}' de ejemplo.")
        return

    games_from_file = read_games(games_file_path)
    if not games_from_file:
        return

    start_time = time.time()
    
    loaded_metacritic_scores = load_metacritic_scores(METACRITIC_SCORES_FILE)
    loaded_hltb_times = load_hltb_times(HLTB_TIMES_FILE)
    
    price_results = scrape_all_prices(games_from_file, loaded_metacritic_scores, loaded_hltb_times, max_workers=7)
    
    if price_results: 
        generate_html(price_results)
    
    end_time = time.time()
    print(f"✅ Proceso completado en {end_time - start_time:.2f} segundos.")

if __name__ == "__main__":
    main()