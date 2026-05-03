import json
import os
import threading
import requests
from datetime import datetime
from config import *
from core.loader import load_data
from core.analyzer import prepare, apply_analysis
from core.photo import download_photos
from core.excel import export_excel, format_excel

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

COOKIE_FILE = "cookie.json"


def create_session(progress_callback=None, login_event=None):

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    # =========================
    # COBA COOKIE
    # =========================
    if os.path.exists(COOKIE_FILE):

        log("Coba pakai cookie lama...")

        session = requests.Session()

        with open(COOKIE_FILE) as f:
            cookies = json.load(f)

        for c in cookies:
            session.cookies.set(c['name'], c['value'])

        # =========================
        # TEST COOKIE (KRITIS)
        # =========================
        try:
            test = session.get(
                "https://portalapp.iconpln.co.id/acmt/DisplayBlobServlet1",
                params={"idpel":"123","fotoke":1,"blth":"202401"},
                timeout=5
            )

            ct = test.headers.get("Content-Type","")
            if "image" in ct:
                log("Cookie valid ✔")
                return session, None
            else:
                log("Cookie expired ❌")

        except:
            log("Cookie error ❌")

    # =========================
    # LOGIN ULANG
    # =========================
    log("Buka browser untuk login...")

    opt = Options()
    opt.add_experimental_option("detach", True)

    driver = webdriver.Chrome(
        service=Service("chromedriver.exe"),
        options=opt
    )

    driver.get("https://portalapp.iconpln.co.id/acmt/")

    if login_event is not None:
        if progress_callback:
            progress_callback(("login_wait", None))
        login_event.wait()
    else:
        input("Login + captcha lalu ENTER...")

    cookies = driver.get_cookies()

    with open(COOKIE_FILE, "w") as f:
        json.dump(cookies, f)

    session = requests.Session()
    for c in cookies:
        session.cookies.set(c['name'], c['value'])

    log("Login berhasil ✔")

    return session, driver


def run_pipeline(dpm_path, blth, progress_callback=None, stop_flag=None, login_event=None):

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    def percent(p):
        if progress_callback:
            progress_callback(("percent", p))

    output_dir = os.path.join("hasil", blth)
    os.makedirs(output_dir, exist_ok=True)
    foto_dir = os.path.join(FOTO_DIR, blth)

    log("LOAD DATA")
    dpm, db, mode = load_data(dpm_path, DB_FILE)
    percent(5)

    log("PREPARE")
    df = prepare(dpm, db)
    percent(10)

    log("ANALYZE")
    df = apply_analysis(df)
    percent(20)

    session, driver = create_session(progress_callback, login_event=login_event)
    percent(25)

    log("DOWNLOAD FOTO")

    df_foto = df[df["STATUS"] != "Normal"]

    def photo_progress(data):
        if data["type"] == "photo":
            p = 25 + (data["done"] / data["total"]) * 50
            percent(p)
            if progress_callback:
                progress_callback(("eta", data["eta"]))

    results, bulan_list = download_photos(
        df_foto,
        session,
        BASE_URL,
        foto_dir,
        blth,
        MAX_WORKERS,
        progress_callback=photo_progress,
        stop_flag=stop_flag
    )

    percent(75)

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return

    log("EXPORT EXCEL")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"hasil_analisa_{timestamp}.xlsx")
    sheet_map = export_excel(df, output_file, bulan_list)
    percent(85)

    log("FORMAT EXCEL")
    format_excel(output_file, sheet_map, results, bulan_list)
    percent(100)

    try:
        if driver:
            driver.quit()
    except:
        pass

    log("SELESAI")