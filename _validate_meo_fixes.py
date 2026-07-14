# -*- coding: utf-8 -*-
"""
MEO緊急トラックA（2026-07-13）の受け入れ基準を機械検証する。
対象: articles/clinics/*.html 全件 + sitemap.xml
チェック項目:
  A-1: noindexが薄い院に付与され、厚い院には付いていない（誤爆ゼロ）／
       薄い院がsitemapに載っていない／薄い院ページに定型空文が出ていない
  A-2: canonicalが全院ページに1本／canonical == og:url == JSON-LD url == Breadcrumb最終item
  A-3: openingHoursSpecificationの形式（曜日enum・HH:MM）／PostalAddressにlocality・region／
       aggregateRating・review markupが1件も無い／旧openingHours（日本語文）が残っていない
  A-4: schemaのtelephoneに共有電話番号（2院以上で共用）が入っていない
  補足: meta descriptionが文の途中で切れていない
実行: python3 _validate_meo_fixes.py
"""
import json, os, re, sys, random
from html import unescape

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from thin_page_policy import is_thin, THIN_AI_MARKERS
from build_clinics import compute_shared_phones, slugify

db = json.load(open(os.path.join(ROOT, "clinic_db.json"), encoding="utf-8"))
clinics = list(db.values()) if isinstance(db, dict) else db
slug_map = json.load(open(os.path.join(ROOT, "clinic_slugs.json"), encoding="utf-8"))
pub = [c for c in clinics if c.get("name") and not c.get("q_excluded")]
shared = compute_shared_phones(clinics)
sitemap = open(os.path.join(ROOT, "sitemap.xml"), encoding="utf-8").read()

DAY_OK = {f"https://schema.org/{d}" for d in
          ("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday")}
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

errors, warns = [], []
n_thin = n_thick = 0
n_ohs = n_addr_loc = n_zip = n_tel = n_tel_suppressed = 0

for c in pub:
    slug = slug_map.get(c.get("place_id"), slugify(c["name"]))
    path = os.path.join(ROOT, "articles", "clinics", slug + ".html")
    if not os.path.exists(path):
        errors.append(f"[missing] {slug}.html が存在しない（{c.get('name')}）")
        continue
    html_src = open(path, encoding="utf-8").read()
    thin = is_thin(c)
    has_noindex = 'content="noindex,follow"' in html_src

    # A-1
    if thin:
        n_thin += 1
        if not has_noindex:
            errors.append(f"[A-1] 薄い院にnoindexが無い: {slug}")
        if f"/articles/clinics/{slug}.html" in sitemap or f"clinics/{slug}.html" in sitemap:
            # sitemapはURLエンコード済みのため、エンコードした形でも突合する
            pass
        for m in THIN_AI_MARKERS:
            if m in html_src:
                errors.append(f"[A-1] 薄い院ページに定型空文が残存: {slug} ({m})")
                break
    else:
        n_thick += 1
        if has_noindex:
            errors.append(f"[A-1] 厚い院にnoindexが付いている（誤爆）: {slug}")

    # A-2: canonical == og:url == JSON-LD url == Breadcrumb
    can = re.findall(r'<link rel="canonical" href="([^"]+)"', html_src)
    og = re.findall(r'<meta property="og:url" content="([^"]+)"', html_src)
    if len(can) != 1:
        errors.append(f"[A-2] canonicalが{len(can)}本: {slug}")
        continue
    ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_src, re.S)
    dentist = crumb = None
    for b in ld_blocks:
        try:
            d = json.loads(unescape(b))
        except Exception as e:
            errors.append(f"[A-3] JSON-LDがパース不能: {slug}: {e}")
            continue
        if d.get("@type") == "Dentist":
            dentist = d
        elif d.get("@type") == "BreadcrumbList":
            crumb = d
    if not dentist:
        errors.append(f"[A-3] Dentist schemaが無い: {slug}")
        continue
    urls = {can[0], og[0] if og else None, dentist.get("url")}
    if crumb:
        urls.add(crumb["itemListElement"][-1].get("item"))
    if None in urls or len(urls) != 1:
        errors.append(f"[A-2] URL不一致: {slug}: {urls}")

    # A-3
    if "aggregateRating" in html_src or '"review"' in html_src:
        errors.append(f"[A-3] aggregateRating/reviewが混入: {slug}")
    if '"openingHours"' in html_src:
        errors.append(f"[A-3] 旧openingHours（日本語文）が残存: {slug}")
    ohs = dentist.get("openingHoursSpecification") or []
    if ohs:
        n_ohs += 1
        for s in ohs:
            if s.get("dayOfWeek") not in DAY_OK or not TIME_RE.match(s.get("opens","")) or not TIME_RE.match(s.get("closes","")):
                errors.append(f"[A-3] openingHoursSpecification形式不正: {slug}: {s}")
                break
    addr = dentist.get("address") or {}
    if addr:
        if addr.get("addressLocality"):
            n_addr_loc += 1
        elif re.search(r"[市区]", c.get("address") or ""):
            warns.append(f"[A-3] addressLocality欠落: {slug}: {c.get('address','')[:30]}")
        if not addr.get("addressRegion"):
            errors.append(f"[A-3] addressRegion欠落: {slug}")
        if addr.get("postalCode"):
            n_zip += 1

    # A-4
    tel = dentist.get("telephone")
    phone = (c.get("phone") or "").strip()
    if tel:
        n_tel += 1
        if tel in shared:
            errors.append(f"[A-4] 共有電話番号がschemaに残存: {slug}: {tel}")
    elif phone and phone in shared:
        n_tel_suppressed += 1
        if phone not in html_src:
            warns.append(f"[A-4] 表示側の電話まで消えている: {slug}")

    # 補足: description語尾
    md = re.search(r'<meta name="description" content="([^"]*)"', html_src)
    if md:
        d = unescape(md.group(1)).strip()
        if d and not re.search(r"[。…！？）」]$", d):
            warns.append(f"[補足] description語尾切れの疑い: {slug}: …{d[-25:]}")

# sitemap側: 薄い院URLの混入チェック（URLエンコードで突合）
from urllib.parse import quote
thin_in_sitemap = []
for c in pub:
    if not is_thin(c):
        continue
    slug = slug_map.get(c.get("place_id"), slugify(c["name"]))
    if quote(f"articles/clinics/{slug}", safe="/-_.~") + "</loc>" in sitemap:
        thin_in_sitemap.append(slug)
if thin_in_sitemap:
    errors.append(f"[A-1] sitemapに薄い院が混入: {len(thin_in_sitemap)}件 例: {thin_in_sitemap[:3]}")
# 厚い院がsitemapに全部載っているか
thick_missing = []
for c in pub:
    if is_thin(c):
        continue
    slug = slug_map.get(c.get("place_id"), slugify(c["name"]))
    if quote(f"articles/clinics/{slug}", safe="/-_.~") + "</loc>" not in sitemap:
        thick_missing.append(slug)
if thick_missing:
    errors.append(f"[A-1] sitemapから厚い院が欠落: {len(thick_missing)}件 例: {thick_missing[:3]}")

print(f"検証対象: {len(pub)}院（薄い {n_thin} / 厚い {n_thick}）")
print(f"openingHoursSpecificationあり: {n_ohs}院 / addressLocalityあり: {n_addr_loc}院 / postalCodeあり: {n_zip}院")
print(f"schema telephoneあり: {n_tel}院 / 共有番号のため抑止: {n_tel_suppressed}院")
print(f"\nエラー: {len(errors)}")
for e in errors[:30]:
    print("  ✗", e)
print(f"警告: {len(warns)}")
for w in warns[:15]:
    print("  ⚠", w)
sys.exit(1 if errors else 0)
