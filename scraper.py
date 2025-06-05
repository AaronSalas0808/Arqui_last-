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
    "Referer": "https://www.google.com/", # Un referer común puede ayudar
    "DNT": "1", # Do Not Track
    "Upgrade-Insecure-Requests": "1"
}

METACRITIC_SCORES_FILE = "metacritic_scores.txt"


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
    try:
        r = requests.get(
            "https://store.steampowered.com/api/storesearch/",
            params=params, headers=HEADERS, timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items: return "N/A"
        appid = items[0]["id"]
        r2 = requests.get(
            "https://store.steampowered.com/api/appdetails/",
            params={"appids": appid, "cc": "US", "l": "english"},
            headers=HEADERS, timeout=12,
        )
        r2.raise_for_status()
        info = r2.json().get(str(appid), {})
        data_info = info.get("data", {})
        if not data_info: return "N/A"
        if data_info.get("is_free", False): return "Free"
        po = data_info.get("price_overview")
        if not po: return "N/A"
        price = po["final"] / 100
        return f"{price:.2f} {po['currency']}"
    except Exception: return "N/A"

def get_playstation_price(name: str) -> str:
    # PlayStation Store usa GraphQL, pero intentaremos con una búsqueda web y scraping.
    # Esto es propenso a romperse si cambian la estructura.
    # URL para la tienda de EE. UU.
    search_term_encoded = urllib.parse.quote(name)
    # Ejemplo de URL de búsqueda (puede necesitar ajustes para diferentes regiones o si cambia)
    # A menudo, la búsqueda real se hace con JS y llamadas a API.
    # Este es un intento de simular una búsqueda simple.
    url = f"https://store.playstation.com/en-us/search/{search_term_encoded}"
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Los selectores para PS Store son muy volátiles.
        # Buscamos elementos que contengan el nombre del juego y luego su precio.
        # Esto es una suposición y probablemente necesitará ser ajustado después de inspeccionar el HTML real.
        # Ejemplo de un patrón que podría existir (muy simplificado):
        # <div class="product-tile">
        #   <span class="product-tile__name">Game Name</span>
        #   <span class="price">$--.--</span>
        # </div>
        # O podrían usar data-qa atributos.

        # Intenta encontrar un contenedor de producto que coincida con el nombre
        game_elements = soup.select('div[data-qa*="product"], li[data-qa*="product"]') # Patrón común
        if not game_elements:
            game_elements = soup.find_all(lambda tag: tag.name in ['div', 'li'] and name.lower() in tag.get_text().lower() and '$' in tag.get_text())


        for elem in game_elements:
            title_el = elem.select_one('span[data-qa$="title"], span[class*="name"], h3') # Posibles selectores de título
            if title_el and name.lower() in title_el.get_text(strip=True).lower():
                price_el = elem.select_one('span[data-qa$="display-price"], span[class*="price"]')
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    if price_text.lower() == "free": return "Free"
                    if price_text.startswith("$"): return price_text
                # A veces el precio está en un formato diferente
                price_match = re.search(r"\$\d+\.\d{2}", elem.get_text())
                if price_match:
                    return price_match.group(0)
        return "N/A"
    except Exception:
        # print(f"PS Store error for {name}: {e}")
        return "N/A"


def get_epicgames_price(name: str) -> str:
    # Epic Games Store usa una API GraphQL para su tienda.
    # Este es un endpoint de búsqueda que a veces funciona para obtener datos básicos.
    # País: US, Idioma: en-US
    # Este endpoint puede cambiar o requerir autenticación/tokens más complejos en el futuro.
    search_term_encoded = urllib.parse.quote(name)
    url = (
        f"https://store-content-ipv4.ak.epicgames.com/api/en-US/content/products/slug/{search_term_encoded}"
    )
    # Un endpoint alternativo de búsqueda más general (pero más datos para parsear):
    # url = (
    #     "https://store.epicgames.com/graphql"
    # )
    # graphql_query = {
    #     "query": "query searchStoreQuery($country: String!, $locale: String, $searchText: String!, $start: Int, $count: Int) { Catalog { searchStore(country: $country, locale: $locale, searchText: $searchText, start: $start, count: $count) { elements { title productSlug keyImages { type url } price(country: $country) { totalPrice { fmtPrice(locale: $locale) { originalPrice discountPrice } } } } paging { count total } } } }",
    #     "variables": {"country": "US", "searchText": name, "start": 0, "count": 1, "locale": "en-US"}
    # }
    # headers_epic = HEADERS.copy()
    # headers_epic["Content-Type"] = "application/json"

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # Para el endpoint de slug:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()

        # Si el juego es gratuito
        if data.get("price", {}).get("totalPrice", {}).get("discountPrice", -1) == 0 and \
           data.get("price", {}).get("totalPrice", {}).get("originalPrice", -1) == 0:
            return "Free"

        # Obtener precio
        price_info = data.get("price", {}).get("totalPrice", {}).get("fmtPrice", {})
        if price_info:
            # Priorizar precio con descuento, luego original
            if price_info.get("discountPrice"):
                return price_info["discountPrice"]
            if price_info.get("originalPrice"):
                return price_info["originalPrice"]
        
        # Fallback si la estructura es diferente o es un bundle
        # A veces el precio está en _product_ como price.totalPrice.fmtPrice.originalPrice
        product_info = data.get("_product")
        if product_info and isinstance(product_info, dict):
            price_data = product_info.get("price", {}).get("totalPrice", {}).get("fmtPrice", {})
            if price_data.get("discountPrice"): return price_data["discountPrice"]
            if price_data.get("originalPrice"): return price_data["originalPrice"]


        # Para el endpoint GraphQL (más complejo):
        # r = session.post(url, json=graphql_query, headers=headers_epic, timeout=15)
        # r.raise_for_status()
        # data = r.json()
        # elements = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
        # if elements:
        #     game_data = elements[0]
        #     price_data = game_data.get("price", {}).get("totalPrice", {})
        #     if price_data.get("discountPrice", -1) == 0 and price_data.get("originalPrice", -1) == 0:
        #         return "Free"
        #     fmt_price = price_data.get("fmtPrice", {})
        #     if fmt_price.get("discountPrice"):
        #         return fmt_price["discountPrice"]
        #     if fmt_price.get("originalPrice"):
        #         return fmt_price["originalPrice"]
        return "N/A"
    except Exception:
        # print(f"Epic Store error for {name}: {e}")
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
        print(f"⚠️ Archivo de puntuaciones '{input_filename}' no encontrado. Las puntuaciones de Metacritic serán 'N/A'.")
        print(f"   Puedes generar este archivo ejecutando 'python metacritic_scraper.py'")
        return scores
    with open(input_filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                try:
                    name, score = line.split(":", 1)
                    scores[name.strip()] = score.strip()
                except ValueError: pass
    if scores: print(f"✔ Puntuaciones de Metacritic cargadas desde '{input_filename}'")
    else: print(f"ℹ️ No se cargaron puntuaciones de Metacritic desde '{input_filename}'.")
    return scores

def scrape_game(name: str, all_metacritic_scores: dict) -> dict:
    s, ps, epic, a = "N/A", "N/A", "N/A", "N/A" # Inicializar precios
    try: s = get_steam_price(name)
    except Exception as e: print(f"⚠️ Error Steam «{name}»: {e}")
    try: ps = get_playstation_price(name)
    except Exception as e: print(f"⚠️ Error PlayStation «{name}»: {e}")
    try: epic = get_epicgames_price(name)
    except Exception as e: print(f"⚠️ Error Epic Games «{name}»: {e}")
    try: a = get_amazon_price(name)
    except Exception as e: print(f"⚠️ Error Amazon «{name}»: {e}")
    m_score = all_metacritic_scores.get(name, "N/A")
    return {
        "name": name, "steam": s, "playstation": ps,
        "epicgames": epic, "amazon": a, "metacritic": m_score
    }

def scrape_all_prices(games: list, all_metacritic_scores: dict, max_workers: int = 6) -> list: # Reducido workers por más tiendas
    results = []
    if not games: return results
    print(f"ℹ️ Iniciando scraping de precios para {len(games)} juegos (max_workers={max_workers})...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scrape_game, name, all_metacritic_scores): name for name in games}
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            name = futures[future]
            try:
                res = future.result()
                print(
                    f"  Precios ({i+1}/{len(games)}): «{name}» → Steam: {res['steam']} | PS: {res['playstation']} | Epic: {res['epicgames']} | Amazon: {res['amazon']}"
                )
            except Exception as e:
                print(f"⚠️ Excepción mayor en precios «{name}»: {e}")
                res = {
                    "name": name, "steam": "N/A", "playstation": "N/A",
                    "epicgames": "N/A", "amazon": "N/A",
                    "metacritic": all_metacritic_scores.get(name, "N/A")
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
  <title>Comparativa de Precios y Puntuaciones</title>
  <style>
    body { font-family: Arial,sans-serif; margin:20px;
           background:#f4f4f4; color: #333; }
    h1 { text-align: center; color: #2c3e50; margin-bottom: 30px;}
    .grid {
      display:grid;
      grid-template-columns: repeat(auto-fill, minmax(230px,1fr));
      gap:25px;
    }
    .card {
      background:#fff; border:1px solid #ddd; border-radius:10px;
      overflow:hidden; box-shadow:0 4px 8px rgba(0,0,0,0.08);
      cursor:pointer; transition:transform .2s ease-out, box-shadow .2s ease-out;
      display: flex; flex-direction: column;
    }
    .card:hover { transform:translateY(-5px); box-shadow:0 6px 12px rgba(0,0,0,0.12); }
    .card .img-container {
        width:100%; height:160px; background:#ececec;
        display:flex; align-items:center; justify-content:center;
        overflow: hidden;
    }
    .card .img-container img { width:100%; height:100%; object-fit:cover; }
    .card .img-container .placeholder-text { color:#aaa; font-style:italic; }
    .card .title {
      padding:12px 15px; font-size:1.05em; font-weight: bold; text-align:center; color:#333;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      border-top: 1px solid #eee;
    }
    .modal {
      display:none; position:fixed; z-index:1000; top:0; left:0; width:100%; height:100%;
      background:rgba(0,0,0,0.65); align-items:center; justify-content:center;
      padding: 20px; box-sizing: border-box;
    }
    .modal.open { display:flex; }
    .modal-content {
      background:#fff; border-radius:10px; padding:25px 30px;
      max-width:480px; width:100%; position:relative;
      box-shadow:0 5px 20px rgba(0,0,0,0.25); animation:fadeInModal .3s ease-out;
    }
    .modal-content .img-modal-container {
        max-width:100%; max-height: 220px; display:flex; align-items:center;
        justify-content:center; margin:0 auto 20px; border-radius: 6px;
        overflow:hidden; background-color: #f0f0f0;
    }
    .modal-content .img-modal-container img {
        max-width:100%; max-height:100%; object-fit:contain;
    }
    .modal-content h2 { margin:0 0 20px; font-size:1.5em; text-align:center; color: #2c3e50; }
    .modal-content .details p {
      margin:10px 0; font-size:1em; color:#555; border-bottom: 1px solid #f0f0f0;
      padding-bottom: 10px; display: flex; justify-content: space-between; align-items: center;
    }
    .modal-content .details p:last-child { border-bottom: none; }
    .modal-content .details strong { color: #333; margin-right: 10px; flex-shrink: 0;}
    .modal-content .details span { text-align: right; word-break: break-word; }
    .close {
      position:absolute; top:15px; right:20px; font-size:1.8em; line-height: 1;
      cursor:pointer; color:#aaa; transition: color 0.2s;
    }
    .close:hover { color: #777; }
    @keyframes fadeInModal {
      from { opacity:0; transform:translateY(-25px) scale(0.95) }
      to   { opacity:1; transform:translateY(0) scale(1) }
    }
  </style>
</head>
<body>
  <h1>Comparativa de Precios y Puntuaciones</h1>
  <div class="grid">
"""
    for r in results:
        img_url = images.get(r["name"], "")
        img_tag_html = f'<img src="{img_url}" alt="{r["name"]}">' if img_url else '<span class="placeholder-text">No Image</span>'
        html += f'''    <div class="card"
         data-title="{r["name"]}"
         data-img="{img_url}"
         data-steam="{r.get("steam", "N/A")}"
         data-playstation="{r.get("playstation", "N/A")}"
         data-epicgames="{r.get("epicgames", "N/A")}"
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
        <p><strong>Epic Games:</strong> <span id="modal-epicgames"></span></p>
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
    const modalPlaystation = document.getElementById('modal-playstation'); // Nuevo
    const modalEpicgames = document.getElementById('modal-epicgames'); // Nuevo
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
        modalPlaystation.textContent = card.dataset.playstation; // Nuevo
        modalEpicgames.textContent = card.dataset.epicgames; // Nuevo
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
                f.write("# Ejemplo: Cyberpunk 2077\nElden Ring\nGod of War\n") # Añadido God of War como ejemplo
            print(f"✔ Se ha creado un archivo '{games_file_path}' de ejemplo.")
        except IOError: print(f"❌ No se pudo crear el archivo '{games_file_path}' de ejemplo.")
        return

    games_from_file = read_games(games_file_path)
    if not games_from_file:
        print("ℹ️ No se encontraron juegos en 'games.txt'.")
        return

    start_time = time.time()
    loaded_metacritic_scores = load_metacritic_scores(METACRITIC_SCORES_FILE)
    price_results = scrape_all_prices(games_from_file, loaded_metacritic_scores, max_workers=6) # max_workers ajustado
    if price_results: generate_html(price_results)
    else: print("ℹ️ No se obtuvieron resultados de precios para generar el reporte HTML.")
    end_time = time.time()
    print(f"✅ Proceso completado en {end_time - start_time:.2f} segundos.")

if __name__ == "__main__":
    main()