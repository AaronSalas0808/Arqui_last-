import asyncio
import json
from playwright.async_api import async_playwright, Playwright
from urllib.parse import quote

async def main():
    try:
        with open("games.txt", "r", encoding="utf-8") as f:
            juegos = [line.strip() for line in f if line.strip()]
        if not juegos:
            return
    except FileNotFoundError:
        return

    with open("hltb_times.txt", "w", encoding="utf-8") as f:
        f.write("")

    headless_mode = True
    resultados = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless_mode)
        user_agent_string = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
        context = await browser.new_context(
            user_agent=user_agent_string,
            viewport={"width": 1920, "height": 1080},
        )

        for juego in juegos:
            page = await context.new_page()

            try:
                search_url = f"https://howlongtobeat.com/?q={quote(juego)}"
                await page.goto(
                    search_url, wait_until="domcontentloaded", timeout=30000
                )
                await page.wait_for_selector(
                    "div.GameCard_inside_blur__cP8_l", timeout=15000
                )
                first_link_element = await page.query_selector(
                    "div.GameCard_inside_blur__cP8_l a"
                )
                if not first_link_element:
                    raise Exception("No se encontró el primer juego")

                href = await first_link_element.get_attribute("href")
                full_url = (
                    href
                    if href.startswith("http")
                    else f"https://howlongtobeat.com{href}"
                )
                await page.goto(
                    full_url, wait_until="domcontentloaded", timeout=30000
                )
                await page.wait_for_selector(
                    "div.GameHeader_profile_header__q_PID", timeout=10000
                )
                await page.wait_for_selector(
                    "li.GameStats_short__tSJ6I.time_100 h5", timeout=10000
                )

                data = await page.evaluate(
                    """
                    () => {
                        const nameEl = document.querySelector('div.GameHeader_profile_header__q_PID');
                        const timeEl = document.querySelector('li.GameStats_short__tSJ6I.time_100 h5');
                        const name = nameEl?.textContent.trim() ?? 'Nombre no disponible';
                        const time = timeEl?.textContent.trim() ?? 'Duración no disponible';
                        return { name, time };
                    }
                """
                )

                resultados.append(data)

                # --- NUEVA LÍNEA: GUARDAR RESULTADO EN TXT ---
                with open("hltb_times.txt", "a", encoding="utf-8") as txt_file:
                    txt_file.write(f"{data['name']} — {data['time']}\n")

            except Exception as e:
                resultados.append({"name": juego, "time": "No disponible"})

                # --- NUEVA LÍNEA: GUARDAR ERROR EN TXT ---
                with open("hltb_times.txt", "a", encoding="utf-8") as txt_file:
                    txt_file.write(f"{juego} — No disponible\n")

            finally:
                await page.close()
                await asyncio.sleep(1.5)

        await context.close()
        await browser.close()


asyncio.run(main())