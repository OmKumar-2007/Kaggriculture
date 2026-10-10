"""Browser smoke for contestant and admin pages on the isolated port 18000."""
from __future__ import annotations

import secrets
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

BASE = "http://127.0.0.1:18000"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
OUTPUT = Path(__file__).with_name("data")
CONTESTANT_TABS = ["Bot Lab", "Strategy Path", "sandbox", "analytics", "submissions",
                   "leaderboard", "tournament", "guide"]
ADMIN_TABS = ["Overview", "Competition Setup", "Reference Bots", "Round 1 Qualification",
              "Round 2 Bracket", "Teams & Sessions", "Submissions & Jobs",
              "Evaluation Pipeline", "Tournament & Matches", "Workers & Devices",
              "System Health", "Tournament Controls", "Audit Logs"]


def recovery_identity():
    client = requests.Session()
    login = client.post(BASE + "/api/admin/login", json={"password": "load-test-organizer"}, timeout=10)
    login.raise_for_status()
    client.headers["X-Admin-CSRF"] = login.json()["csrfToken"]
    status = client.get(BASE + "/tournament/status", timeout=10).json()
    team = status["champion"]["username"]
    recovered = client.post(BASE + f"/api/admin/contestants/{team}/recovery",
                            json={"confirmation": "RESET SESSION"}, timeout=10)
    recovered.raise_for_status()
    return team, recovered.json()["recoveryCode"]


def main():
    assert CHROME.is_file(), "Installed Chrome is required for browser smoke."
    OUTPUT.mkdir(exist_ok=True)
    problems = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        contestant = browser.new_context(viewport={"width": 1440, "height": 900})
        page = contestant.new_page()
        page.on("pageerror", lambda error: problems.append(f"contestant JS: {error}"))
        page.on("response", lambda response: problems.append(f"contestant HTTP {response.status}: {response.url}")
                if response.status >= 500 else None)
        page.goto(BASE, wait_until="networkidle")
        page.get_by_label("Your team name").fill("ui_" + secrets.token_hex(4))
        page.get_by_role("button", name="Enter FarmCraft").click()
        try:
            page.locator(".product-nav").wait_for(timeout=3000)
        except PlaywrightTimeout:
            team, code = recovery_identity()
            page.get_by_role("button", name="Already registered? Recover with the organizer").click()
            page.get_by_label("Your team name").fill(team)
            page.get_by_label("Organizer recovery code").fill(code)
            page.get_by_role("button", name="Recover team").click()
            page.locator(".product-nav").wait_for()
        for label in CONTESTANT_TABS:
            page.locator(".product-nav button").filter(has_text=label).click()
            page.wait_for_timeout(300)
            assert page.locator("main").count() >= 1, f"{label} did not render"
        page.locator(".product-nav button").filter(has_text="tournament").click()
        page.wait_for_timeout(1200)
        if page.locator(".champion-reveal").count():
            assert page.locator(".champion-reveal").is_visible()
            champion = requests.get(BASE + "/tournament/status", timeout=10).json()["champion"]["username"]
            assert champion.upper() in page.locator(".champion-reveal").inner_text().upper()
        page.screenshot(path=str(OUTPUT / "contestant-desktop.png"), full_page=True)
        broken = page.locator("img").evaluate_all("items => items.filter(i => i.complete && i.naturalWidth === 0).map(i => i.src)")
        assert not broken, f"Broken contestant images: {broken}"

        admin = browser.new_context(viewport={"width": 1440, "height": 900})
        control = admin.new_page()
        control.on("pageerror", lambda error: problems.append(f"admin JS: {error}"))
        control.on("response", lambda response: problems.append(f"admin HTTP {response.status}: {response.url}")
                   if response.status >= 500 else None)
        control.goto(BASE + "/admin", wait_until="networkidle")
        control.get_by_label("Organizer password").fill("load-test-organizer")
        control.get_by_role("button", name="Enter", exact=True).click()
        control.locator(".admin-sidebar").wait_for()
        for label in ADMIN_TABS:
            control.locator(".admin-sidebar nav button").filter(has_text=label).click()
            control.wait_for_timeout(350)
            assert control.locator(".admin-top h1").inner_text() == label
        control.locator(".admin-sidebar nav button").filter(has_text="Overview").click()
        control.wait_for_timeout(1200)
        control.screenshot(path=str(OUTPUT / "admin-desktop.png"), full_page=True)

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                                     device_scale_factor=1)
        phone = mobile.new_page()
        phone.goto(BASE, wait_until="networkidle")
        phone.screenshot(path=str(OUTPUT / "entry-mobile.png"), full_page=True)
        assert phone.locator(".entry-card").is_visible()
        browser.close()
    assert not problems, "\n".join(problems)
    print(f"Browser smoke passed: {len(CONTESTANT_TABS)} contestant tabs, "
          f"{len(ADMIN_TABS)} admin tabs, desktop and mobile. Screenshots: {OUTPUT}")


if __name__ == "__main__":
    main()
