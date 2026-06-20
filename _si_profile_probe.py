"""Intercept the Startup India per-company PROFILE detail API (founders, website,
socials, contact) by loading a public profile page and capturing its XHRs."""
import json
from playwright.sync_api import sync_playwright

SID = "6a2fd199e4b06921f1d4d76d"  # a sample company id from our table
CAPTURED = []


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0", locale="en-IN")
        page = ctx.new_page()

        def on_resp(resp):
            u = resp.url
            if "api.startupindia.gov.in" in u and resp.request.method in ("GET", "POST") and SID[:12] in u.replace("/", "") + u:
                pass
            if "api.startupindia.gov.in" in u and ("profile" in u.lower() or "detail" in u.lower() or SID in u or "user" in u.lower()):
                try:
                    CAPTURED.append((u, resp.request.method, resp.json()))
                except Exception:
                    CAPTURED.append((u, resp.request.method, None))

        page.on("response", on_resp)
        # try the common public profile URL patterns
        for url in [
            f"https://www.startupindia.gov.in/content/sih/en/profile.html?user={SID}",
            f"https://www.startupindia.gov.in/content/sih/en/profile.html?actorType=Startup&id={SID}",
        ]:
            try:
                page.goto(url, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(8000)
            except Exception as e:
                print("nav err:", str(e)[:120])
            if CAPTURED:
                break
        b.close()

    print(f"captured {len(CAPTURED)} profile API call(s)")
    for u, m, body in CAPTURED[:6]:
        print("\nURL:", m, u)
        if isinstance(body, dict):
            d = body.get("data", body)
            keys = list(d.keys()) if isinstance(d, dict) else "(list)"
            print("keys:", keys if isinstance(keys, str) else keys[:40])
            # surface the fields we care about
            if isinstance(d, dict):
                for f in ("name", "website", "websiteUrl", "url", "founders", "members",
                          "linkedin", "linkedinUrl", "socialMedia", "email", "phone",
                          "mobile", "contactNumber", "about", "primaryContact", "user"):
                    if f in d:
                        print(f"  {f}: {str(d[f])[:160]}")
            print("RAW(1200):", json.dumps(body)[:1200])


if __name__ == "__main__":
    main()
