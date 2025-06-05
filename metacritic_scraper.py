# metacritic_scraper.py
import os
import time
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

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
GAMES_FILE_PATH = "games.txt" # Asume que games.txt está en el mismo directorio
DEBUG_METACRITIC_HTML = True # Puedes ponerlo en False cuando estés seguro de que funciona


def read_games(file_path: str) -> list:
    games = []
    if not os.path.exists(file_path):
        print(f"❌ Error: El archivo de juegos '{file_path}' no existe.")
        return games
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            games.append(line)
    return games

def _clean_filename(name):
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'\s+', '_', name)
    return name[:50]

def _fetch_single_metacritic_score(game_name: str, session: requests.Session) -> str:
    search_term_encoded = urllib.parse.quote(game_name)
    url = f"https://www.metacritic.com/search/{search_term_encoded}/"
    html_content_for_debug = ""
    score_found = "N/A"
    actual_url = url

    try:
        r = session.get(url, timeout=25, allow_redirects=True)
        r.raise_for_status()
        actual_url = r.url
        html_content_for_debug = r.text
        soup = BeautifulSoup(r.text, "html.parser")

        score_selectors = [
            'div[class*="c-siteReviewScore"]:not([class*="user"]) span',
            'meta-score-styled-pe[scorevalue]',
            'div[class*="c-productScoreDetails_sideScore"] div[class*="c-siteReviewScore"]:not([class*="user"]) span',
            'a[class*="c-productHero_score"] div[class*="c-siteReviewScore"] span',
            'div.metascore_w.game span',
            'div.game_details .metascore_wrap span.score_value',
            'span.metascore_w',
            'div[data-test-id="critic-score"]',
            'div[class*="criticScore"]',
        ]

        for selector in score_selectors:
            score_element = soup.select_one(selector)
            if score_element:
                score_val = ""
                if score_element.name == 'meta-score-styled-pe' and score_element.has_attr('scorevalue'):
                    score_val = score_element['scorevalue']
                else:
                    score_val = score_element.get_text(strip=True)

                if score_val.lower() == "tbd":
                    score_found = "tbd"
                    break
                if score_val.isdigit() and 0 <= int(score_val) <= 100:
                    score_found = score_val
                    break
            if score_found != "N/A":
                break

        if score_found == "N/A" and DEBUG_METACRITIC_HTML:
            debug_filename = f"metacritic_debug_{_clean_filename(game_name)}.html"
            with open(debug_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- URL VISITADA: {actual_url} -->\n<!-- JUEGO: {game_name} -->\n")
                df.write(html_content_for_debug if html_content_for_debug else "NO SE CAPTURÓ CONTENIDO HTML")
            print(f"  Metacritic: Puntuación no encontrada. HTML de depuración guardado en {debug_filename} para «{game_name}»")
        return score_found

    except requests.exceptions.HTTPError as e:
        print(f"  Metacritic: HTTP error {e.response.status_code} para «{game_name}» (URL: {url}, URL Final: {actual_url})")
        if DEBUG_METACRITIC_HTML and e.response:
            debug_filename = f"metacritic_error_{_clean_filename(game_name)}_{e.response.status_code}.html"
            with open(debug_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- URL: {url}, URL FINAL: {actual_url}, STATUS: {e.response.status_code} -->\n<!-- JUEGO: {game_name} -->\n")
                df.write(e.response.text)
            print(f"  Metacritic: HTML de error guardado en {debug_filename} para «{game_name}»")
        return "N/A"
    except Exception as e_gen:
        print(f"  Metacritic: Error general para «{game_name}» (URL: {url}, URL Final: {actual_url}): {type(e_gen).__name__} - {e_gen}")
        if DEBUG_METACRITIC_HTML and html_content_for_debug:
            debug_filename = f"metacritic_exception_{_clean_filename(game_name)}.html"
            with open(debug_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- URL: {url}, URL FINAL: {actual_url}, EXCEPCIÓN: {type(e_gen).__name__} - {e_gen} -->\n<!-- JUEGO: {game_name} -->\n")
                df.write(html_content_for_debug)
            print(f"  Metacritic: HTML de contexto de excepción guardado en {debug_filename} para «{game_name}»")
        return "N/A"

def scrape_and_save_metacritic_scores(games_list: list, output_filename: str, delay_seconds: int = 5):
    if not games_list:
        print("ℹ️ No hay juegos en la lista para buscar puntuaciones de Metacritic.")
        return

    print(f"ℹ️ Iniciando scraping de Metacritic para {len(games_list)} juegos (delay: {delay_seconds}s)...")
    found_any_score = False
    scores_data = {}

    with requests.Session() as session:
        session.headers.update(HEADERS)
        try:
            session.get("https://www.metacritic.com/", timeout=15)
        except requests.RequestException as e:
            print(f"  Metacritic: Falló GET inicial a metacritic.com: {e}")
            # Continuar de todas formas

        for i, game_name in enumerate(games_list):
            score = _fetch_single_metacritic_score(game_name, session)
            scores_data[game_name] = score
            if score != "N/A" and score != "tbd":
                found_any_score = True
            print(f"  Metacritic ({i+1}/{len(games_list)}): «{game_name}» → {score}")
            if i < len(games_list) - 1:
                time.sleep(delay_seconds)

    with open(output_filename, "w", encoding="utf-8") as f:
        for game_name, score in scores_data.items():
            f.write(f"{game_name}:{score}\n")

    if not found_any_score and games_list:
        print("⚠️ Metacritic: No se encontraron puntuaciones válidas para ningún juego.")
    elif games_list:
        print(f"✔ Puntuaciones de Metacritic (re)generadas y guardadas en '{output_filename}'")

def main():
    print("--- Script de Scraping de Metacritic ---")
    games_to_scrape = read_games(GAMES_FILE_PATH)
    if games_to_scrape:
        scrape_and_save_metacritic_scores(games_to_scrape, METACRITIC_SCORES_FILE, delay_seconds=5)
    else:
        print(f"Asegúrate de que '{GAMES_FILE_PATH}' existe y contiene nombres de juegos.")
    print("--- Fin del Script de Scraping de Metacritic ---")

if __name__ == "__main__":
    main()