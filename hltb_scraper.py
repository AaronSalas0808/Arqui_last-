# hltb_scraper.py (Scraping directo - Refinando selección de juego y parseo de página)
import os
import time
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
import json # Para depurar

HLTB_TIMES_FILE = "howlongtobeat_times.txt"
GAMES_FILE_PATH = "games.txt"
REQUEST_DELAY_SECONDS = 7 # Aumentado ligeramente
DEBUG_HLTB_HTML = True

HLTB_BASE_URL = "https://howlongtobeat.com" # Sin / al final para urljoin
HLTB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    "Referer": HLTB_BASE_URL + "/",
    "DNT": "1", "Upgrade-Insecure-Requests": "1", "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-User": "?1",
}

def read_games(file_path: str) -> list:
    games = []
    if not os.path.exists(file_path):
        print(f"❌ Error: El archivo de juegos '{file_path}' no existe.")
        return games
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            games.append(line)
    return games

def format_hltb_string_time(time_string: str) -> str:
    if not time_string or "N/A" in time_string or "Not Available" in time_string: return "--"
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
    times = {"main": "--", "extra": "--", "completionist": "--"}
    main_story_patterns = ["Main Story", "Single-Player", "Solo"]
    main_extra_patterns = ["Main + Extras", "Main + Sides", "Story + Sides", "Main + DLC"]
    completionist_patterns = ["Completionist", "100%", "All Trophies/Achievements"]

    # Estrategia 1: Buscar la estructura de lista <ul><li> (común en páginas de detalle)
    # print(f"DEBUG HLTB ({game_name_for_debug}): Intentando Estrategia 1 (Listas ul/li) en página de juego.")
    # Selectores comunes para la tabla/lista de tiempos en la página de detalle
    # El diseño de 2023/2024 usa divs anidados, a menudo dentro de un contenedor con 'GameStats' o 'profile_details'
    # <div class="GameProfile_profile_summary__*"> o <div class="GameStats_game_times__*">
    #   <ul> o varios <div> que actúan como <li>
    #     <li title="Main Story"> o <div title="Main Story">
    #       <div>Main Story</div>
    #       <h5>10 Hours</h5> o <div>10 Hours</div>
    #     </li>
    #   </ul>
    # </div>
    
    # Buscar un contenedor principal de estadísticas de tiempo
    stats_container = soup.select_one('div[class*="GameProfile_profile_summary"], div[class*="GameStats_game_times"]')
    if not stats_container: # Fallback a un contenedor más general si el específico no se encuentra
        stats_container = soup.find('div', class_=lambda x: x and ('game_details' in x or 'profile_details' in x))
    
    elements_to_check = []
    if stats_container:
        # Buscar elementos de lista o divs que actúen como tales
        elements_to_check = stats_container.find_all(['li', 'div'], class_=lambda x: x and ('list_item' in x or 'TimeEntry_' in x or 'GameStats_game_times__box' in x), recursive=True)
        if not elements_to_check: # Si no hay clases específicas, tomar todos los li o divs directos
            elements_to_check = stats_container.find_all(['li', 'div'], recursive=False) # Hijos directos
            if not elements_to_check: # Si sigue vacío, buscar más profundamente
                 elements_to_check = stats_container.find_all(['li', 'div'], recursive=True, limit=10)


    # print(f"DEBUG HLTB ({game_name_for_debug}): Estrategia 1 - Encontrados {len(elements_to_check)} elementos de tiempo potenciales.")

    for item in elements_to_check:
        item_text_content = item.get_text(" ", strip=True)
        item_text_lower = item_text_content.lower()
        
        # El valor del tiempo suele estar en un <h5>, <div>, o <span> dentro del item
        time_value_element = item.find(['h5', 'div', 'span'], class_=lambda x: x and ('value' in x.lower() or 'time_stat' in x.lower() or 'GameStats_Value' in x or 'Time' in x)) # Clases más específicas
        if not time_value_element: # Fallback
            potential_time_elements = item.find_all(['h5', 'div', 'span'])
            for pte in potential_time_elements:
                if re.search(r"\d", pte.get_text(strip=True)): time_value_element = pte; break
            if not time_value_element and potential_time_elements: time_value_element = potential_time_elements[-1]
        
        time_value_str = ""
        if time_value_element: time_value_str = time_value_element.get_text(strip=True)
        else: time_value_str = item_text_content # Usar texto del item si no hay sub-elemento de tiempo

        # print(f"DEBUG HLTB ({game_name_for_debug}): Estrategia 1 - Item: '{item_text_lower[:60]}...', Tiempo crudo: '{time_value_str}'")

        if any(p.lower() in item_text_lower for p in main_story_patterns):
            if times["main"] == "--": times["main"] = format_hltb_string_time(time_value_str)
        elif any(p.lower() in item_text_lower for p in main_extra_patterns):
            if times["extra"] == "--": times["extra"] = format_hltb_string_time(time_value_str)
        elif any(p.lower() in item_text_lower for p in completionist_patterns):
            if times["completionist"] == "--": times["completionist"] = format_hltb_string_time(time_value_str)

    if not all(t == "--" for t in times.values()):
        # print(f"DEBUG HLTB ({game_name_for_debug}): Tiempos encontrados con Estrategia 1 (Listas/Bloques Detalle): {times}")
        return times

    # --- Estrategia 2: Parsear la estructura de divs "GameCard_search_list_tidbit" (si está en la página de detalle) ---
    # print(f"DEBUG HLTB ({game_name_for_debug}): Intentando Estrategia 2 (GameCard_search_list_tidbit) en página de juego.")
    all_tidbit_divs = soup.select('div[class*="GameCard_search_list_tidbit"]')
    if all_tidbit_divs:
        for i, div_element in enumerate(all_tidbit_divs):
            text_content = div_element.get_text(strip=True)
            if "Main Story" in text_content:
                if i + 1 < len(all_tidbit_divs):
                    next_div = all_tidbit_divs[i+1]
                    if next_div and 'center' in next_div.get('class', []) and 'time_100' in next_div.get('class', []):
                        if times["main"] == "--": times["main"] = format_hltb_string_time(next_div.get_text(strip=True))
            elif "Main + Extra" in text_content or "Main + Sides" in text_content:
                if i + 1 < len(all_tidbit_divs):
                    next_div = all_tidbit_divs[i+1]
                    if next_div and 'center' in next_div.get('class', []) and 'time_100' in next_div.get('class', []):
                        if times["extra"] == "--": times["extra"] = format_hltb_string_time(next_div.get_text(strip=True))
            elif "Completionist" in text_content:
                if i + 1 < len(all_tidbit_divs):
                    next_div = all_tidbit_divs[i+1]
                    if next_div and 'center' in next_div.get('class', []) and 'time_100' in next_div.get('class', []):
                        if times["completionist"] == "--": times["completionist"] = format_hltb_string_time(next_div.get_text(strip=True))
        # print(f"DEBUG HLTB ({game_name_for_debug}): Después Estrategia 2 (GameCard): {times}")
        if not all(t == "--" for t in times.values()): return times


    # --- Estrategia 3: Regex general sobre todo el texto de la página (último recurso) ---
    # print(f"DEBUG HLTB ({game_name_for_debug}): Intentando Estrategia 3 (Regex general) en página de juego.")
    all_page_text = ""
    if soup and soup.body: all_page_text = soup.body.get_text(" ", strip=True)
    if all_page_text:
        if times["main"] == "--":
            main_match = re.search(r"(?:Main Story|Single-Player|Solo)\s*[:\-]?\s*([\d\w\s½\.]+?)(?:\s+(?:Hours|Mins)|<|$|Main\s*\+|Completionist)", all_page_text, re.IGNORECASE)
            if main_match: times["main"] = format_hltb_string_time(main_match.group(1).strip())
        if times["extra"] == "--":
            extra_match = re.search(r"(?:Main\s*\+\s*(?:Extras|Sides)|Story \+ Sides)\s*[:\-]?\s*([\d\w\s½\.]+?)(?:\s+(?:Hours|Mins)|<|$|Completionist)", all_page_text, re.IGNORECASE)
            if extra_match: times["extra"] = format_hltb_string_time(extra_match.group(1).strip())
        if times["completionist"] == "--":
            comp_match = re.search(r"(?:Completionist|100%)\s*[:\-]?\s*([\d\w\s½\.]+?)(?:\s+(?:Hours|Mins)|<|$)", all_page_text, re.IGNORECASE)
            if comp_match: times["completionist"] = format_hltb_string_time(comp_match.group(1).strip())
        # print(f"DEBUG HLTB ({game_name_for_debug}): Después Estrategia 3 (Regex): {times}")
            
    return times


def get_single_game_hltb_page_scrape(game_name: str, session: requests.Session) -> dict:
    times = {"main": "--", "extra": "--", "completionist": "--"}
    search_query_encoded = urllib.parse.quote_plus(game_name)
    search_page_url = f"https://howlongtobeat.com/?q={search_query_encoded}"
    game_page_html_for_debug, search_page_html_for_debug, game_page_url_found = "", "", ""
    game_soup = None
    clean_game_name_for_file = re.sub(r'[^\w\s-]', '', game_name).replace(' ', '_')[:30]

    try:
        # print(f"    HLTB Scrape: Buscando «{game_name}» en URL: {search_page_url}")
        search_response = session.get(search_page_url, timeout=25, headers=HLTB_HEADERS)
        search_response.raise_for_status()
        search_page_html_for_debug = search_response.text
        search_soup = BeautifulSoup(search_page_html_for_debug, "html.parser")

        if DEBUG_HLTB_HTML:
            debug_search_filename = f"hltb_debug_searchpage_{clean_game_name_for_file}.html"
            with open(debug_search_filename, "w", encoding="utf-8") as df:
                df.write(f"<!-- URL de Búsqueda: {search_page_url} -->\n<!-- Juego Buscado: {game_name} -->\n")
                df.write(search_page_html_for_debug)

        # Lógica para encontrar el mejor enlace en la página de resultados
        game_cards = search_soup.select('div[class*="GameCard_search_list__"], li[class*="GameCard_search_list__"]') # Contenedor de cada resultado
        if not game_cards: game_cards = search_soup.select('li[class*="search_list_item"]') # Fallback

        best_match_link_href = None
        highest_similarity_score = -0.1

        for card in game_cards:
            link_element = card.find('a', href=re.compile(r"/game/\d+")) # Enlace a la página del juego
            if not link_element: continue

            title_element = card.find(['h2','h3','div'], class_=lambda x: x and ('title' in x.lower() or 'GameCard_title' in x))
            if not title_element: title_element = link_element # Usar el texto del enlace si no hay título específico
            
            link_title_text = title_element.get_text(strip=True) if title_element else ""
            if not link_title_text and link_element: link_title_text = link_element.get('title', '') # Atributo title del enlace
            if not link_title_text and link_element: # Texto directo del enlace como último recurso
                direct_texts = link_element.find_all(string=True, recursive=False)
                link_title_text = " ".join(t.strip() for t in direct_texts if t.strip())


            normalized_link_title = link_title_text.lower()
            normalized_game_name = game_name.lower()
            current_similarity = 0
            if normalized_link_title:
                if normalized_game_name == normalized_link_title: current_similarity = 1.0
                elif normalized_game_name in normalized_link_title: current_similarity = 0.7 + (len(normalized_game_name) / len(normalized_link_title)) * 0.2
                elif normalized_link_title in normalized_game_name: current_similarity = 0.4 + (len(normalized_link_title) / len(normalized_game_name)) * 0.2
            
            # print(f"      HLTB Scrape: Candidato: '{link_title_text}' (Sim: {current_similarity:.2f}) para '{game_name}'")

            if current_similarity > highest_similarity_score:
                highest_similarity_score = current_similarity
                best_match_link_href = link_element.get('href')
                if current_similarity >= 0.95: break # Si es una coincidencia muy alta, tomarla
        
        if best_match_link_href:
            game_page_url_found = urllib.parse.urljoin(HLTB_BASE_URL, best_match_link_href)
            # print(f"    HLTB Scrape: URL de página de juego para «{game_name}»: {game_page_url_found}")

            game_page_response = session.get(game_page_url_found, timeout=20, headers=HLTB_HEADERS)
            game_page_response.raise_for_status()
            game_page_html_for_debug = game_page_response.text
            game_soup = BeautifulSoup(game_page_html_for_debug, "html.parser") 
            
            if game_soup: times = get_game_page_times(game_soup, game_name)

            if DEBUG_HLTB_HTML and game_soup and all(t == "--" for t in times.values()):
                debug_gamepage_filename = f"hltb_debug_gamepage_no_times_{clean_game_name_for_file}.html"
                with open(debug_gamepage_filename, "w", encoding="utf-8") as df:
                    df.write(f"<!-- URL Página Juego: {game_page_url_found} -->\n<!-- Juego: {game_name} -->\n")
                    df.write(game_page_html_for_debug)
        # else:
            # print(f"    HLTB Scrape: No se encontró enlace para «{game_name}» en la página de búsqueda.")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code != 404: print(f"    Error HTTP HLTB Scrape para '{game_name}': {e}")
    except requests.exceptions.RequestException as e: print(f"    Error de red HLTB Scrape para '{game_name}': {e}")
    except Exception as e: print(f"    Error general en HLTB Scrape para '{game_name}' ({type(e).__name__}): {e}")
    return times

def scrape_and_save_hltb_times(games_list: list, output_filename: str):
    if not games_list:
        print("ℹ️ No hay juegos en la lista para buscar tiempos de HowLongToBeat.")
        return
    print(f"ℹ️ Iniciando scraping (directo de página) de HowLongToBeat para {len(games_list)} juegos (delay: {REQUEST_DELAY_SECONDS}s)...")
    hltb_data_to_save = []
    with requests.Session() as session:
        # No es necesario actualizar session.headers aquí si HLTB_HEADERS se pasa a session.get/post
        try: session.get(HLTB_BASE_URL, timeout=15, headers=HLTB_HEADERS) # Visita inicial con headers
        except requests.RequestException as e: print(f"    HLTB Scrape: Falló visita inicial a howlongtobeat.com: {e}")
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
    print("--- Script de Scraping de HowLongToBeat (Scraping Directo de Página - Refinado) ---")
    games_to_scrape = read_games(GAMES_FILE_PATH)
    if games_to_scrape:
        scrape_and_save_hltb_times(games_to_scrape, HLTB_TIMES_FILE)
    else:
        print(f"Asegúrate de que '{GAMES_FILE_PATH}' existe y contiene nombres de juegos.")
    print("--- Fin del Script de Scraping de HowLongToBeat ---")

if __name__ == "__main__":
    main()