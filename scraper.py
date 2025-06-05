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
DEBUG_PLAYSTATION_HTML = True # Para depurar PS Store



def read_games(file_path: str) -> list:
    games = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            games.append(line)
    return games

# --- get_steam_price RESTAURADA A TU VERSIÓN ORIGINAL ---
def get_steam_price(name: str) -> str:
    params = {"term": name, "l": "english", "cc": "US"}
    r = requests.get(
        "https://store.steampowered.com/api/storesearch/",
        params=params,
        headers=HEADERS,
        timeout=10,
    )
    r.raise_for_status() # Will raise an exception for HTTP errors
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
    data_info = info.get("data", {}) # Acceso más seguro
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
        
        # Si es un 404, el juego no se encontró, no es un error de parsing.
        if r.status_code == 404:
            # print(f"  PS Store: Juego «{name}» no encontrado (404 en {actual_url})")
            return "N/A" # No guardar HTML de depuración para 404
        
        r.raise_for_status() # Para otros errores HTTP (403, 500, etc.)
        html_content_for_debug = r.text
        soup = BeautifulSoup(r.text, "html.parser")

        price_selectors = [
            'span[data-qa$="display-price"]',
            'span[data-qa$="finalPrice"]',
            'div[data-qa*="price"] > span',
            'span[class*="price"][class*="sales"]',
            'span[class*="price"][class*="original"]',
            'span[class*="psw-t-title-m"][class*="psw-m-r-3"]',
            'span.psw-l-line-left',
            'div.psw-l-line-left > span.psw-t-title-m',
            'span.price',
            'div[class*="ProductPrice"]',
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
            if "free" in body_text.lower() and "add to cart" in body_text.lower():
                 return "Free"

    except requests.exceptions.HTTPError as e:
        if e.response.status_code != 404: # No guardar para 404, ya manejado arriba
            # print(f"  PS Store: HTTP error {e.response.status_code} para «{name}» (URL: {actual_url})")
            if DEBUG_PLAYSTATION_HTML and e.response:
                debug_filename = f"playstation_error_{name.replace(' ', '_')[:30]}_{e.response.status_code}.html"
                with open(debug_filename, "w", encoding="utf-8") as df:
                    df.write(f"<!-- URL: {url}, URL Final: {actual_url}, STATUS: {e.response.status_code} -->\n<!-- Juego: {name} -->\n")
                    df.write(e.response.text)
        return "N/A"
    except Exception: # e
        # print(f"  PS Store: Error general para «{name}» (URL: {actual_url}): {e}")
        if DEBUG_PLAYSTATION_HTML and html_content_for_debug:
            debug_filename = f"playstation_exception_{name.replace(' ', '_')[:30]}.html"
            with open(debug_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- URL: {url}, URL Final: {actual_url}, EXCEPCIÓN: {type(e).__name__} - {e} -->\n<!-- Juego: {name} -->\n") # type: ignore
                df.write(html_content_for_debug)
        return "N/A"
# --- FIN get_playstation_price ---


def get_amazon_price(name: str) -> str:
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set("i18n-prefs", "USD", domain="www.amazon.com")
    search_term = f"{name} PC game" # O buscar solo el nombre si es para consola
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
        print(f"⚠️ Archivo de puntuaciones '{input_filename}' no encontrado.")
        print(f"   Puedes generar este archivo ejecutando 'python metacritic_scraper.py'")
        return scores
    with open(input_filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                try: name, score = line.split(":", 1); scores[name.strip()] = score.strip()
                except ValueError: pass
    if scores: print(f"✔ Puntuaciones de Metacritic cargadas desde '{input_filename}'")
    else: print(f"ℹ️ No se cargaron puntuaciones de Metacritic desde '{input_filename}'.")
    return scores

def scrape_game(name: str, all_metacritic_scores: dict) -> dict:
    s, ps, a = "N/A", "N/A", "N/A"
    try: s = get_steam_price(name)
    except Exception as e: print(f"⚠️ Error Steam «{name}»: {e}")
    try: ps = get_playstation_price(name)
    except Exception as e: print(f"⚠️ Error PlayStation «{name}»: {e}")
    try: a = get_amazon_price(name)
    except Exception as e: print(f"⚠️ Error Amazon «{name}»: {e}")
    m_score = all_metacritic_scores.get(name, "N/A")
    return {"name": name, "steam": s, "playstation": ps, "amazon": a, "metacritic": m_score}

def scrape_all_prices(games: list, all_metacritic_scores: dict, max_workers: int = 6) -> list:
    results = []
    if not games: return results
    print(f"ℹ️ Iniciando scraping de precios para {len(games)} juegos (max_workers={max_workers})...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scrape_game, name, all_metacritic_scores): name for name in games}
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            name = futures[future]
            try:
                res = future.result()
                print(f"  Precios ({i+1}/{len(games)}): «{name}» → Steam: {res['steam']} | PS: {res['playstation']} | Amazon: {res['amazon']}")
            except Exception as e:
                print(f"⚠️ Excepción mayor en precios «{name}»: {e}")
                res = {"name": name, "steam": "N/A", "playstation": "N/A", "amazon": "N/A", "metacritic": all_metacritic_scores.get(name, "N/A")}
            results.append(res)
    return results

def generate_html(results: list, images_path="images.json"):

    try:
        with open(images_path, encoding="utf-8") as f: images = json.load(f)
    except Exception: images = {}
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Paginita</title><style>body{font-family:Arial,sans-serif;margin:20px;background:#f4f4f4;color:#333}h1{text-align:center;color:#2c3e50;margin-bottom:30px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:25px}.card{background:#fff;border:1px solid #ddd;border-radius:10px;overflow:hidden;box-shadow:0 4px 8px rgba(0,0,0,.08);cursor:pointer;transition:transform .2s ease-out,box-shadow .2s ease-out;display:flex;flex-direction:column}.card:hover{transform:translateY(-5px);box-shadow:0 6px 12px rgba(0,0,0,.12)}.card .img-container{width:100%;height:160px;background:#ececec;display:flex;align-items:center;justify-content:center;overflow:hidden}.card .img-container img{width:100%;height:100%;object-fit:cover}.card .img-container .placeholder-text{color:#aaa;font-style:italic}.card .title{padding:12px 15px;font-size:1.05em;font-weight:700;text-align:center;color:#333;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-top:1px solid #eee}.modal{display:none;position:fixed;z-index:1000;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.65);align-items:center;justify-content:center;padding:20px;box-sizing:border-box}.modal.open{display:flex}.modal-content{background:#fff;border-radius:10px;padding:25px 30px;max-width:480px;width:100%;position:relative;box-shadow:0 5px 20px rgba(0,0,0,.25);animation:fadeInModal .3s ease-out}.modal-content .img-modal-container{max-width:100%;max-height:220px;display:flex;align-items:center;justify-content:center;margin:0 auto 20px;border-radius:6px;overflow:hidden;background-color:#f0f0f0}.modal-content .img-modal-container img{max-width:100%;max-height:100%;object-fit:contain}.modal-content h2{margin:0 0 20px;font-size:1.5em;text-align:center;color:#2c3e50}.modal-content .details p{margin:10px 0;font-size:1em;color:#555;border-bottom:1px solid #f0f0f0;padding-bottom:10px;display:flex;justify-content:space-between;align-items:center}.modal-content .details p:last-child{border-bottom:none}.modal-content .details strong{color:#333;margin-right:10px;flex-shrink:0}.modal-content .details span{text-align:right;word-break:break-word}.close{position:absolute;top:15px;right:20px;font-size:1.8em;line-height:1;cursor:pointer;color:#aaa;transition:color .2s}.close:hover{color:#777}@keyframes fadeInModal{from{opacity:0;transform:translateY(-25px) scale(.95)}to{opacity:1;transform:translateY(0) scale(1)}}</style></head><body><h1>Comparativa de Precios y Puntuaciones</h1><div class="grid">""" # type: ignore
    for r in results:
        img_url = images.get(r["name"], "")
        img_tag_html = f'<img src="{img_url}" alt="{r["name"]}">' if img_url else '<span class="placeholder-text">No Image</span>'
        html += f'''    <div class="card"
             data-title="{r["name"]}"
             data-img="{img_url}"
             data-steam="{r.get("steam", "N/A")}"
             data-playstation="{r.get("playstation", "N/A")}"
             data-amazon="{r.get("amazon", "N/A")}"
             data-metacritic="{r.get("metacritic", "N/A")}">
          <div class="img-container">{img_tag_html}</div>
          <div class="title" title="{r["name"]}">{r["name"]}</div>
        </div>
    '''
    html += """  </div>
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
          </div>
        </div>
      </div>
      <script>
        const modal = document.getElementById('modal');
        const modalTitle = document.getElementById('modal-title');
        const modalImgContainer = document.querySelector('.modal-content .img-modal-container');
        const modalImg   = document.getElementById('modal-img');
        const modalSteam = document.getElementById('modal-steam');
        const modalPlaystation = document.getElementById('modal-playstation');
        const modalAmz   = document.getElementById('modal-amazon');
        const modalMetacritic = document.getElementById('modal-metacritic');
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
            modal.classList.add('open');
          });
        });
        function closeModal() { modal.classList.remove('open'); }
        modalClose.addEventListener('click', closeModal);
        modal.addEventListener('click', e => { if (e.target === modal) { closeModal(); } });
        document.addEventListener('keydown', e => { if (e.key === "Escape" && modal.classList.contains('open')) { closeModal(); } });
      </script>
    </body>
    </html>"""
    with open("report.html", "w", encoding="utf-8") as f: f.write(html)
    if results: print("✔ report.html generado")


def main():
    games_file_path = os.path.join(os.path.dirname(__file__), "games.txt")
    if not os.path.exists(games_file_path):
        print(f"❌ Error: El archivo '{games_file_path}' no existe.")
        try:
            with open(games_file_path, "w", encoding="utf-8") as f:
                f.write("# Ejemplo: Cyberpunk 2077\nElden Ring\nGod of War\nSpider-Man Remastered\n")
            print(f"✔ Se ha creado un archivo '{games_file_path}' de ejemplo.")
        except IOError: print(f"❌ No se pudo crear el archivo '{games_file_path}' de ejemplo.")
        return

    games_from_file = read_games(games_file_path)
    if not games_from_file:
        print("ℹ️ No se encontraron juegos en 'games.txt'.")
        return

    start_time = time.time()
    loaded_metacritic_scores = load_metacritic_scores(METACRITIC_SCORES_FILE)
    price_results = scrape_all_prices(games_from_file, loaded_metacritic_scores, max_workers=6)
    if price_results: generate_html(price_results)
    else: print("ℹ️ No se obtuvieron resultados de precios para generar el reporte HTML.")
    end_time = time.time()
    print(f"✅ Proceso completado en {end_time - start_time:.2f} segundos.")

if __name__ == "__main__":
    main()