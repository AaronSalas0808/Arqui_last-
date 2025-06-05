# hltb_scraper.py (Scraping directo de página HLTB - Guardando HTML de búsqueda)
import os
import time
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
import json # Aunque no se usa para guardar, puede ser útil para depurar respuestas JSON si se cambia el enfoque

HLTB_TIMES_FILE = "howlongtobeat_times.txt"
GAMES_FILE_PATH = "games.txt"
REQUEST_DELAY_SECONDS = 6 # Delay entre peticiones
DEBUG_HLTB_HTML = True # Poner en True para guardar HTMLs de depuración

HLTB_BASE_URL = "https://howlongtobeat.com/"
# Headers para simular un navegador
HLTB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    "Referer": "https://howlongtobeat.com/", # A veces ayuda tener un referer
    "DNT": "1", # Do Not Track
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin", # O "cross-site" si la búsqueda fuera a un subdominio diferente
    "Sec-Fetch-User": "?1", # Indica navegación iniciada por el usuario
}

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

def format_hltb_string_time(time_string: str) -> str:
    if not time_string or "N/A" in time_string or "Not Available" in time_string:
        return "--"
    time_string = time_string.replace("½", ".5").replace("&#189;", ".5")
    hours, minutes = 0, 0
    hour_match = re.search(r"([\d\.]+)\s*H(?:our(?:s)?)?", time_string, re.IGNORECASE)
    if hour_match:
        try:
            h_val = float(hour_match.group(1))
            hours = int(h_val)
            minutes += int(round((h_val - hours) * 60))
        except ValueError: pass
    min_match = re.search(r"([\d\.]+)\s*M(?:in(?:ute(?:s)?)?)?", time_string, re.IGNORECASE)
    if min_match:
        try:
            if not (hour_match and '.' in hour_match.group(1)): minutes += int(round(float(min_match.group(1))))
            elif not hour_match: minutes += int(round(float(min_match.group(1))))
        except ValueError: pass
    if minutes >= 60: hours += minutes // 60; minutes %= 60
    if hours > 0 and minutes > 0: return f"{hours}h {minutes}m"
    elif hours > 0: return f"{hours}h"
    elif minutes > 0: return f"{minutes}m"
    else: return "--" if time_string.strip() in ["", "None"] else time_string.strip()


def get_game_page_times(soup: BeautifulSoup, game_name_for_debug: str) -> dict:
    """
    Parsea los tiempos de HLTB desde el HTML de la página de un juego específico.
    Intenta ser robusto ante variaciones en la estructura HTML.
    """
    times = {"main": "--", "extra": "--", "completionist": "--"}
    
    main_story_patterns = ["Main Story", "Single-Player", "Solo"]
    main_extra_patterns = ["Main + Extras", "Main + Sides", "Story + Sides"]
    completionist_patterns = ["Completionist", "100%"]

    # --- Intento 1: Buscar una estructura de lista común (ul > li) ---
    possible_list_containers = soup.select('ul[class*="game_times"], div[class*="GameDetails_timings"], div[class*="Stats_game_times"]')
    
    found_any_time_attempt1 = False
    for container in possible_list_containers:
        list_items = container.find_all('li', recursive=True)
        for item_li in list_items:
            item_text_lower = item_li.get_text(" ", strip=True).lower()
            time_value_element = item_li.find(['h5', 'div', 'span'], class_=lambda x: x and ('value' in x.lower() or 'time' in x.lower()))
            if not time_value_element:
                potential_time_elements = item_li.find_all(['h5', 'div', 'span'])
                if potential_time_elements:
                    time_value_element = potential_time_elements[-1]
            
            if time_value_element:
                time_value_str = time_value_element.get_text(strip=True)
                if any(p.lower() in item_text_lower for p in main_story_patterns):
                    if times["main"] == "--": times["main"] = format_hltb_string_time(time_value_str); found_any_time_attempt1 = True
                elif any(p.lower() in item_text_lower for p in main_extra_patterns):
                    if times["extra"] == "--": times["extra"] = format_hltb_string_time(time_value_str); found_any_time_attempt1 = True
                elif any(p.lower() in item_text_lower for p in completionist_patterns):
                    if times["completionist"] == "--": times["completionist"] = format_hltb_string_time(time_value_str); found_any_time_attempt1 = True
        if found_any_time_attempt1 and not all(t == "--" for t in times.values()): # Si encontramos algo útil, parar
            break


    # --- Intento 2: Buscar estructura de divs más plana (común en diseños nuevos) ---
    found_any_time_attempt2 = False
    if all(t == "--" for t in times.values()): # Solo si el Intento 1 falló completamente
        all_div_blocks = soup.select('div[class*="Stats_time_block"], div[class*="GameStats_game_times__box"], div[class*="profile_details_block"]')
        if not all_div_blocks:
            all_div_blocks = soup.find_all('div', limit=50)

        for block_div in all_div_blocks:
            block_text_lower = block_div.get_text(" ", strip=True).lower()
            time_value_element = block_div.find(['h5', 'div', 'span'], class_=lambda x: x and ('value' in x.lower() or 'time_stat' in x.lower()))
            if not time_value_element: time_value_element = block_div.find('h5')
            if not time_value_element:
                if re.search(r"(\d+\s*(Hour|Min)|N/A)", block_div.get_text(strip=True), re.IGNORECASE):
                    time_value_element = block_div
            
            if time_value_element:
                time_value_str = time_value_element.get_text(strip=True)
                if any(p.lower() in block_text_lower for p in main_story_patterns):
                    if times["main"] == "--": times["main"] = format_hltb_string_time(time_value_str); found_any_time_attempt2 = True
                elif any(p.lower() in block_text_lower for p in main_extra_patterns):
                    if times["extra"] == "--": times["extra"] = format_hltb_string_time(time_value_str); found_any_time_attempt2 = True
                elif any(p.lower() in block_text_lower for p in completionist_patterns):
                    if times["completionist"] == "--": times["completionist"] = format_hltb_string_time(time_value_str); found_any_time_attempt2 = True
            if found_any_time_attempt2 and not all(t == "--" for t in times.values()):
                 break
        if found_any_time_attempt2 and not all(t == "--" for t in times.values()): # Si encontramos algo útil, parar
            pass # Ya se hizo break interno o se completó el bucle


    # --- Intento 3: Regex general sobre todo el texto de la página (último recurso) ---
    # Esta variable all_page_text se define aquí, antes de ser usada.
    all_page_text = "" # Inicializar por si soup es None o no tiene body
    if soup and soup.body: # Asegurarse de que soup y soup.body existen
        all_page_text = soup.body.get_text(" ", strip=True)
    
    if all(t == "--" for t in times.values()) and all_page_text: # Solo si los intentos anteriores fallaron y hay texto
        main_match = re.search(r"(?:Main Story|Single-Player|Solo)\s*:\s*([\d\w\s½\.]+)", all_page_text, re.IGNORECASE)
        if not main_match:
            main_match = re.search(r"(?:Main Story|Single-Player|Solo)\s+([\d\w\s½\.]+?)(?:\s+(?:Hours|Mins)|<|$|Main \+)", all_page_text, re.IGNORECASE)
        if main_match:
            times["main"] = format_hltb_string_time(main_match.group(1).strip())

        extra_match = re.search(r"(?:Main\s*\+\s*(?:Extras|Sides)|Story \+ Sides)\s*:\s*([\d\w\s½\.]+)", all_page_text, re.IGNORECASE)
        if not extra_match:
            extra_match = re.search(r"(?:Main\s*\+\s*(?:Extras|Sides)|Story \+ Sides)\s+([\d\w\s½\.]+?)(?:\s+(?:Hours|Mins)|<|$|Completionist)", all_page_text, re.IGNORECASE)
        if extra_match:
            times["extra"] = format_hltb_string_time(extra_match.group(1).strip())

        comp_match = re.search(r"(?:Completionist|100%)\s*:\s*([\d\w\s½\.]+)", all_page_text, re.IGNORECASE)
        if not comp_match:
            comp_match = re.search(r"(?:Completionist|100%)\s+([\d\w\s½\.]+?)(?:\s+(?:Hours|Mins)|<|$)", all_page_text, re.IGNORECASE)
        if comp_match:
            times["completionist"] = format_hltb_string_time(comp_match.group(1).strip())
            
    return times

def get_single_game_hltb_page_scrape(game_name: str, session: requests.Session) -> dict:
    times = {"main": "--", "extra": "--", "completionist": "--"}
    search_query_encoded = urllib.parse.quote_plus(game_name)
    # Usar la URL de búsqueda GET que parece funcionar para obtener una lista
    search_page_url = f"https://howlongtobeat.com/?q={search_query_encoded}"
    
    game_page_html_for_debug = ""
    search_page_html_for_debug = ""
    game_page_url_found = ""
    # Limpiar nombre del juego para usar en el nombre del archivo de depuración
    clean_game_name_for_file = re.sub(r'[^\w\s-]', '', game_name).replace(' ', '_')[:30]

    try:
        # print(f"    HLTB Page Scrape: Buscando en URL: {search_page_url}")
        search_response = session.get(search_page_url, timeout=25) # Timeout aumentado
        search_response.raise_for_status()
        search_page_html_for_debug = search_response.text
        search_soup = BeautifulSoup(search_page_html_for_debug, "html.parser")

        if DEBUG_HLTB_HTML:
            debug_search_filename = f"hltb_debug_searchpage_{clean_game_name_for_file}.html"
            with open(debug_search_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- URL de Búsqueda: {search_page_url} -->\n<!-- Juego Buscado: {game_name} -->\n")
                df.write(search_page_html_for_debug)
            # print(f"    HLTB Page Scrape: HTML de la página de búsqueda guardado en {debug_search_filename}")

        # Intentar encontrar el enlace al juego en la página de resultados
        # Los selectores aquí son cruciales y dependen del diseño de HLTB
        # Ejemplo: <a href="/game/12345/Game-Title"><h3>Game Title</h3>...</a>
        # O en el nuevo diseño: <a ... class="GameCard_profile_link__* ... href="/game/..."> <h3 class="GameCard_title__*">Game Title</h3> </a>
        
        game_links = search_soup.select('a[href*="/game/"]') # Selector general para enlaces de juego
        best_match_link_href = None
        highest_similarity_score = -0.1 # Empezar en negativo para que cualquier coincidencia sea mejor

        for link_candidate in game_links:
            # Intentar obtener el título del juego desde el enlace
            title_element = link_candidate.find('h3') # Muchos sitios usan h3 para títulos en tarjetas
            if not title_element: # Fallback a buscar texto dentro del 'a' o un div/span con clase 'title'
                title_element = link_candidate.find(['div', 'span'], class_=lambda x: x and 'title' in x.lower())
            
            link_title_text = ""
            if title_element:
                link_title_text = title_element.get_text(strip=True)
            else: # Si no hay h3 o clase title, tomar el texto visible del enlace
                link_title_text = link_candidate.get_text(strip=True)
                # A veces el texto del enlace es solo la imagen, así que esto puede ser vacío.
                # Podríamos necesitar un selector más robusto para el título si este falla.

            if not link_title_text: # Si sigue vacío, intentar con el atributo title del 'a'
                link_title_text = link_candidate.get('title', '')


            # Calcular similitud (muy básico, se puede mejorar)
            # print(f"      Candidato: '{link_title_text}' vs '{game_name}'") # DEBUG
            normalized_link_title = link_title_text.lower()
            normalized_game_name = game_name.lower()

            current_similarity = 0
            if normalized_link_title: # Solo si tenemos un título para comparar
                if normalized_game_name == normalized_link_title:
                    current_similarity = 1.0 # Coincidencia perfecta
                elif normalized_game_name in normalized_link_title:
                    current_similarity = 0.5 + (len(normalized_game_name) / len(normalized_link_title)) * 0.4
                elif normalized_link_title in normalized_game_name: # Menos peso si el buscado es más largo
                     current_similarity = 0.3 + (len(normalized_link_title) / len(normalized_game_name)) * 0.4


            if current_similarity > highest_similarity_score:
                highest_similarity_score = current_similarity
                best_match_link_href = link_candidate.get('href')
                # print(f"        Nuevo mejor candidato: '{link_title_text}' (Sim: {current_similarity:.2f}), Enlace: {best_match_link_href}") # DEBUG
                if current_similarity == 1.0: # Coincidencia perfecta, no buscar más
                    break
        
        if best_match_link_href:
            if not best_match_link_href.startswith("http"):
                game_page_url_found = urllib.parse.urljoin(HLTB_BASE_URL, best_match_link_href)
            else:
                game_page_url_found = best_match_link_href
            
            # print(f"    HLTB Page Scrape: URL de página de juego encontrada: {game_page_url_found}")

            game_page_response = session.get(game_page_url_found, timeout=20)
            game_page_response.raise_for_status()
            game_page_html_for_debug = game_page_response.text
            game_soup = BeautifulSoup(game_page_html_for_debug, "html.parser")
            times = get_game_page_times(game_soup, game_name)

            if DEBUG_HLTB_HTML and all(t == "--" for t in times.values()):
                debug_gamepage_filename = f"hltb_debug_gamepage_no_times_{clean_game_name_for_file}.html"
                with open(debug_gamepage_filename, "w", encoding="utf-8") as df:
                    df.write(f"<!-- URL Página Juego: {game_page_url_found} -->\n<!-- Juego: {game_name} -->\n")
                    df.write(game_page_html_for_debug)
        # else:
            # print(f"    HLTB Page Scrape: No se encontró un enlace de juego coincidente para '{game_name}'.")

    except requests.exceptions.HTTPError as e:
        # No guardar HTML de depuración para 404 en la búsqueda inicial, ya se guardó arriba.
        if e.response.status_code != 404:
            print(f"    Error HTTP HLTB Page Scrape para '{game_name}': {e}")
            if DEBUG_HLTB_HTML and e.response and search_page_html_for_debug: # Si el error fue en la página del juego
                 debug_error_filename = f"hltb_debug_error_gamepage_{clean_game_name_for_file}_{e.response.status_code}.html"
                 with open(debug_error_filename, "w", encoding="utf-8") as df:
                    df.write(f"<!-- URL Página Juego (si se intentó): {game_page_url_found} -->\n<!-- Juego: {game_name} -->\n<!-- STATUS: {e.response.status_code} -->\n")
                    df.write(e.response.text) # Guardar el HTML de la página que dio error
    except requests.exceptions.RequestException as e:
        print(f"    Error de red HLTB Page Scrape para '{game_name}': {e}")
    except Exception as e:
        print(f"    Error general en HLTB Page Scrape para '{game_name}' ({type(e).__name__}): {e}")
        if DEBUG_HLTB_HTML and (game_page_html_for_debug or search_page_html_for_debug):
            debug_exception_filename = f"hltb_debug_exception_{clean_game_name_for_file}.html"
            with open(debug_exception_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- Juego: {game_name} -->\n<!-- EXCEPCIÓN: {type(e).__name__} - {e} -->\n")
                df.write(game_page_html_for_debug if game_page_html_for_debug else search_page_html_for_debug)
            
    return times

def scrape_and_save_hltb_times(games_list: list, output_filename: str):
    if not games_list:
        print("ℹ️ No hay juegos en la lista para buscar tiempos de HowLongToBeat.")
        return

    print(f"ℹ️ Iniciando scraping (directo de página) de HowLongToBeat para {len(games_list)} juegos (delay: {REQUEST_DELAY_SECONDS}s)...")
    hltb_data_to_save = []
    
    with requests.Session() as session:
        session.headers.update(HLTB_HEADERS)
        try:
            session.get(HLTB_BASE_URL, timeout=15)
        except requests.RequestException as e:
            print(f"    HLTB Page Scrape: Falló visita inicial a howlongtobeat.com: {e}")

        for i, game_name in enumerate(games_list):
            print(f"  HLTB ({i+1}/{len(games_list)}): Buscando «{game_name}»...")
            game_times = get_single_game_hltb_page_scrape(game_name, session)
            hltb_data_to_save.append({"name": game_name, "main": game_times["main"], "extra": game_times["extra"], "completionist": game_times["completionist"]})
            print(f"    Tiempos: Main: {game_times['main']}, Extra: {game_times['extra']}, Completionist: {game_times['completionist']}")
            if i < len(games_list) - 1: time.sleep(REQUEST_DELAY_SECONDS)

    with open(output_filename, "w", encoding="utf-8") as f:
        for data in hltb_data_to_save:
            f.write(f"{data['name']}:Main={data['main']};Extra={data['extra']};Completionist={data['completionist']}\n")
    print(f"✔ Tiempos de HowLongToBeat (directo de página) (re)generados y guardados en '{output_filename}'")

def main():
    print("--- Script de Scraping de HowLongToBeat (Scraping Directo de Página - Guardando HTML de Búsqueda) ---")
    games_to_scrape = read_games(GAMES_FILE_PATH)
    if games_to_scrape:
        scrape_and_save_hltb_times(games_to_scrape, HLTB_TIMES_FILE)
    else:
        print(f"Asegúrate de que '{GAMES_FILE_PATH}' existe y contiene nombres de juegos.")
    print("--- Fin del Script de Scraping de HowLongToBeat ---")

if __name__ == "__main__":
    main()